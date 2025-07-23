import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse, parse_qs

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number_input = st.text_input("Enter AD Number (e.g., 2020-06-14):")

@st.cache_data(show_spinner=False)
def fetch_ad_html(ad_number):
    search_url = f"https://www.google.com/search?q=site:federalregister.gov+{ad_number.replace(' ', '+')}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(search_url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Find redirect links like /url?q=https://www.federalregister.gov/...
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/url?q=https://www.federalregister.gov"):
                real_url = parse_qs(urlparse(href).query).get("q", [None])[0]
                if real_url:
                    ad_resp = requests.get(real_url, headers=headers, timeout=10)
                    if ad_resp.status_code == 200:
                        return ad_resp.text
    except Exception as e:
        st.error(f"🔧 Error fetching AD: {e}")
    return None

def extract_effective_date(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    match = re.search(r"(Effective Date\s*[:\-]\s*|This AD is effective\s+)([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if match:
        return match.group(2)
    return "Not found"

if ad_number_input:
    html = fetch_ad_html(ad_number_input)
    if html:
        effective_date = extract_effective_date(html)
        st.success(f"✅ Effective Date: {effective_date}")
    else:
        st.error("❌ AD not found. Please check the number and try again.")
