# ad_checker.py

import streamlit as st
import requests

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ Airworthiness Directive (AD) Compliance Checker")

# Prompt for AD Number
ad_number = st.text_input("Enter AD Number (e.g., 2020-06-14):").strip()

# Function to query the Federal Register API for AD info
def fetch_ad_info(ad_number):
    api_url = f"https://www.federalregister.gov/api/v1/documents.json?conditions[term]={ad_number}&per_page=5"
    try:
        response = requests.get(api_url, headers={"User-Agent": "AD-Checker/1.0"})
        response.raise_for_status()
        results = response.json().get("results", [])
        for item in results:
            if ad_number in item.get("document_number", ""):
                effective_date = item.get("effective_on", "Unknown")
                link = item.get("html_url", "#")
                return effective_date, link
        return None, None
    except Exception as e:
        return None, None

# UI Display
if ad_number:
    with st.spinner("🔍 Searching for AD..."):
        date, link = fetch_ad_info(ad_number)

    if date and link:
        st.success(f"✅ AD Found: Effective Date is **{date}**")
        st.markdown(f"[🔗 View Full AD on FederalRegister.gov]({link})")
    else:
        st.error("❌ AD not found. Please check the number and try again.")
