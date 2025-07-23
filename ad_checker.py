# ad_checker.py

import streamlit as st
import requests
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ Airworthiness Directive (AD) Compliance Checker")

ad_number = st.text_input("Enter AD Number (e.g., 2020-06-14):").strip()

def query_federal_register(ad_number):
    api_url = f"https://www.federalregister.gov/api/v1/documents.json?conditions[document_number]={ad_number}"
    try:
        response = requests.get(api_url, headers={"User-Agent": "AD-Checker"})
        if response.status_code != 200:
            return None, None
        data = response.json()
        if data["count"] == 0:
            return None, None
        entry = data["results"][0]
        return entry["effective_on"], entry["html_url"]
    except Exception as e:
        st.error(f"Error contacting Federal Register API: {e}")
        return None, None

if ad_number:
    with st.spinner("🔎 Searching Federal Register..."):
        effective_date, ad_link = query_federal_register(ad_number)

    if effective_date and ad_link:
        st.success(f"✅ Effective Date: {effective_date}")
        st.markdown(f"[📄 View Full AD]({ad_link})")
    else:
        st.error("❌ AD not found. Please check the number and try again.")
