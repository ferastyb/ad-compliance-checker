# ad_checker.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
import json
import io
import csv
import re
from datetime import datetime, date

# --- PDF (ReportLab) imports ---
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# -----------------------------
# Page setup + Branding (UI)
# -----------------------------
st.set_page_config(page_title="FAA AD Compliance Checker", layout="centered")

LOGO_URL = "https://www.ferasaviation.info/gallery/FA__logo.png?ts=1754692591"
SITE_URL = "https://www.ferasaviation.info"

# UI logo
st.image(LOGO_URL, width=180)
st.markdown(f"[🌐 www.ferasaviation.info]({SITE_URL})")

st.title("🛠️ AD Compliance Checker")

# Session state for compliance entries
if "compliance_records" not in st.session_state:
    st.session_state["compliance_records"] = []

# -----------------------------
# Inputs
# -----------------------------
ad_number = st.text_input("Enter AD Number (e.g., 2025-01-01):").strip()
customer_for_report = st.text_input("Customer (for report):").strip()
compliance_status_date = st.date_input("Compliance status as of:", date.today()).strftime("%Y-%m-%d")

# Optional stamp inputs (use either)
st.markdown("**PDF Stamp (optional)**")
stamp_file = st.file_uploader("Upload stamp image (PNG/JPG)", type=["png", "jpg", "jpeg"])
stamp_path_or_url = st.text_input("Or paste a stamp file path / URL (optional)").strip()

# -----------------------------
# Effective Date Utilities
# -----------------------------
EFFECTIVE_SENTENCE_RE = re.compile(
    r"(?:This\s*)?AD(?:\s+\d{4}-\d{2}-\d{2})?\s*(?:\([^)]*\))?\s*(?:is|becomes)\s*effective(?:\s+on)?\s*\(?\s*([A-Za-z]+ \d{1,2}, \d{4})\s*\)?",
    re.IGNORECASE | re.DOTALL
)
MONTH_DATE_RE = re.compile(r"\b([A-Za-z]+ \d{1,2}, \d{4})\b")

def _normalize_date(date_str: str) -> str | None:
    try:
        return datetime.strptime(date_str.strip(), "%B %d, %Y").date().isoformat()
    except Exception:
        return None

def extract_effective_date_from_text(text: str) -> str | None:
    if not text:
        return None
    t = text.replace("\u00a0", " ")
    m = EFFECTIVE_SENTENCE_RE.search(t)
    if m:
        norm = _normalize_date(m.group(1))
        if norm:
            return norm
    eff_idx = t.lower().find("effective")
    if eff_idx != -1:
        window = t[eff_idx:eff_idx + 240]
        m2 = MONTH_DATE_RE.search(window)
        if m2:
            norm = _normalize_date(m2.group(1))
            if norm:
                return norm
    return None

def to_ddmmyyyy(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.strftime("%d-%m-%Y")
    except Exception:
        pass
    try:
        dt = datetime.strptime(date_str.strip(), "%B %d, %Y")
        return dt.strftime("%d-%m-%Y")
    except Exception:
        return date_str

# -----------------------------
# Robust text slicers for (letter) sections
# -----------------------------
LETTER_BLOCK_RE_TEMPLATE = r"""
    \(\s*{letter}\s*\)       # (c), (d), (g), (h)...
    [^\n]*?                  # header line
    \n?                      # optional newline
    (                        # capture the body
        .*?
    )
    (?=                      # stop at next lettered section or end
        \n\(\s*[a-z]\s*\)\s*[^\n]*\n
        | \Z
    )
"""
def slice_letter_block(full_text: str, letter: str) -> str | None:
    if not full_text:
        return None
    t = full_text.replace("\u00a0", " ")
    t = re.sub(r"\r\n?", "\n", t)
    t = re.sub(r"(?<!\n)\(\s*([a-z])\s*\)", r"\n(\1)", t, flags=re.IGNORECASE)
    pat = LETTER_BLOCK_RE_TEMPLATE.format(letter=re.escape(letter))
    block_re = re.compile(pat, re.IGNORECASE | re.DOTALL | re.VERBOSE)
    m = block_re.search(t)
    if m:
        body = m.group(1).strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        return body if body else None
    return None

SB_CODE_RE = re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)*-SB[0-9A-Z]+(?:-[0-9A-Z]+)*\b", re.IGNORECASE)
def find_sb_refs(text: str) -> list[str]:
    if not text:
        return []
    refs = [m.group(0).upper() for m in SB_CODE_RE.finditer(text)]
    out, seen = [], set()
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out

# -----------------------------
# ATA Chapter detection
# -----------------------------
def detect_ata_from_sb(sb_refs: list[str] | None = None) -> str | None:
    """Detect ATA chapter by capturing the 2 digits after 'SB' in SB numbers"""
    if not sb_refs:
        return None
    for ref in sb_refs:
        m = re.search(r"SB(\d{2})", ref)
        if m:
            return m.group(1)
    return None

