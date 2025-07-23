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
def fetch_ad_html(ad_number):
    try:
        search_url = f"https://www.google.com/search?q=site%3Afederalregister.gov+{ad_number.replace(' ', '+')}"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(search_url, headers=headers)
        soup = BeautifulSoup(resp.text, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "https://www.federalregister.gov/documents/" in href:
                ad_url = href.split("&")[0].replace("/url?q=", "")
                ad_html = requests.get(ad_url, headers=headers).text
                return ad_url, ad_html
    except Exception as e:
        st.error(f"Error fetching AD: {e}")
    return None, None

def extract_effective_date(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    patterns = [
        r"Effective Date\s*[:\-]\s*([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"This AD is effective\s+([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"DATES\s*[:\-]?\s*This AD is effective\s+([A-Z][a-z]+ \d{1,2}, \d{4})"
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)

    return "Not found"

def extract_title(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    return h1.text.strip() if h1 else "Unknown"

if ad_number_input:
    ad_url, html = fetch_ad_html(ad_number_input)
    if html:
        title = extract_title(html)
        effective_date = extract_effective_date(html)

        st.success(f"✅ Found AD {ad_number_input}")
        st.markdown(f"**Title:** {title}")
        st.markdown(f"**Effective Date:** {effective_date}")

        st.markdown(f"\n🔗 [View Full AD (HTML)]({ad_url})")
        st.markdown(f"🗎 [View PDF]({ad_url.replace('/documents/', '/pdf/')})")
    else:
        st.error("❌ AD not found. Please check the number and try again.")
