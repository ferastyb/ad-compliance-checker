# ad_checker.py

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
            params={"conditions[term]": f"Airworthiness Directive {ad_number}", "per_page": 25},
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        results = response.json().get("results", [])

        for doc in results:
            title = doc.get("title", "")
            if ad_number in title or "airworthiness directive" in title.lower():
                return {
                    "title": title,
                    "effective_date": doc.get("effective_on"),
                    "html_url": doc.get("html_url"),
                    "pdf_url": doc.get("pdf_url"),
                    "document_number": doc.get("document_number")
                }

    except requests.RequestException as e:
        st.error(f"❌ Request failed: {e}")

    return None

def extract_details_from_html(html_url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(html_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(separator="\n")

        # Use regex or keyword search to extract relevant blocks
        def find_block(keyword, window=1000):
            idx = text.lower().find(keyword.lower())
            if idx == -1:
                return "Not found"
            return text[idx:idx+window]

        return {
            "affected_aircraft": find_block("applicability"),
            "required_actions": find_block("compliance"),
            "compliance_times": find_block("compliance time")
        }

    except Exception as e:
        return {
            "affected_aircraft": f"Error extracting: {e}",
            "required_actions": "N/A",
            "compliance_times": "N/A"
        }

if ad_number:
    with st.spinner("🔍 Searching Federal Register..."):
        data = fetch_ad_data(ad_number)

    if data:
        st.success(f"✅ Found: {data['title']}")
        st.write(f"**Document Number:** {data['document_number']}")
        st.write(f"**Effective Date:** {data['effective_date']}")
        st.markdown(f"[🔗 View Full AD (HTML)]({data['html_url']})")
        st.markdown(f"[📄 View PDF]({data['pdf_url']})")

        st.markdown("---")
        st.subheader("📄 Key Extracted Details")

        ad_details = extract_details_from_html(data["html_url"])

        st.markdown(f"**✈️ Affected Aircraft / SB References:**\n```\n{ad_details['affected_aircraft']}\n```")
        st.markdown(f"**⚙️ Required Actions:**\n```\n{ad_details['required_actions']}\n```")
        st.markdown(f"**📅 Compliance Deadlines:**\n```\n{ad_details['compliance_times']}\n```")

    else:
        st.error("❌ AD not found. Please check the number exactly as it appears (e.g., 2020-06-14).")
