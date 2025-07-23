# ad_checker.py (AD Compliance Checker UI)

import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number_input = st.text_input("Enter AD Number (e.g., 2020-06-14):")

@st.cache_data(show_spinner=False)
def fetch_ad_html(ad_number):
    try:
        query = f'site:federalregister.gov "Airworthiness Directive {ad_number}"'
        search_url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(search_url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            match = re.search(r"https://www\.federalregister\.gov/documents/\d{4}/\d{2}/\d{2}/[^"]+", href)
            if match:
                ad_url = match.group(0)
                page = requests.get(ad_url, headers=headers)
                return ad_url, page.text
    except Exception as e:
        st.error(f"Error fetching AD: {e}")
    return None, None

def extract_effective_date(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    match = re.search(r"(?i)(Effective Date\s*[:\-]\s*|This AD is effective )([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if match:
        return match.group(2)
    return "Not found"

if ad_number_input:
    ad_url, html = fetch_ad_html(ad_number_input)
    if html:
        effective_date = extract_effective_date(html)
        st.success(f"✅ Effective Date: {effective_date}")
        st.markdown(f"🔗 [View AD on Federal Register]({ad_url})")
    else:
        st.error("❌ AD not found. Please check the number and try again.")
