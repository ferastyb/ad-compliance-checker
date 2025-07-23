# ad_checker.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number_input = st.text_input("Enter AD Number (e.g., 2020-06-14):")

def fetch_ad_link(ad_number):
    query = f"site:federalregister.gov {ad_number}"
    search_url = f"https://www.google.com/search?q={query}"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response = requests.get(search_url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            match = re.search(r"https://www\.federalregister\.gov/documents/\d+/.+?(?=&)", href)
            if match:
                return match.group(0)
    except Exception as e:
        st.error(f"Error during search: {e}")
    return None

def extract_effective_date(ad_url):
    try:
        response = requests.get(ad_url)
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(separator="\n")

        match = re.search(r"(Effective Date\s*[:\-]\s*|This AD is effective\s+)([A-Z][a-z]+ \d{1,2}, \d{4})", text)
        if match:
            return match.group(2)
    except Exception as e:
        st.error(f"Error reading AD: {e}")
    return "Not found"

if ad_number_input:
    with st.spinner("🔎 Searching for AD..."):
        ad_url = fetch_ad_link(ad_number_input.strip())

    if ad_url:
        effective_date = extract_effective_date(ad_url)
        st.success(f"✅ Effective Date: {effective_date}")
        st.markdown(f"[📄 View AD on Federal Register]({ad_url})")
    else:
        st.error("❌ AD not found. Please check the number and try again.")
