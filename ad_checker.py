import streamlit as st
import requests
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number_input = st.text_input("Enter AD Number (e.g., 2020-06-14):")

@st.cache_data(show_spinner=False)
def fetch_ad_content(ad_number):
    try:
        url = f"https://www.federalregister.gov/api/v1/documents/{ad_number}.json"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get("body_html", ""), data.get("html_url", "")
        else:
            return None, None
    except Exception as e:
        st.error(f"Error contacting federalregister.gov: {e}")
        return None, None

def extract_effective_date(html):
    if not html:
        return "Not found"
    
    text = re.sub(r"<[^>]+>", "", html)  # Remove HTML tags
    match = re.search(r"(?i)(Effective Date\s*[:\-]?\s*|This AD is effective )([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if match:
        return match.group(2)
    return "Not found"

if ad_number_input:
    html, url = fetch_ad_content(ad_number_input)
    if html:
        effective_date = extract_effective_date(html)
        st.success(f"✅ Effective Date: {effective_date}")
        st.markdown(f"[🔗 View full AD on Federal Register]({url})")
    else:
        st.warning("❌ AD not found. Please check the number and try again.")
