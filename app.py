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
        "icp_summary": "2-sentence summary of the ideal customer"
    }}
    """

    result = ask_groq(prompt)
    start = result.find("{")
    end = result.rfind("}") + 1
    if start != -1 and end > start:
        result = result[start:end]
    icp = json.loads(result)
    return jsonify(icp)


# ── 2. Search for leads via Hunter ───────────────────────────────────────────
@app.route("/search-leads", methods=["POST"])
def search_leads():
    data = request.json
    icp = data.get("icp", {})
    service_description = data.get("service_description", "")
    country = data.get("country", "Malaysia")

    industries = icp.get("target_industries", [])
    keywords = icp.get("search_keywords", [])
    job_titles = icp.get("job_titles_to_target", [])

    # Ask Groq to suggest real company domains in the target country
    prompt = f"""
    A service provider offers: {service_description}
    Target country: {country}
    Target industries: {', '.join(industries)}
    Target job titles: {', '.join(job_titles)}
    Additional keywords: {', '.join(keywords)}

    List 10 real company website domains based in {country} that would be ideal customers for this service.
    Focus on small to medium sized local businesses in {country}, NOT global giants like Amazon, Google, PayPal or IBM.
    For example, if country is Malaysia, suggest companies like maybank.com, cimb.com, airasia.com, petronas.com, etc.
    Return ONLY a JSON array of domain strings, no explanation:
    ["domain1.com", "domain2.com"]
    """

    domains_raw = ask_groq(prompt)
    try:
        start = domains_raw.find("[")
        end = domains_raw.rfind("]") + 1
        if start != -1 and end > start:
            domains_raw = domains_raw[start:end]
        domains = json.loads(domains_raw)
    except:
        # Fallback domains based on country
        fallbacks = {
            "Malaysia": ["maybank.com", "cimb.com", "airasia.com", "maxis.com.my", "celcom.com.my", "digi.com.my", "petronas.com", "rhbgroup.com"],
            "Singapore": ["dbs.com.sg", "ocbc.com", "singtel.com", "grab.com", "shopee.com", "lazada.com.sg"],
            "Indonesia": ["tokopedia.com", "gojek.com", "bukalapak.com", "traveloka.com", "blibli.com"],
            "Global": ["hubspot.com", "salesforce.com", "shopify.com", "zendesk.com", "freshworks.com"],
        }
        domains = fallbacks.get(country, fallbacks["Global"])

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
                },
                timeout=10
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
                    title = e.get("position", "")
                    leads.append({
                        "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                        "title": title,
                        "email": e.get("value", ""),
                        "company": company,
                        "industry": ", ".join(industries[:2]),
                        "employees": "",
                        "website": website,
                        "linkedin": e.get("linkedin", ""),
                        "country": country,
                    })
        except Exception as e:
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
        try:
            prompt = f"""
            Service offered: {service_description}

            Ideal Customer Profile:
            {json.dumps(icp, indent=2)}

            Lead:
            - Name: {lead.get('name', '')}
            - Title: {lead.get('title', '')}
            - Company: {lead.get('company', '')}
            - Industry: {lead.get('industry', '')}
            - Website: {lead.get('website', '')}
            - Country: {lead.get('country', '')}

            Return ONLY a JSON object with no extra text, no explanation, no markdown:
            {{"score": 7, "fit_reason": "one sentence reason", "email_subject": "subject line", "email_body": "3 paragraph personalized cold email"}}
            """

            result = ask_groq(prompt)
            result = result.strip()
            result = result.replace("```json", "").replace("```", "").strip()
            start = result.find("{")
            end = result.rfind("}") + 1
            if start != -1 and end > start:
                result = result[start:end]

            qualification = json.loads(result)
            lead.update(qualification)

        except Exception as e:
            lead.update({
                "score": 5,
                "fit_reason": "Potential match based on industry alignment.",
                "email_subject": f"Quick question for {lead.get('company', 'your team')}",
                "email_body": f"Hi {lead.get('name', 'there')},\n\nI came across {lead.get('company', 'your company')} and wanted to reach out about how {service_description} could help your team.\n\nWould you be open to a quick 15-minute chat?\n\nBest regards"
            })

        qualified.append(lead)

    qualified.sort(key=lambda x: x.get("score", 0), reverse=True)
    return jsonify(qualified)


# ── Health check ─────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True)
