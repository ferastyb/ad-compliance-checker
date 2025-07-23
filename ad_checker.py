# ad_checker.py

import streamlit as st
import requests
from urllib.parse import quote

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number = st.text_input("Enter AD Number (e.g., 2020-06-14):").strip()

def fetch_ad_data(ad_number: str):
    base_url = "https://www.federalregister.gov/api/v1/documents.json"
    params = {
        "conditions[term]": ad_number,
        "per_page": 10
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = requests.get(base_url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results", [])
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

if ad_number:
    with st.spinner("🔍 Searching Federal Register..."):
        data = fetch_ad_data(ad_number)

    if data:
        st.success(f"✅ Found AD {ad_number}")
        st.write(f"**Title:** {data['title']}")
        st.write(f"**Effective Date:** {data['effective_date']}")
        st.markdown(f"[🔗 View Full AD (HTML)]({data['html_url']})")
        st.markdown(f"[📄 View PDF]({data['pdf_url']})")
    else:
        st.error("❌ AD not found. Please check the number exactly as it appears.")
