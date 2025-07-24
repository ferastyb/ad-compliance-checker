# ad_checker.py — FAA DRS-Based AD Compliance Checker

import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

st.set_page_config(page_title="AD Compliance Checker (DRS)", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_number = st.text_input("Enter AD Number (e.g., 2020-06-14):").strip()


def search_faa_drs(ad_number):
    """Search FAA DRS site for actual AD numbers."""
    base_url = "https://drs.faa.gov/search"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = requests.get(
            base_url,
            params={
                "query": ad_number,
                "doctype": "ADFRAWD",
            },
            headers=headers,
            timeout=10
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Look for link(s) that match the AD number
        ad_links = soup.find_all("a", href=True, string=re.compile(ad_number))
        for link in ad_links:
            href = link.get("href")
            if href and ad_number in link.text:
                return {
                    "title": link.text.strip(),
                    "url": f"https://drs.faa.gov{href}"
                }

    except Exception as e:
        st.error(f"Search failed: {e}")

    return None


if ad_number:
    with st.spinner("🔍 Searching FAA DRS for AD..."):
        result = search_faa_drs(ad_number)

    if result:
        st.success(f"✅ Found AD {ad_number}")
        st.write(f"**Title:** {result['title']}")
        st.markdown(f"[🔗 View Full AD on FAA DRS]({result['url']})")
    else:
        st.error("❌ AD not found. Please ensure it's a valid FAA AD number like 2020-06-14.")
