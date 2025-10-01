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
ATA_FROM_SUBJECT_RE = re.compile(
    r"\b(?:JASC\/)?ATA(?:\s*chapter)?\s*[:\-]?\s*(\d{2})(?:[.\- ]?\d{2})?\b",
    re.IGNORECASE
)
def detect_ata_from_subject(full_text: str) -> str | None:
    subj = slice_letter_block(full_text, "d")
    if not subj:
        return None
    m = ATA_FROM_SUBJECT_RE.search(subj)
    if m:
        return m.group(1)
    return None

ATA_DIRECT_RE = re.compile(
    r"\b(?:ATA|ATA\s*chapter|chapter\s*(?:ATA)?)\s*[-:]?\s*(\d{2})(?:[.\- ]?(\d{2}))?\b",
    re.IGNORECASE
)
ATA_KEYWORD_HINTS = [
    (r"\bflight controls?\b", "27"),
    (r"\bfuel\b", "28"),
    (r"\bdoors?\b", "52"),
    (r"\bfuselage\b", "53"),
    (r"\bwings?\b", "57"),
    (r"\bnavigation\b", "34"),
    (r"\belectrical power\b", "24"),
    (r"\bequipment|furnishings\b", "25"),
    (r"\blanding gear\b", "32"),
    (r"\bair conditioning\b", "21"),
]
def detect_ata_fallback(full_text: str, sb_refs: list[str] | None = None) -> str | None:
    if not full_text:
        return None
    t = full_text.replace("\u00a0", " ")
    cands = [m.group(1) if not m.group(2) else f"{m.group(1)}-{m.group(2)}"
             for m in ATA_DIRECT_RE.finditer(t)]
    if cands:
        from collections import Counter
        return Counter(cands).most_common(1)[0][0]
    if sb_refs:
        for ref in sb_refs:
            m = re.search(r"-(\d{2})-", ref)
            if m:
                return m.group(1)
    tl = t.lower()
    for pat, code in ATA_KEYWORD_HINTS:
        if re.search(pat, tl):
            return code
    return None

# -----------------------------
# NEW: Summarizer for (g) and (h)
# -----------------------------
def summarize_g_h_sections(req_text: str | None, exc_text: str | None) -> tuple[list[str], list[str]]:
    bullets_g, bullets_h = [], []

    if req_text and req_text.strip().upper() != "N/A":
        if "RC" in req_text and "Service Bulletin" in req_text:
            bullets_g = [
                "Perform all actions labeled 'RC' (required for compliance) in the Accomplishment Instructions of the referenced Service Bulletin.",
                "Follow the compliance times specified in paragraph 5, 'Compliance,' of the Service Bulletin.",
                "Do the actions in accordance with the Service Bulletin instructions.",
                "These actions are required except where modified by paragraph (h) of this AD."
            ]
        else:
            bullets_g = [req_text.strip()]

    if exc_text and exc_text.strip().upper() != "N/A":
        if "effective date" in exc_text.lower() and "issue" in exc_text.lower():
            bullets_h = [
                "Where the Service Bulletin refers to 'the Issue date of this Service Bulletin,' substitute 'the effective date of this AD.'",
                "All other Service Bulletin instructions remain unchanged."
            ]
        else:
            bullets_h = [exc_text.strip()]

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
