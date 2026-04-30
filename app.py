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
        model="llama3-70b-8192",
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

    keywords = icp.get("search_keywords", [])
    industries = icp.get("target_industries", [])
    search_terms = keywords + industries

    leads = []
    seen_domains = set()

    for term in search_terms[:3]:
        res = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={
                "company": term,
                "api_key": HUNTER_API_KEY,
                "limit": 5,
                "seniority": "senior,executive",
            }
        )

        result = res.json().get("data", {})
        domain = result.get("domain", "")
        company = result.get("organization", term)
        emails = result.get("emails", [])

        if domain and domain not in seen_domains and emails:
            seen_domains.add(domain)
            for e in emails[:3]:
                title = e.get("position", "")
                targeted_titles = [t.lower() for t in icp.get("job_titles_to_target", [])]
                if any(t in title.lower() for t in targeted_titles) or not targeted_titles:
                    leads.append({
                        "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                        "title": title,
                        "email": e.get("value", ""),
                        "company": company,
                        "industry": ", ".join(industries[:2]),
                        "employees": "",
                        "website": f"https://{domain}",
                        "linkedin": e.get("linkedin", ""),
                    })

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
