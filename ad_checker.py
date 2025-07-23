# ad_checker.py (AD Compliance Checker UI)

import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number_input = st.text_input("Enter AD Number (e.g., 2020-06-14):")

@st.cache_data(show_spinner=False)
def get_ad_document_number(ad_number):
    """
    Searches the Federal Register API using the AD number (e.g., 2020-06-14) and retrieves the corresponding document number.
    """
    url = "https://www.federalregister.gov/api/v1/documents.json"
    params = {
        "per_page": 5,
        "order": "relevance",
        "conditions[term]": f"Airworthiness Directive {ad_number}"
    }
    try:
        resp = requests.get(url, params=params)
        data = resp.json()
        if data.get("results"):
            return data["results"][0]["document_number"]
    except Exception as e:
        st.error(f"Error retrieving AD document: {e}")
    return None

@st.cache_data(show_spinner=False)
def fetch_ad_html_by_document(document_number):
    try:
        url = f"https://www.federalregister.gov/documents/full_text/html/{document_number}"
        resp = requests.get(url)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        st.error(f"Error fetching AD HTML: {e}")
    return None

def extract_effective_date(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    match = re.search(r"(?i)(Effective Date\s*[:\-]\s*|This AD is effective )([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if match:
        return match.group(2)
    return "Not found"

if ad_number_input:
    document_number = get_ad_document_number(ad_number_input)
    if document_number:
        html = fetch_ad_html_by_document(document_number)
        if html:
            effective_date = extract_effective_date(html)
            st.success(f"✅ Effective Date: {effective_date}")
        else:
            st.error("❌ Failed to retrieve the full text of the AD.")
    else:
        st.error("❌ AD not found. Please check the number and try again.")
