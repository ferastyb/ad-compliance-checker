import streamlit as st
import requests
from bs4 import BeautifulSoup

st.set_page_config(page_title="AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

ad_input = st.text_input("Enter AD Number (e.g., 2020‑06‑14):").strip()

def fetch_ad_from_faa(ad_number):
    """Search FAA DRS and parse AD page for effective date."""
    search_url = f"https://drs.faa.gov/browse/ADFRAWD/doctypeDetails?docType=ADFRAWD&docName={ad_number}"
    resp = requests.get(search_url, timeout=10)
    if resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    # Look for key elements like “Issue Date” or “Effective”
    rows = soup.select("table tr")
    info = {}
    for tr in rows:
        cols = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(cols) == 2:
            k, v = cols
            info[k] = v

    if not info:
        return None

    title = soup.select_one("h2") and soup.select_one("h2").get_text(strip=True)
    effective = info.get("Issue Date") or info.get("Effective Date") or info.get("Effective On")
    pdf_link = soup.select_one("a[href*='.pdf']")
    pdf_url = requests.compat.urljoin(search_url, pdf_link["href"]) if pdf_link else None

    return {
        "title": title or "N/A",
        "effective_date": effective or "N/A",
        "html_url": search_url,
        "pdf_url": pdf_url,
        "info": info
    }

if ad_input:
    with st.spinner("🔍 Querying FAA AD database..."):
        data = fetch_ad_from_faa(ad_input)

    if data:
        st.success(f"✅ Found AD {ad_input}")
        st.write(f"**Title:** {data['title']}")
        st.write(f"**Effective Date:** {data['effective_date']}")
        st.markdown(f"[🔗 View AD in Browser]({data['html_url']})")
        if data["pdf_url"]:
            st.markdown(f"[📄 Download PDF]({data['pdf_url']})")
        else:
            st.info("PDF link not detected.")
    else:
        st.error("❌ AD not found or page structure changed.")

