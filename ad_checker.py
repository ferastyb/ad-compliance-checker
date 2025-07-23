import streamlit as st
import requests
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number_input = st.text_input("Enter AD Number (e.g., 2020-06-14):")

@st.cache_data(show_spinner=False)
def fetch_ad_content(ad_number):
    try:
        # Search for the AD using the Federal Register API
        search_url = "https://www.federalregister.gov/api/v1/documents.json"
        params = {
            "per_page": 5,
            "order": "relevance",
            "conditions[term]": ad_number
        }
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        for doc in data.get("results", []):
            if ad_number in doc.get("document_number", "") or ad_number in doc.get("title", ""):
                return doc.get("body_html", ""), doc.get("html_url", "")
    except Exception as e:
        st.error(f"Error contacting federalregister.gov: {e}")
    return None, None

def extract_effective_date(html):
    if not html:
        return "Not found"
    
    text = re.sub(r"<[^>]+>", "", html)  # Strip HTML
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
