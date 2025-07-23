# ad_checker.py

import streamlit as st
import requests
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ Airworthiness Directive (AD) Compliance Checker")

ad_number = st.text_input("Enter AD Number (e.g., 2020-06-14):").strip()

def fetch_federal_register_doc(ad_number):
    """
    Search for the AD using the Federal Register API.
    """
    base_url = "https://www.federalregister.gov/api/v1/documents.json"
    query = {
        "conditions[term]": ad_number,
        "per_page": 5,
        "order": "newest"
    }
    try:
        response = requests.get(base_url, params=query, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        docs = response.json().get("results", [])
        for doc in docs:
            if ad_number in doc.get("document_number", ""):
                return {
                    "effective_date": doc.get("effective_on"),
                    "html_url": doc.get("html_url"),
                    "title": doc.get("title"),
                    "pdf_url": doc.get("pdf_url")
                }
    except Exception as e:
        st.error(f"API error: {e}")
    return None

if ad_number:
    with st.spinner("🔍 Searching for AD..."):
        result = fetch_federal_register_doc(ad_number)

    if result:
        st.success(f"✅ Found AD {ad_number}")
        st.write(f"**Title:** {result['title']}")
        st.write(f"**Effective Date:** {result['effective_date']}")
        st.markdown(f"[🔗 View AD (HTML)]({result['html_url']})")
        st.markdown(f"[📄 View PDF]({result['pdf_url']})")
    else:
        st.error("❌ AD not found. Please check the number and try again.")
