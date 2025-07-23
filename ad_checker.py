import streamlit as st
import requests

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number = st.text_input("Enter AD Number (e.g., 2020-06-14):").strip()

def fetch_ad_data(ad_number):
    base_url = "https://www.federalregister.gov/api/v1/documents.json"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(
            base_url,
            params={"conditions[term]": ad_number, "per_page": 20},
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        
        for doc in results:
            title = doc.get("title", "").lower()
            html_url = doc.get("html_url", "").lower()
            # Match AD number in title or URL
            if ad_number.lower() in title or ad_number.replace('-', '') in html_url:
                return {
                    "title": doc.get("title"),
                    "effective_date": doc.get("effective_on"),
                    "html_url": doc.get("html_url"),
                    "pdf_url": doc.get("pdf_url")
                }

    except requests.RequestException as e:
        st.error(f"Request failed: {e}")
    return None

if ad_number:
    with st.spinner("🔍 Searching Federal Register..."):
        data = fetch_ad_data(ad_number)

    if data:
        st.success(f"✅ Found AD {ad_number}")
        st.write(f"**Title:** {data['title']}")
        st.write(f"**Effective Date:** {data['effective_date'] or 'Not found'}")
        st.markdown(f"[🔗 View Full AD (HTML)]({data['html_url']})")
        st.markdown(f"[📄 View PDF]({data['pdf_url']})")
    else:
        st.error("❌ AD not found. Please check the number exactly as it appears (e.g., 2020-06-14).")