# -----------------------------
# Summarizer for (g) and (h)
# -----------------------------
def summarize_g_h_sections(req_text: str | None, exc_text: str | None) -> tuple[list[str], list[str]]:
    bullets_g, bullets_h = [], []

    # (g) Required Actions
    if req_text and req_text.strip().upper() != "N/A":
        sb_match = re.search(r"(B\d{3}-\d{5}-SB\d{6}-\d{2})", req_text)
        sb_ref = sb_match.group(1) if sb_match else "the referenced Service Bulletin"

        if "RC" in req_text and "Service Bulletin" in req_text:
            bullets_g = [
                f"Perform all actions labeled 'RC' (required for compliance) in the Accomplishment Instructions of {sb_ref}.",
                "Follow the timing in paragraph 5, 'Compliance,' of the same service bulletin.",
                "Do the actions in accordance with that SB’s procedures and specifications.",
                "Actions are required except where modified by paragraph (h) of this AD."
            ]
        else:
            sentences = re.split(r'(?<=[.])\s+', req_text.strip())
            bullets_g = [s.strip() for s in sentences if s.strip()]

    # (h) Exceptions
    if exc_text and exc_text.strip().upper() != "N/A":
        if "effective date" in exc_text.lower():
            bullets_h = [
                "Where the Service Bulletin refers to 'the Issue date of this Service Bulletin,' substitute 'the effective date of this AD.'",
                "All other Service Bulletin instructions remain unchanged."
            ]
        else:
            sentences = re.split(r'(?<=[.])\s+', exc_text.strip())
            bullets_h = [s.strip() for s in sentences if s.strip()]

    return bullets_g, bullets_h

# -----------------------------
# Data fetchers
# -----------------------------
def fetch_ad_data(ad_number: str):
    base_url = "https://www.federalregister.gov/api/v1/documents.json"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(
            base_url,
            params={"conditions[term]": f"Airworthiness Directive {ad_number}", "per_page": 25},
            headers=headers,
            timeout=12
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        for doc in results:
            title = (doc.get("title") or "")
            if ad_number in title or "airworthiness directive" in title.lower():
                return {
                    "title": title,
                    "effective_date": doc.get("effective_on"),
                    "html_url": doc.get("html_url"),
                    "pdf_url": doc.get("pdf_url"),
                    "document_number": doc.get("document_number"),
                    "publication_date": doc.get("publication_date"),
                }
    except requests.RequestException as e:
        st.error(f"❌ Request failed: {e}")
    return None

def fetch_document_json(document_number: str) -> dict | None:
    if not document_number:
        return None
    url = f"https://www.federalregister.gov/api/v1/documents/{document_number}.json"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

# -----------------------------
# Section details extractor
# -----------------------------
def extract_details(ad_html_url: str, api_doc: dict | None):
    headers = {"User-Agent": "Mozilla/5.0"}
    full_text = ""

    if api_doc and api_doc.get("body_html_url"):
        try:
            r = requests.get(api_doc["body_html_url"], headers=headers, timeout=12)
            r.raise_for_status()
            body_soup = BeautifulSoup(r.text, "html.parser")
            full_text = body_soup.get_text("\n", strip=True)
        except Exception:
            full_text = ""
    if not full_text:
        try:
            r = requests.get(ad_html_url, headers=headers, timeout=12)
            r.raise_for_status()
            page_soup = BeautifulSoup(r.text, "html.parser")
            full_text = page_soup.get_text("\n", strip=True)
        except Exception as e:
            return {
                "affected_aircraft": f"Error extracting: {e}",
                "required_actions": "N/A",
                "exceptions": "N/A",
                "sb_references": [],
                "_full_html_text": "",
            }

    applic_text = slice_letter_block(full_text, "c")
    req_actions_text = slice_letter_block(full_text, "g")
    exceptions_text = slice_letter_block(full_text, "h")

    sb_refs = find_sb_refs(req_actions_text) if req_actions_text else []
    if not sb_refs:
        sb_refs = find_sb_refs(full_text)

    return {
        "affected_aircraft": (applic_text or "N/A"),
        "required_actions": (req_actions_text or "N/A"),
        "exceptions": (exceptions_text or "N/A"),
        "sb_references": sb_refs,
        "_full_html_text": full_text,
    }

# -----------------------------
# PDF report builder
# -----------------------------
def build_pdf_report(
    ad_data: dict,
    details: dict,
    logo_url: str,
    site_url: str,
    customer: str,
    aircraft: str,
    ata_chapter: str | None,
    compliance_status_date: str | None,
    stamp_bytes: bytes | None = None,
    stamp_path_or_url: str | None = None
) -> bytes:
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab is not installed. Add 'reportlab' to your requirements.txt.")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16*mm,
        rightMargin=16*mm,
        topMargin=16*mm,
        bottomMargin=16*mm,
        title=f"AD Report - {ad_data.get('document_number') or 'Unknown'}",
        author="Feras Aviation AD Compliance Checker",
    )

    styles = getSampleStyleSheet()
    from reportlab.lib import colors
    h1 = styles["Heading1"]
    h3 = styles["Heading3"]
    normal = styles["BodyText"]

    story = []

    # Title
    story.append(Paragraph("AD Compliance Report", h1))
    story.append(Spacer(1, 12))

    # Metadata
    meta_data = [
        ["AD Number", ad_data.get("ad_number") or ""],
        ["Document Number", ad_data.get("document_number") or ""],
        ["AD Title", ad_data.get("title") or ""],
        ["Publication Date", ad_data.get("publication_date") or "N/A"],
        ["Effective Date", ad_data.get("effective_date") or "N/A"],
        ["ATA Chapter", ata_chapter or "N/A"],
        ["Customer", customer or ""],
        ["Aircraft", aircraft or ""],
    ]
    meta_table = Table(meta_data, colWidths=[40*mm, 120*mm], hAlign="LEFT")
    story.append(meta_table)
    story.append(Spacer(1, 12))

    # Summaries
    g_bullets, h_bullets = summarize_g_h_sections(details.get("required_actions"), details.get("exceptions"))

    story.append(Paragraph("Required Actions — key points", h3))
    if g_bullets:
        for i, b in enumerate(g_bullets, 1):
            story.append(Paragraph(f"{i}. {b}", normal))
    else:
        story.append(Paragraph("N/A", normal))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Exceptions — key points", h3))
    if h_bullets:
        for i, b in enumerate(h_bullets, 1):
            story.append(Paragraph(f"{i}. {b}", normal))
    else:
        story.append(Paragraph("N/A", normal))
    story.append(Spacer(1, 8))

    # Compliance status + certification
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Compliance status as of {compliance_status_date}", normal))
    story.append(Paragraph(
        "This compliance check was carried out with reference to the regulatory framework "
        "EASA Part-M / FAA 14 CFR Part 39.", normal
    ))

    # Stamp (optional)
    if stamp_bytes:
        story.append(PageBreak())
        story.append(Paragraph("Approval Stamp", h3))
        story.append(Spacer(1, 12))
        story.append(Image(io.BytesIO(stamp_bytes), width=60*mm, height=60*mm))
    elif stamp_path_or_url:
        try:
            resp = requests.get(stamp_path_or_url, timeout=10)
            if resp.ok:
                story.append(PageBreak())
                story.append(Paragraph("Approval Stamp", h3))
                story.append(Spacer(1, 12))
                story.append(Image(io.BytesIO(resp.content), width=60*mm, height=60*mm))
        except Exception:
            pass

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()

