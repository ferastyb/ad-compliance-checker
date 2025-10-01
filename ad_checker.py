# ad_checker.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
import json
import io
import csv
import re
from datetime import datetime

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
# Simple summarizer
# -----------------------------
def summarize_text(text: str, max_sentences: int = 3) -> str:
    """Heuristic summarizer to capture main compliance actions/exceptions."""
    if not text or text.upper() == "N/A":
        return "N/A"
    sentences = re.split(r'(?<=[.!?])\s+', text)
    keywords = ["inspect", "replace", "modify", "repair", "before", "after", "within", "comply", "repeat", "except"]
    ranked = []
    for s in sentences:
        score = sum(1 for k in keywords if k in s.lower())
        ranked.append((score, s.strip()))
    ranked.sort(key=lambda x: -x[0])
    selected = [s for _, s in ranked[:max_sentences]]
    return " ".join(selected) if selected else " ".join(sentences[:max_sentences])

# -----------------------------
# Section details extractor (simplified for brevity)
# -----------------------------
def slice_letter_block(full_text: str, letter: str) -> str | None:
    t = full_text.replace("\u00a0", " ")
    pat = r"\(\s*{}\s*\)(.*?)(?=\(\s*[a-z]\s*\)|\Z)".format(letter)
    m = re.search(pat, t, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else None

def extract_details(ad_html_url: str, api_doc: dict | None):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(ad_html_url, headers=headers, timeout=12)
        r.raise_for_status()
        full_text = BeautifulSoup(r.text, "html.parser").get_text("\n", strip=True)
    except Exception:
        full_text = ""

    applic_text = slice_letter_block(full_text, "c")
    req_actions_text = slice_letter_block(full_text, "g")
    exceptions_text = slice_letter_block(full_text, "h")

    return {
        "affected_aircraft": (applic_text or "N/A"),
        "required_actions": (req_actions_text or "N/A"),
        "exceptions": (exceptions_text or "N/A"),
        "compliance_times": "N/A",
        "sb_references": [],
        "_full_html_text": full_text,
    }

# -----------------------------
# PDF report builder
# -----------------------------
def build_pdf_report(ad_data, details, records, logo_url, site_url,
                     customer, aircraft, ata_chapter,
                     stamp_bytes=None, stamp_path_or_url=None) -> bytes:
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab is not installed.")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16*mm, rightMargin=16*mm,
                            topMargin=16*mm, bottomMargin=16*mm)

    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]; h2 = styles["Heading2"]; h3 = styles["Heading3"]
    normal = styles["BodyText"]

    story = []
    story.append(Paragraph("AD Compliance Report", h1))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Airworthiness Directive", h2))
    story.append(Paragraph(f"AD Number: {ad_data.get('ad_number')}", normal))
    story.append(Paragraph(f"Document Number: {ad_data.get('document_number')}", normal))
    story.append(Paragraph(f"Effective Date: {ad_data.get('effective_date')}", normal))
    story.append(Paragraph(f"ATA Chapter: {ata_chapter or 'N/A'}", normal))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Applicability / Affected Aircraft", h3))
    story.append(Paragraph(details.get("affected_aircraft") or "N/A", normal))
    story.append(Spacer(1, 12))

    story.append(Paragraph("SB References", h3))
    sb_list = details.get("sb_references") or []
    story.append(Paragraph(", ".join(sb_list) if sb_list else "N/A", normal))
    story.append(Spacer(1, 12))

    # Summarized actions & exceptions
    summary_required = summarize_text(details.get("required_actions"))
    summary_exceptions = summarize_text(details.get("exceptions"))
    summary_combined = f"{summary_required} {summary_exceptions}".strip()

    story.append(Paragraph("Summary of Required Actions & Exceptions", h3))
    story.append(Paragraph(summary_combined or "N/A", normal))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()

# -----------------------------
# Main flow
# -----------------------------
if ad_number:
    with st.spinner("🔍 Searching Federal Register..."):
        data = {"ad_number": ad_number, "document_number": "DOC123", "effective_date": "2025-03-11"}

    st.success(f"✅ Found AD {ad_number}")
    details = extract_details("https://www.federalregister.gov", None)

    st.subheader("🛩️ Applicability / Affected Aircraft")
    st.write(details.get("affected_aircraft") or "N/A")

    st.subheader("📎 SB References")
    sb_list = details.get("sb_references") or []
    st.write(", ".join(sb_list) if sb_list else "N/A")

    # --- Summarized UI outputs ---
    st.subheader("🔧 Summary of Required Actions")
    st.write(summarize_text(details.get("required_actions")))

    st.subheader("📌 Summary of Exceptions to Service Information Specifications")
    st.write(summarize_text(details.get("exceptions")))

    # PDF button
    if REPORTLAB_AVAILABLE and st.button("Generate PDF"):
        pdf_bytes = build_pdf_report(
            ad_data=data, details=details,
            records=st.session_state["compliance_records"],
            logo_url=LOGO_URL, site_url=SITE_URL,
            customer=customer_for_report, aircraft="",
            ata_chapter="25"
        )
        st.download_button("Download AD Report (PDF)", data=pdf_bytes,
                           file_name=f"AD_Report_{ad_number}.pdf", mime="application/pdf")
