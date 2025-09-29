import streamlit as st
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import re
import json
import io
import csv
from datetime import datetime

st.set_page_config(page_title="FAA AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

# -----------------------------
# Utilities
# -----------------------------

def _requests_session():
    """Create a resilient requests session with retries and timeouts."""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (AD-Checker/1.0)"
    })
    return session

SESSION = _requests_session()
FR_API = "https://www.federalregister.gov/api/v1/documents.json"

# -----------------------------
# Search & Fetch
# -----------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ad_candidates(ad_number: str, extra_terms: list[str] | None = None, pages: int = 3, per_page: int = 50):
    """Return a list of candidate FR documents for this AD number using multiple query styles.

    We bias toward FAA final rules and ADs by agency/type filters where possible.
    """
    candidates = []
    terms = [
        f"\"Airworthiness Directive\" {ad_number}",
        f"Airworthiness Directive {ad_number}",
        f"{ad_number} Airworthiness Directive",
        f"{ad_number}",
    ]
    if extra_terms:
        terms.extend(extra_terms)

    seen_ids = set()

    for term in terms:
        for page in range(1, pages + 1):
            params = {
                "conditions[term]": term,
                "conditions[agencies][]": "federal-aviation-administration",
                # ADs are usually RULE documents; include both RULE and PROPOSED_RULE just in case
                "conditions[type][]": ["RULE", "PROPOSED_RULE"],
                "per_page": per_page,
                "page": page,
                # Sort by relevance then recency
                "order": "relevance",
            }
            try:
                r = SESSION.get(FR_API, params=params, timeout=10)
                r.raise_for_status()
                results = r.json().get("results", [])
            except requests.RequestException:
                results = []

            for doc in results:
                doc_id = doc.get("document_number") or doc.get("id")
                if not doc_id or doc_id in seen_ids:
                    continue
                seen_ids.add(doc_id)
                # Only keep documents that look like ADs
                title = (doc.get("title") or "").strip()
                if re.search(r"airworthiness directive", title, re.I) or re.search(r"AD\s*\d{4}-\d{2}-\d{2}", title, re.I) or ad_number in title:
                    candidates.append({
                        "title": title,
                        "effective_date": doc.get("effective_on"),
                        "html_url": doc.get("html_url"),
                        "pdf_url": doc.get("pdf_url"),
                        "document_number": doc.get("document_number"),
                        "publication_date": doc.get("publication_date"),
                        "type": doc.get("type"),
                        "agency_names": doc.get("agencies", []),
                    })

    # De-duplicate by html_url
    unique = {}
    for c in candidates:
        unique[c["html_url"]] = c

    # Sort: exact number in title first, then most recent effective date
    def _sort_key(c):
        exact = 0 if ad_number in (c["title"] or "") else 1
        eff = c.get("effective_date") or ""
        return (exact, "" if not eff else eff)

    return sorted(unique.values(), key=_sort_key)


def pick_best_candidate(candidates: list[dict], ad_number: str) -> dict | None:
    if not candidates:
        return None
    # Prefer exact match in title, otherwise first item (already sorted)
    for c in candidates:
        if ad_number in (c.get("title") or ""):
            return c
    return candidates[0]


# -----------------------------
# HTML Parsing
# -----------------------------

SECTION_HEADERS = [
    ("affected_aircraft", ["Applicability", "Affected Airplanes", "Affected Aircraft", "Applicability/Compliance"]),
    ("unsafe_condition", ["Unsafe Condition", "Reason", "Summary"]),
    ("required_actions", ["Compliance", "Actions and Compliance", "Requirements", "AD Requirements"]),
    ("compliance_times", ["Compliance Time", "Compliance", "Effective Date and Compliance", "When must I comply"])
]


def _collect_following_text(header_tag) -> str:
    content_lines = []
    for sib in header_tag.next_siblings:
        if getattr(sib, "name", None) and re.match(r"^h[1-6]$|^strong$", sib.name, re.I):
            break
        if hasattr(sib, "get_text"):
            text = sib.get_text("\n", strip=True)
            if text:
                content_lines.append(text)
        elif isinstance(sib, str):
            if sib.strip():
                content_lines.append(sib.strip())
    content = "\n".join(content_lines).strip()
    # Light cleanup: collapse multiple blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content


def _find_by_labels(soup: BeautifulSoup, labels: list[str]) -> str | None:
    # Search headings, <strong>, and elements with role=heading
    candidates = soup.find_all([re.compile(r"^h[1-6]$", re.I), "strong"]) + soup.select('[role="heading"]')
    for tag in candidates:
        txt = tag.get_text(strip=True)
        for label in labels:
            if re.search(rf"\b{re.escape(label)}\b", txt, re.I):
                content = _collect_following_text(tag)
                if content:
                    return content
    return None


