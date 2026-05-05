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
    A service p
