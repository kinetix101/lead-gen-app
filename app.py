from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
import requests
import os
import json

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY")

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
        "icp_summary": "2-sentence summary of the ideal customer"
    }}
    """

    result = ask_groq(prompt)
    icp = json.loads(result)
    return jsonify(icp)


# ── 2. Search for leads via Apollo ───────────────────────────────────────────
@app.route("/search-leads", methods=["POST"])
def search_leads():
    data = request.json
    icp = data.get("icp", {})

    payload = {
        "api_key": APOLLO_API_KEY,
        "per_page": 10,
        "person_titles": icp.get("job_titles_to_target", ["CEO", "Founder"]),
        "organization_num_employees_ranges": [
            f"{icp['company_size']['min']},{icp['company_size']['max']}"
        ],
    }

    industries = icp.get("target_industries", [])
    if industries:
        payload["q_organization_keyword_tags"] = industries

    res = requests.post(
        "https://api.apollo.io/v1/mixed_people/search",
        json=payload
    )

    people = res.json().get("people", [])

    leads = []
    for p in people:
        org = p.get("organization") or {}
        leads.append({
            "name": p.get("name", ""),
            "title": p.get("title", ""),
            "email": p.get("email", ""),
            "company": org.get("name", ""),
            "industry": org.get("industry", ""),
            "employees": org.get("num_employees", ""),
            "website": org.get("website_url", ""),
            "linkedin": p.get("linkedin_url", ""),
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
        - Employees: {lead['employees']}
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