# -----------------------------
# Main flow
# -----------------------------
if ad_number:
    with st.spinner("🔍 Searching Federal Register..."):
        data = fetch_ad_data(ad_number)

    if data:
        data["ad_number"] = ad_number

        st.success(f"✅ Found: {data['title']}")
        st.write(f"**AD Number:** {ad_number}")
        st.write(f"**Document Number:** {data['document_number']}")
        st.write(f"**Publication Date:** {data.get('publication_date') or 'N/A'}")
        st.write(f"**Effective Date:** {to_ddmmyyyy(data.get('effective_date')) or 'N/A'}")

        st.markdown(f"[🔗 View Full AD (HTML)]({data['html_url']})")
        st.markdown(f"[📄 View PDF]({data['pdf_url']})")

        api_doc = fetch_document_json(data.get("document_number"))
        details = extract_details(data['html_url'], api_doc)

        ata_chapter = detect_ata_from_sb(details.get("sb_references"))

        # Show summaries
        g_bullets, h_bullets = summarize_g_h_sections(details.get("required_actions"), details.get("exceptions"))

        st.subheader("🔧 Required Actions — key points")
        for i, b in enumerate(g_bullets, 1):
            st.write(f"{i}. {b}")

        st.subheader("📌 Exceptions — key points")
        for i, b in enumerate(h_bullets, 1):
            st.write(f"{i}. {b}")

        # PDF Report Download
        st.divider()
        st.subheader("📄 Generate PDF Report")
        if REPORTLAB_AVAILABLE:
            if st.button("Generate PDF"):
                try:
                    aircraft_for_report = ""
                    if st.session_state["compliance_records"]:
                        aircraft_for_report = st.session_state["compliance_records"][-1].get("applic_serials", "") or ""

                    stamp_bytes_data = stamp_file.read() if stamp_file is not None else None

                    pdf_bytes = build_pdf_report(
                        ad_data=data,
                        details=details,
                        logo_url=LOGO_URL,
                        site_url=SITE_URL,
                        customer=customer_for_report,
                        aircraft=aircraft_for_report,
                        ata_chapter=ata_chapter,
                        compliance_status_date=compliance_status_date,
                        stamp_bytes=stamp_bytes_data,
                        stamp_path_or_url=stamp_path_or_url if stamp_bytes_data is None else None
                    )
                    st.download_button(
                        "Download AD Report (PDF)",
                        data=pdf_bytes,
                        file_name=f"AD_Report_{data.get('document_number','AD')}.pdf",
                        mime="application/pdf",
                    )
                except Exception as e:
                    st.error(f"Failed to create PDF: {e}")
        else:
            st.warning("PDF generation requires 'reportlab' and 'Pillow'.")
    else:
        st.error("❌ AD not found. Please check the number (e.g., 2025-01-01).")
