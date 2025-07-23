# ad_checker.py (Standalone AD Compliance Checker)

import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number_input = st.text_input("Enter AD Number (e.g., 2020-06-14):")

def fetch_ad_from_federalregister(ad_number):
    try:
        # Build a likely URL for the AD document
        url = f"https://www.federalregister.gov/documents/{ad_number.replace('-', '/')}/"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return None, None

        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text("\n")

        # Extract title
        title_tag = soup.find("h1", class_="document-title")
        title = title_tag.get_text(strip=True) if title_tag else "No title found"

        # Extract effective date
        match = re.search(r"(?i)(Effective Date\s*[:\-]\s*|This AD is effective )(\w+ \d{1,2}, \d{4})", text)
        effective_date = match.group(2) if match else "Not found"

        return title, effective_date
    except Exception as e:
        st.error(f"Error: {e}")
        return None, None

if ad_number_input:
    with st.spinner("Searching for AD on federalregister.gov..."):
        title, effective_date = fetch_ad_from_federalregister(ad_number_input)

    if title:
        st.success(f"✅ Title: {title}")
        st.success(f"📅 Effective Date: {effective_date}")
    else:
        st.error("❌ AD not found. Please check the number and try again.")
