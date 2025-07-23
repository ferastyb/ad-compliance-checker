# ad_checker.py (Standalone AD Compliance Checker)

import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number_input = st.text_input("Enter AD Number (e.g., 2020-06-14):")

def fetch_ad_url(ad_number):
    """
    Try fetching the federalregister.gov AD document link via Google Search.
    """
    query = f"site:federalregister.gov {ad_number}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(f"https://www.google.com/search?q={query}", headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "https://www.federalregister.gov/documents/" in href:
                # Google result URLs are usually like /url?q=real_url
                match = re.search(r"/url\?q=(https://www\.federalregister\.gov/documents/[^&]+)", href)
                if match:
                    return match.group(1)
    except Exception as e:
        st.error(f"🔧 Error while searching for AD: {e}")
    return None

def extract_effective_date_from_url(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(separator="\n")

        # Try finding "Effective Date" or "This AD is effective" phrases
        match = re.search(r"(?i)(Effective Date\s*[:\-]\s*|This AD is effective )([A-Z][a-z]+ \d{1,2}, \d{4})", text)
        if match:
            return match.group(2)
    except Exception as e:
        st.error(f"🔧 Failed to extract AD details: {e}")
    return None

if ad_number_input:
    with st.spinner("🔍 Searching for the AD..."):
        ad_url = fetch_ad_url(ad_number_input.strip())

    if ad_url:
        st.markdown(f"📄 [View AD on federalregister.gov]({ad_url})")

        with st.spinner("📑 Extracting effective date..."):
            date = extract_effective_date_from_url(ad_url)
            if date:
                st.success(f"✅ Effective Date: {date}")
            else:
                st.warning("⚠️ Effective date not found in the AD document.")
    else:
        st.error("❌ AD not found. Please check the number and try again.")
