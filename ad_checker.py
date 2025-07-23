# ad_checker.py (AD Compliance Checker UI)

try:
    import streamlit as st
except ModuleNotFoundError:
    raise ImportError("Streamlit is not installed. Please install it using 'pip install streamlit' and try again.")

import requests
from bs4 import BeautifulSoup
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number_input = st.text_input("Enter AD Number (e.g., 2020-06-14):")

@st.cache_data(show_spinner=False)
def fetch_federalregister_ad(ad_number):
    try:
        # Break down AD number: 2020-06-14 -> year: 2020, sequence: 06-14
        ad_pattern = ad_number.replace("-", "")  # e.g. 20200614

        # Search federalregister.gov ADs
        search_url = f"https://www.federalregister.gov/documents/search?conditions%5Bterm%5D={ad_number}"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(search_url, headers=headers)
        soup = BeautifulSoup(resp.text, "html.parser")

        for link in soup.select("a[href*='/documents/']"):
            href = link.get("href")
            if href and ad_pattern in href.replace("-", ""):
                full_url = f"https://www.federalregister.gov{href}"
                ad_page = requests.get(full_url, headers=headers)
                return ad_page.text
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
    html = fetch_federalregister_ad(ad_number_input)
    if html:
        effective_date = extract_effective_date(html)
        st.success(f"✅ Effective Date: {effective_date}")
    else:
        st.warning("No AD found or unable to fetch.")
