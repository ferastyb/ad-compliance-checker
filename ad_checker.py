# ad_checker.py (Enhanced AD Compliance Checker UI)

import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number = st.text_input("Enter AD Number (e.g., 2020-06-14):").strip()

def fetch_ad_data(ad_number):
    base_url = "https://www.federalregister.gov/api/v1/documents.json"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(
            base_url,
            params={"conditions[term]": ad_number, "per_page": 10},
            headers=headers,
            timeout=10
        )
        response.raise_for_status()

        results = response.json().get("results", [])
        for doc in results:
            if ad_number == doc.get("document_number"):
                return {
                    "title": doc.get("title"),
                    "effective_date": doc.get("effective_on"),
                    "html_url": doc.get("html_url"),
                    "pdf_url": doc.get("pdf_url")
                }

    except requests.RequestException as e:
        st.error(f"Request failed: {e}")

    return None

def extract_details_from_html(html_url):
    try:
        html = requests.get(html_url, headers={"User-Agent": "Mozilla/5.0"}).text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")

        aircraft = ", ".join(re.findall(r"Model [\w\-]+", text)) or "Not found"
        sb_refs = ", ".join(re.findall(r"SB[ \-]?[0-9A-Z]+", text)) or "Not found"
        actions = "\n".join(re.findall(r"(?i)(?:Before further flight|Do the following|Comply .*?)\n.*?(?=\n\n|$)", text)) or "Not found"
        deadlines = "\n".join(re.findall(r"(?i)(within \d+ .*?|before .*? compliance|no later than .*?)\n", text)) or "Not found"

        return {
            "affected_aircraft": aircraft,
            "sb_references": sb_refs,
            "required_actions": actions,
            "compliance_deadlines": deadlines
        }

    except Exception as e:
        return {"error": str(e)}

if ad_number:
    with st.spinner("🔍 Searching Federal Register..."):
        data = fetch_ad_data(ad_number)

    if data:
        st.success(f"✅ Found AD {ad_number}")
        st.write(f"**Title:** {data['title']}")
        st.write(f"**Effective Date:** {data['effective_date']}")
        st.markdown(f"[🔗 View Full AD (HTML)]({data['html_url']})")
        st.markdown(f"[📄 View PDF]({data['pdf_url']})")

        st.markdown("---")
        st.subheader("🧠 Extracted Key Details")

        details = extract_details_from_html(data['html_url'])
        if "error" in details:
            st.error(f"❌ Failed to extract details: {details['error']}")
        else:
            st.write(f"**Affected Aircraft:** {details['affected_aircraft']}")
            st.write(f"**Service Bulletin References:** {details['sb_references']}")
            st.write(f"**Compliance Deadlines:**\n{details['compliance_deadlines']}")
            st.write(f"**Required Actions:**\n{details['required_actions']}")

    else:
        st.error("❌ AD not found. Please check the number exactly as it appears (e.g., 2020-06-14).")
