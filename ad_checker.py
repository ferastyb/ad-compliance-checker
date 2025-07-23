# ad_checker.py (AD Compliance Checker UI)

try:
    import streamlit as st
except ModuleNotFoundError:
    import sys
    sys.exit("Streamlit is not installed. Please run this script in an environment where Streamlit is available.")

import requests
from bs4 import BeautifulSoup
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number_input = st.text_input("Enter AD Number (e.g., 2020-06-92):")

@st.cache_data(show_spinner=False)
def fetch_ad_html(ad_number):
    try:
        search_url = f"https://www.google.com/search?q=site%3Afederalregister.gov+{ad_number.replace(' ', '+')}"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(search_url, headers=headers)
        soup = BeautifulSoup(resp.text, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "https://www.federalregister.gov/documents/" in href:
                return requests.get(href).text
    except Exception as e:
        st.error(f"Error fetching AD: {e}")
    return None

def extract_effective_date(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    match = re.search(r"(?i)(Effective Date\s*[:\-]\s*|This AD is effective )([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if match:
        return match.group(2)
    return "Not found"

if ad_number_input:
    html = fetch_ad_html(ad_number_input)
    if html:
        effective_date = extract_effective_date(html)
        st.success(f"✅ Effective Date: {effective_date}")
    else:
        st.warning("No AD found or unable to fetch.")
