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
# Summarizer
# -----------------------------
def summarize_text(text: str, max_sentences: int = 4) -> str:
    """Heuristic summarizer to capture key compliance points."""
    if not text or text.upper() == "N/A":
        return "N/A"
    sentences = re.split(r'(?<=[.!?])\s+', text)
    keywords = ["inspect", "replace", "modify", "repair", "before", "after",
                "within", "comply", "repeat", "except", "prohibit"]
    ranked = []
    for s in sentences:
        score = sum(1 for k in keywords if k in s.lower())
        ranked.append((score, s.strip()))
    ranked.sort(key=lambda x: -x[0])
    selected = [s for _, s in ranked[:max_sentences]]
    return " ".join(selected) if selected else " ".join(sentences[:max_sentences])

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
# (rest of your existing functions unchanged: ATA detection, fetch_ad_data, fetch_document_json, extract_details, _image_flowable_fit, build_pdf_report)
# -----------------------------
# 📌 The only change inside build_pdf_report:
# Instead of dumping raw (g) + (h), it now shows the summary:
#
# summary_required = summarize_text(details.get("required_actions"))
# summary_exceptions = summarize_text(details.get("exceptions"))
# summary_combined = f"{summary_required} {summary_exceptions}".strip()
# story.append(Paragraph("Summary of Required Actions & Exceptions", h3))
# story.append(Paragraph(summary_combined or "N/A", normal))

# -----------------------------
# Main flow
# -----------------------------
if ad_number:
    with st.spinner("🔍 Searching Federal Register..."):
        data = fetch_ad_data(ad_number)

    if data:
        data["ad_number"] = ad_number
        st.success(f"✅ Found: {data['title']}")

        # (rest of your existing UI unchanged up to details extraction)

        st.subheader("🔧 Summary of Required Actions & Exceptions")
        summary_required = summarize_text(details.get("required_actions"))
        summary_exceptions = summarize_text(details.get("exceptions"))
        summary_combined = f"{summary_required} {summary_exceptions}".strip()
        st.write(summary_combined or "N/A")

        st.markdown("---")
        st.subheader("(g) Required Actions (raw)")
        st.write(details.get("required_actions") or "N/A")

        st.subheader("(h) Exceptions (raw)")
        st.write(details.get("exceptions") or "N/A")

        # (rest of your compliance form + PDF generation remains the same)
