from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
import requests
import os
import json

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY")

client = Groq(api_key=GROQ_API_KEY)

def ask_groq(prompt):
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return raw


# ── 1. Analyze user's service and build ICP ──────────────────────────────────
@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json
    service_description = data.get("service_description", "")

    prompt = f"""
    A user offers the following product or service:
    "{service_description}"

    Based on this, extract their Ideal Customer Profile (ICP) and return ONLY a JSON object with no extra text, no explanation:
    {{
        "target_industries": ["industry1", "industry2"],
        "company_size": {{ "min": 10, "max": 500 }},
        "company_stage": ["startup", "growth", "enterprise"],
        "pain_points": ["pain1", "pain2", "pain3"],
        "job_titles_to_target": ["title1", "title2"],
        "icp_summary": "2-sentence summary of the ideal customer",
        "search_keywords": ["keyword1", "keyword2", "keyword3"]
    }}
    """

    result = ask_groq(prompt)
    icp = json.loads(result)
    return jsonify(icp)


# ── 2. Search for leads via Hunter ───────────────────────────────────────────
@app.route("/search-leads", methods=["POST"])
def search_leads():
    data = request.json
    icp = data.get("icp", {})
    service_description = data.get("service_description", "")

    # Ask Groq to suggest real company domains to target
    prompt = f"""
    A service provider offers: {service_description}

    Their ideal customer industries are: {', '.join(icp.get('target_industries', []))}
    Target job titles: {', '.join(icp.get('job_titles_to_target', []))}

    List 10 real company website domains (just the domain, e.g. "maybank.com") that would be ideal customers.
    Focus on well-known companies. Return ONLY a JSON array of strings, no explanation:
    ["domain1.com", "domain2.com", ...]
    """

    domains_raw = ask_groq(prompt)
    try:
        domains = json.loads(domains_raw)
    except:
        domains = ["grab.com", "lazada.com", "airasia.com", "petronas.com", "celcom.com.my"]

    leads = []
    seen = set()

    for domain in domains[:8]:
        try:
            res = requests.get(
                "https://api.hunter.io/v2/domain-search",
                params={
                    "domain": domain,
                    "api_key": HUNTER_API_KEY,
                    "limit": 3,
                    "seniority": "senior,executive",
                }
            )
            result = res.json().get("data", {})
            if not result:
                continue

            company = result.get("organization", domain)
            website = f"https://{domain}"
            emails = result.get("emails", [])

            if domain not in seen and emails:
                seen.add(domain)
                for e in emails[:2]:
                    leads.append({
                        "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                        "title": e.get("position", ""),
                        "email": e.get("value", ""),
                        "company": company,
                        "industry": ", ".join(icp.get("target_industries", [])[:2]),
                        "employees": "",
                        "website": website,
                        "linkedin": e.get("linkedin", ""),
                    })
        except:
            continue

    return jsonify(leads)

# ── 3. Score leads and write outreach email ──────────────────────────────────
@app.route("/qualify-leads", methods=["POST"])
def qualify_leads():
    data = request.json
    leads = data.get("leads", [])
    icp = data.get("icp", {})
    service_description = data.get("service_description", "")

    qualified = []

    for lead in leads:
        prompt = f"""
        Service offered: {service_description}

        Ideal Customer Profile:
        {json.dumps(icp, indent=2)}

        Lead:
        - Name: {lead['name']}
        - Title: {lead['title']}
        - Company: {lead['company']}
        - Industry: {lead['industry']}
        - Website: {lead['website']}

        Return ONLY a JSON object with no extra text, no explanation:
        {{
            "score": <1-10 integer>,
            "fit_reason": "1 sentence why this lead fits",
            "email_subject": "catchy subject line",
            "email_body": "3-paragraph personalized cold email"
        }}
        """

        result = ask_groq(prompt)
        qualification = json.loads(result)
        lead.update(qualification)
        qualified.append(lead)

    qualified.sort(key=lambda x: x.get("score", 0), reverse=True)
    return jsonify(qualified)


# ── Health check ─────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True)