def _regex_fallback(full_text: str, labels: list[str]) -> str | None:
    for label in labels:
        # Capture the paragraph after the label
        m = re.search(rf"{re.escape(label)}\s*:?\s*(.+?)(\n\s*\n|$)", full_text, re.I | re.S)
        if m:
            return m.group(1).strip()
    return None


@st.cache_data(ttl=1800, show_spinner=False)
def extract_details_from_html(html_url: str) -> dict:
    try:
        r = SESSION.get(html_url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        full_text = soup.get_text("\n", strip=True)

        details = {}
        for key, labels in SECTION_HEADERS:
            value = _find_by_labels(soup, labels)
            if not value:
                value = _regex_fallback(full_text, labels)
            details[key] = value or "Not found"

        # Effective date fallback: parse from page if API lacked it
        eff = _regex_fallback(full_text, ["Effective Date", "Effective date", "This AD is effective"])
        if eff:
            details["effective_date_text"] = eff
        return details
    except Exception as e:
        return {k: f"Error extracting: {e}" for k, _ in SECTION_HEADERS}


# -----------------------------
# UI
# -----------------------------

with st.sidebar:
    st.header("Search")
    mode = st.radio("Lookup mode", ["By AD number", "Keyword/Manufacturer"], horizontal=False)
    if mode == "By AD number":
        ad_number = st.text_input("Enter AD Number (e.g., 2020-06-14):").strip()
        extra = []
    else:
        ad_number = st.text_input("(Optional) AD Number filter:").strip()
        manufacturer = st.text_input("Manufacturer (e.g., Boeing, Airbus, Cessna):").strip()
        keyword = st.text_input("Keyword (e.g., fuel pump, ATA 28):").strip()
        extra = [manufacturer, keyword]
        extra = [t for t in extra if t]

# Main search action
if st.button("🔎 Search Federal Register", type="primary"):
    if not ad_number and mode == "By AD number":
        st.error("Please enter an AD number like 2020-06-14.")
        st.stop()

    with st.spinner("Contacting Federal Register API..."):
        candidates = fetch_ad_candidates(ad_number or "", extra_terms=extra)

    if not candidates:
        st.error("❌ No matching ADs found. Try broadening your search or check the number.")
        st.stop()

    # If multiple, let user choose
    options = [f"{c['title']} — (effective {c.get('effective_date') or 'N/A'})" for c in candidates]
    default_idx = 0
    for i, c in enumerate(candidates):
        if ad_number and ad_number in (c.get("title") or ""):
            default_idx = i
            break

    choice = st.selectbox("Select the AD:", options, index=default_idx)
    selected = candidates[options.index(choice)]

    st.success(f"✅ Found: {selected['title']}")
    st.write(f"**Document Number:** {selected.get('document_number')}")
    st.write(f"**Publication Date:** {selected.get('publication_date') or 'N/A'}")
    st.write(f"**Effective Date (API):** {selected.get('effective_date') or 'N/A'}")
    st.markdown(f"[🔗 View Full AD (HTML)]({selected['html_url']})")
    st.markdown(f"[📄 View PDF]({selected['pdf_url']})")

    with st.spinner("📄 Extracting AD details from HTML..."):
        details = extract_details_from_html(selected['html_url'])

    st.subheader("🛩️ Applicability / Affected Aircraft")
    st.write(details.get('affected_aircraft', ''))

    st.subheader("⚠️ Unsafe Condition")
    st.write(details.get('unsafe_condition', ''))

    st.subheader("🔧 Required Actions")
    st.write(details.get('required_actions', ''))

    st.subheader("📅 Compliance Deadlines")
    st.write(details.get('compliance_times', ''))

    # Data export
    st.divider()
    st.subheader("⬇️ Export")
    bundle = {
        "selected": selected,
        "extracted": details,
        "queried_at": datetime.utcnow().isoformat() + "Z",
    }

    json_bytes = json.dumps(bundle, indent=2).encode("utf-8")
    st.download_button("Download JSON", data=json_bytes, file_name=f"ad_{selected.get('document_number') or 'result'}.json", mime="application/json")

    # Minimal CSV export (flatten a few key fields)
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["document_number", "title", "effective_date_api", "html_url", "pdf_url", "applicability", "requirements", "compliance"])
    writer.writerow([
        selected.get("document_number", ""),
        selected.get("title", ""),
        selected.get("effective_date", ""),
        selected.get("html_url", ""),
        selected.get("pdf_url", ""),
        (details.get("affected_aircraft") or "").replace("\n", " "),
        (details.get("required_actions") or "").replace("\n", " "),
        (details.get("compliance_times") or "").replace("\n", " "),
    ])
    st.download_button("Download CSV", data=csv_buffer.getvalue().encode("utf-8"), file_name=f"ad_{selected.get('document_number') or 'result'}.csv", mime="text/csv")

else:
    # Initial help
    st.info("Enter an AD number like 2020-06-14 on the left, or switch to Keyword/Manufacturer to search more broadly. Then click ‘Search Federal Register’.")
