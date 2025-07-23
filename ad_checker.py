import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number_input = st.text_input("Enter AD Number (e.g., 2020-06-14):")

def search_federal_register(ad_number):
    """Search federalregister.gov API for the AD number"""
    base_url = "https://www.federalregister.gov/api/v1/documents.json"
    params = {"conditions[term]": ad_number, "per_page": 5}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(base_url, params=params, headers=headers)
        data = response.json()
        for result in data.get("results", []):
            if ad_number in result.get("document_number", ""):
                return result.get("html_url", "")
    except Exception as e:
        st.error(f"🔧 API error: {e}")
    return None

def extract_effective_date(url):
    """Scrape the effective date from the AD HTML page"""
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(separator="\n")

        match = re.search(r"(Effective Date\s*[:\-]\s*|This AD is effective )([A-Z][a-z]+ \d{1,2}, \d{4})", text)
        if match:
            return match.group(2)
    except Exception as e:
        st.error(f"Scraping error: {e}")
    return "Not found"

# Main logic
if ad_number_input:
    with st.spinner("Searching for AD..."):
        ad_url = search_federal_register(ad_number_input)
        if ad_url:
            effective_date = extract_effective_date(ad_url)
            st.success(f"✅ AD Found: [View Document]({ad_url})")
            st.info(f"📅 Effective Date: **{effective_date}**")
        else:
            st.error("❌ AD not found. Please check the number and try again.")
