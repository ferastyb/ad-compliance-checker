# ad_checker.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
import json
import io
import csv
import re
from datetime import datetime
from typing import List, Dict, Tuple, Optional

# --- PDF (ReportLab) imports ---
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
    )
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# --- Batch/Merge imports ---
try:
    from PyPDF2 import PdfMerger
    PYPDF2_AVAILABLE = True
except Exception:
    PYPDF2_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:
    PANDAS_AVAILABLE = False


# -----------------------------
# Page setup + Branding (UI)
# -----------------------------
st.set_page_config(page_title="FAA AD Compliance Checker", layout="centered")

LOGO_URL = "https://www.ferasaviation.info/gallery/FA__logo.png?ts=1754692591"
SITE_URL = "https://www.ferasaviation.info"

# UI logo
st.image(LOGO_URL, width=180)
st.markdown(f"[www.ferasaviation.info]({SITE_URL})")

st.title("AD Compliance Checker")

# Session state for compliance entries
if "compliance_records" not in st.session_state:
    st.session_state["compliance_records"] = []

# -----------------------------
# Inputs (single AD)
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

def _normalize_date(date_str: str) -> Optional[str]:
    try:
        return datetime.strptime(date_str.strip(), "%B %d, %Y").date().isoformat()
    except Exception:
        return None

def extract_effective_date_from_text(text: str) -> Optional[str]:
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

def to_ddmmyyyy(date_str: Optional[str]) -> Optional[str]:
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

def slice_letter_block(full_text: str, letter: str) -> Optional[str]:
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

# SB code pattern & helpers
SB_CODE_RE = re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)*-SB[0-9A-Z]+(?:-[0-9A-Z]+)*\b", re.IGNORECASE)
def find_sb_refs(text: str) -> List[str]:
    if not text:
        return []
    refs = [m.group(0).upper() for m in SB_CODE_RE.finditer(text)]
    out, seen = [], set()
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out

def ata_from_sb_code(sb_code: str) -> Optional[str]:
    """
    Extract the two digits immediately after 'SB' in an SB code, e.g.:
    '...-SB420045-00' -> '42'
    """
    m = re.search(r"-SB(\d{2})", sb_code, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m2 = re.search(r"-SB(\d{2})\d+", sb_code, flags=re.IGNORECASE)
    if m2:
        return m2.group(1)
    return None


# -----------------------------
# ATA Chapter detection (Subject -> SB-based -> other heuristics)
# -----------------------------
ATA_FROM_SUBJECT_RE = re.compile(
    r"\b(?:JASC\/)?ATA(?:\s*chapter)?\s*[:\-]?\s*(\d{2})(?:[.\- ]?\d{2})?\b",
    re.IGNORECASE
)
def detect_ata_from_subject(full_text: str) -> Optional[str]:
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
def detect_ata_fallback(full_text: Optional[str], sb_refs: Optional[List[str]] = None) -> Optional[str]:
    # 1) Prefer SB-based ATA: first two digits after 'SB'
    if sb_refs:
        for ref in sb_refs:
            ata = ata_from_sb_code(ref)
            if ata:
                return ata
    # 2) Direct mentions like "ATA 25"
    if full_text:
        t = full_text.replace("\u00a0", " ")
        cands = [m.group(1) if not m.group(2) else f"{m.group(1)}-{m.group(2)}"
                 for m in ATA_DIRECT_RE.finditer(t)]
        if cands:
            from collections import Counter
            return Counter(cands).most_common(1)[0][0]
        # 3) Keyword hints
        tl = t.lower()
        for pat, code in ATA_KEYWORD_HINTS:
            if re.search(pat, tl):
                return code
    return None


# -----------------------------
# Targeted summarizer for (g) and (h)
# -----------------------------
def summarize_g_h_sections(req_text: Optional[str], exc_text: Optional[str]) -> Tuple[List[str], List[str]]:
    """
    Produce structured, numbered bullet points for (g) Required Actions and (h) Exceptions,
    tuned to FAA AD phrasing (e.g., AD 2020-06-14). Also echoes Issue number in (h) when present.
    """
    bullets_g, bullets_h = [], []

    # --------- (g) Required Actions ----------
    if req_text and req_text.strip().upper() != "N/A":
        t = req_text.strip()

        # Pull SB reference(s)
        sb_refs = find_sb_refs(t)
        sb_ref = sb_refs[0] if sb_refs else "the referenced Service Bulletin"

        # Pull Issue number and Service Bulletin date if present
        issue = None
        issue_date = None
        m_issue = re.search(r"\bIssue\s+([0-9A-Za-z]+)\b", t, flags=re.IGNORECASE)
        if m_issue:
            issue = m_issue.group(1)
        m_date = re.search(r"\bdated\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})\b", t, flags=re.IGNORECASE)
        if m_date:
            issue_date = m_date.group(1)

        # Build SB phrase
        sb_phrase = sb_ref
        if issue and issue_date:
            sb_phrase = f"{sb_ref}, Issue {issue} ({issue_date})"
        elif issue:
            sb_phrase = f"{sb_ref}, Issue {issue}"
        elif issue_date:
            sb_phrase = f"{sb_ref}, dated {issue_date}"

        # Detect RC, Compliance paragraph, and (h) exception mention
        has_rc = bool(re.search(r"\bRC\b", t))
        mentions_compliance_para_5 = bool(re.search(r"\bparagraph\s*5\b.*\bCompliance\b", t, flags=re.IGNORECASE))
        mentions_h_exception = bool(re.search(r"\bparagraph\s*\(?h\)?\b", t, flags=re.IGNORECASE)) or \
                               bool(re.search(r"\bexcept as specified\b", t, flags=re.IGNORECASE))

        # Construct bullets closely matching your example
        if has_rc:
            bullets_g.append(
                f"Perform all actions labeled 'RC' (required for compliance) in the Accomplishment Instructions of {sb_phrase}."
            )
        else:
            bullets_g.append(
                f"Accomplish the required actions in the Accomplishment Instructions of {sb_phrase}."
            )

        if mentions_compliance_para_5:
            bullets_g.append("Follow the timing in paragraph 5, 'Compliance,' of the same service bulletin.")
        else:
            bullets_g.append("Follow the compliance times specified in the service bulletin.")

        bullets_g.append("Do the actions in accordance with that SB’s procedures and specifications.")

        if mentions_h_exception:
            bullets_g.append("Actions are required except where modified by paragraph (h) of this AD.")

    # --------- (h) Exceptions ----------
    if exc_text and exc_text.strip().upper() != "N/A":
        t = exc_text.strip()

        # Detect specific "Issue X date" substitution and echo Issue number when found
        m_issue_mention = re.search(r"\bIssue\s+([0-9A-Za-z]+)\b", t, flags=re.IGNORECASE)
        issue_in_h = m_issue_mention.group(1) if m_issue_mention else None

        refers_issue_date = bool(re.search(r"\bIssue\b.*\bdate\b", t, flags=re.IGNORECASE))
        mentions_effective_date = bool(re.search(r"\beffective date\b", t, flags=re.IGNORECASE))
        mentions_sb_phrase = bool(re.search(r"\bservice bulletin\b", t, flags=re.IGNORECASE))

        if refers_issue_date and mentions_effective_date and mentions_sb_phrase:
            if issue_in_h:
                bullets_h.append(
                    f"Where the Service Bulletin refers to 'the Issue {issue_in_h} date of this Service Bulletin,' substitute 'the effective date of this AD.'"
                )
            else:
                bullets_h.append(
                    "Where the Service Bulletin refers to 'the Issue date of this Service Bulletin,' substitute 'the effective date of this AD.'"
                )
            bullets_h.append("All other Service Bulletin instructions remain unchanged.")
        else:
            # Generic exception paraphrase if not the date-substitution pattern
            sentences = re.split(r'(?<=[.!?])\s+', t)
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                bullets_h.append(s)
                if len(bullets_h) >= 6:
                    break

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

def fetch_document_json(document_number: str) -> Optional[Dict]:
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

def extract_effective_from_api_document(doc_json: Optional[Dict], html_fallback_text: Optional[str] = None) -> Optional[str]:
    if not doc_json:
        doc_json = {}

    dates_field = doc_json.get("dates")
    if isinstance(dates_field, str) and dates_field.strip():
        found = extract_effective_date_from_text(dates_field)
        if found:
            return found

    body_html_url = doc_json.get("body_html_url")
    if body_html_url:
        try:
            r = requests.get(body_html_url, timeout=12)
            r.raise_for_status()
            text = BeautifulSoup(r.text, "html.parser").get_text("\n", strip=True)
            found = extract_effective_date_from_text(text)
            if found:
                return found
        except Exception:
            pass

    candidates = []
    for key in ("abstract", "excerpts", "title"):
        val = doc_json.get(key)
        if isinstance(val, str) and val.strip():
            candidates.append(val)
        elif isinstance(val, list):
            candidates.extend([x for x in val if isinstance(x, str)])

    for c in candidates:
        text = BeautifulSoup(c, "html.parser").get_text(" ", strip=True)
        found = extract_effective_date_from_text(text)
        if found:
            return found

    if html_fallback_text:
        return extract_effective_date_from_text(html_fallback_text)

    return None


# -----------------------------
# Section details extractor
# -----------------------------
def extract_details(ad_html_url: str, api_doc: Optional[Dict]):
    headers = {"User-Agent": "Mozilla/5.0"}
    full_text = ""

    # 1) Try body_html_url first
    if api_doc and api_doc.get("body_html_url"):
        try:
            r = requests.get(api_doc["body_html_url"], headers=headers, timeout=12)
            r.raise_for_status()
            body_soup = BeautifulSoup(r.text, "html.parser")
            full_text = body_soup.get_text("\n", strip=True)
        except Exception:
            body_soup = None
    else:
        body_soup = None

    # 2) Fallback: public HTML page
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
                "compliance_times": "N/A",
                "sb_references": [],
                "_full_html_text": "",
            }

    # Slice key letter blocks
    applic_text = slice_letter_block(full_text, "c")
    req_actions_text = slice_letter_block(full_text, "g")
    exceptions_text = slice_letter_block(full_text, "h")

    # SB refs
    sb_refs = find_sb_refs(req_actions_text) if req_actions_text else []
    if not sb_refs:
        sb_refs = find_sb_refs(full_text)

    # Compliance Time
    compliance_text = None
    m = re.search(
        r"\(\s*[a-z]\s*\)\s*[^\n]*\bCompliance\b[^\n]*\n(.*?)(?=\n\(\s*[a-z]\s*\)\s*[^\n]*\n|\Z)",
        full_text, flags=re.IGNORECASE | re.DOTALL
    )
    if m:
        compliance_text = m.group(1).strip()
    if not compliance_text:
        m2 = re.search(r"\bCompliance\b[:.]?\s*(.+?)(?=\n{2,}|\Z)", full_text, flags=re.IGNORECASE | re.DOTALL)
        if m2:
            compliance_text = m2.group(1).strip()

    return {
        "affected_aircraft": (applic_text or "N/A"),
        "required_actions": (req_actions_text or "N/A"),
        "exceptions": (exceptions_text or "N/A"),
        "compliance_times": (compliance_text or "N/A"),
        "sb_references": sb_refs,
        "_full_html_text": full_text,
    }


# -----------------------------
# Image helpers (logo/stamp)
# -----------------------------
def _image_flowable_fit(source_bytes: Optional[bytes] = None, path_or_url: Optional[str] = None,
                        max_w_mm: float = 60, max_h_mm: float = 60):
    """Return a ReportLab Image flowable scaled proportionally to fit within max box (aspect ratio preserved)."""
    try:
        from PIL import Image as PILImage
        if source_bytes:
            pil = PILImage.open(io.BytesIO(source_bytes))
        else:
            if path_or_url is None:
                return None
            if path_or_url.lower().startswith(("http://", "https://")):
                resp = requests.get(path_or_url, timeout=10)
                resp.raise_for_status()
                pil = PILImage.open(io.BytesIO(resp.content))
            else:
                pil = PILImage.open(path_or_url)
        pil = pil.convert("RGBA")
        w, h = pil.size
        max_w_px = int(max_w_mm * 72 / 25.4)
        max_h_px = int(max_h_mm * 72 / 25.4)
        scale = min(max_w_px / w, max_h_px / h, 1.0)
        new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
        pil = pil.resize((new_w, new_h))
        bio = io.BytesIO()
        pil.save(bio, format="PNG")
        bio.seek(0)
        return Image(bio, width=new_w, height=new_h)
    except Exception:
        return None


# -----------------------------
# Watermark helper
# -----------------------------
def _watermark_callbacks_or_none(watermark_text: Optional[str]):
    """Return (on_first_page, on_later_pages) callbacks for doc.build if watermark_text provided."""
    if not watermark_text:
        return None, None

    def _draw_watermark(canv, doc):
        try:
            width, height = doc.pagesize
        except Exception:
            width, height = A4  # fallback

        canv.saveState()
        # Soft gray, big, centered diagonal
        try:
            canv.setFillAlpha(0.15)  # transparency if supported
        except Exception:
            pass
        canv.setFont("Helvetica-Bold", 80)
        canv.setFillColorRGB(0.85, 0.85, 0.85)
        canv.translate(width / 2.0, height / 2.0)
        canv.rotate(45)
        canv.drawCentredString(0, 0, watermark_text)
        canv.restoreState()

    return _draw_watermark, _draw_watermark


# -----------------------------
# PDF report builder (single AD)
# -----------------------------
def build_pdf_report(
    ad_data: Dict,
    details: Dict,
    records: List[Dict],
    logo_url: str,
    site_url: str,
    customer: str,
    aircraft: str,
    ata_chapter: Optional[str],
    stamp_bytes: Optional[bytes] = None,
    stamp_path_or_url: Optional[str] = None,
    watermark_text: Optional[str] = None
) -> bytes:
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab is not installed. Add 'reportlab' to your requirements.txt.")

    # Prepare grayscale 30% logo for the report header (keeps AR via helper below if fallback)
    logo_flowable = None
    try:
        from PIL import Image as PILImage
        resp = requests.get(logo_url, timeout=10)
        resp.raise_for_status()
        pil_img = PILImage.open(io.BytesIO(resp.content)).convert("L")
        w, h = pil_img.size
        pil_img = pil_img.resize((max(1, int(w * 0.3)), max(1, int(h * 0.3))), PILImage.LANCZOS)
        logo_buf = io.BytesIO()
        pil_img.save(logo_buf, format="PNG")
        logo_buf.seek(0)
        logo_flowable = Image(logo_buf)
    except Exception:
        # Fallback: proportional fit (preserves aspect ratio)
        logo_flowable = _image_flowable_fit(path_or_url=logo_url, max_w_mm=40, max_h_mm=20)

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
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    h3 = styles["Heading3"]
    normal = styles["BodyText"]
    small = ParagraphStyle("small", parent=normal, fontSize=9, leading=12, textColor=colors.grey)
    brand_center_small = ParagraphStyle(
        "brand_center_small", parent=normal, alignment=1, fontSize=12, textColor=colors.black
    )

    story = []

    if logo_flowable:
        story.append(logo_flowable)
        # Centered, smaller brand line (as requested)
        story.append(Paragraph("Feras Aviation Technical Services Ltd.", brand_center_small))
    story.append(Paragraph(f'<font size="12"><a href="{site_url}">{site_url}</a></font>', small))
    story.append(Spacer(1, 6))

    story.append(Paragraph("AD Compliance Report", h1))
    story.append(Spacer(1, 6))
    generated_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(f"Generated: {generated_ts}", small))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Airworthiness Directive", h2))
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
    meta_table.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.5, colors.grey),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BACKGROUND", (0,0), (0,-1), colors.whitesmoke),
        ("LEFTPADDING", (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Extracted Details", h2))

    story.append(Paragraph("Applicability / Affected Aircraft", h3))
    text = (details.get("affected_aircraft") or "").replace("\n", "<br/>") or "N/A"
    story.append(Paragraph(text, normal))
    story.append(Spacer(1, 8))

    story.append(Paragraph("SB References (from Required Actions)", h3))
    sb_list = details.get("sb_references") or []
    story.append(Paragraph(", ".join(sb_list) if sb_list else "N/A", normal))
    story.append(Spacer(1, 8))

    # --- Summaries for (g) and (h) (numbered) ---
    story.append(Paragraph("Action Items (Summarized)", h3))

    bullets_g, bullets_h = summarize_g_h_sections(
        details.get("required_actions"),
        details.get("exceptions")
    )

    if bullets_g:
        for i, b in enumerate(bullets_g, 1):
            story.append(Paragraph(f"{i}. {b}", normal))
    else:
        story.append(Paragraph("Required Actions: N/A", normal))

    story.append(Spacer(1, 6))

    if bullets_h:
        for i, b in enumerate(bullets_h, 1):
            story.append(Paragraph(f"{i}. {b}", normal))
    else:
        story.append(Paragraph("Exceptions: N/A", normal))

    story.append(Spacer(1, 10))

    # Required Actions + Exceptions (raw text, unchanged)
    story.append(Paragraph("Required Actions", h3))
    ra_text = (details.get("required_actions") or "").strip()
    ex_text = (details.get("exceptions") or "").strip()
    parts = []
    if ra_text and ra_text.upper() != "N/A":
        parts.append(f"<b>(g) Required Actions</b><br/>{ra_text.replace('\n','<br/>')}")
    if ex_text and ex_text.upper() != "N/A":
        parts.append(f"<br/><b>(h) Exceptions to Service Information Specifications</b><br/>{ex_text.replace('\n','<br/>')}")
    combined = "<br/><br/>".join(parts) if parts else "N/A"
    story.append(Paragraph(combined, normal))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Compliance Deadlines", h3))
    ct_text = (details.get("compliance_times") or "").replace("\n", "<br/>") or "N/A"
    story.append(Paragraph(ct_text, normal))
    story.append(Spacer(1, 8))

    # ------------------- Responsive Compliance Records Table -------------------
    story.append(Paragraph("Compliance Records", h2))
    records_list = records or []
    if not records_list:
        story.append(Paragraph("No compliance records added.", normal))
    else:
        header = [
            "Status", "Method", "Details",
            "Applicability (Aircraft/Component)", "Serials",
            "Date", "Hours", "Cycles", "Repetitive", "Interval", "Basis", "Next Due"
        ]

        from xml.sax.saxutils import escape as xml_escape
        def P(text):
            return Paragraph(xml_escape(str(text)) if text is not None else "", small)

        rows = [[Paragraph(label, ParagraphStyle("th", parent=small, fontName="Helvetica-Bold")) for label in header]]

        for rec in records_list:
            next_due = rec.get("next_due") or {}
            if isinstance(next_due, dict):
                nd_parts = []
                if next_due.get("hours") is not None:  nd_parts.append(f"H:{next_due['hours']}")
                if next_due.get("cycles") is not None: nd_parts.append(f"C:{next_due['cycles']}")
                if next_due.get("calendar"):            nd_parts.append(next_due["calendar"])
                nd_text = ", ".join(nd_parts)
            else:
                nd_text = str(next_due)

            rows.append([
                P(rec.get("status", "")),
                P("; ".join(rec.get("method", []) or [])),
                P(rec.get("method_other", "")),
                P(rec.get("applic_aircraft", "")),
                P(rec.get("applic_serials", "")),
                P(rec.get("performed_date", "")),
                P(rec.get("performed_hours", "")),
                P(rec.get("performed_cycles", "")),
                P("Yes" if rec.get("repetitive") else "No"),
                P((f"{rec.get('rep_interval_value','')} {rec.get('rep_interval_unit','')}".strip()
                   if rec.get("repetitive") else "")),
                P((rec.get('rep_basis','') if rec.get('repetitive') else "")),
                P(nd_text),
            ])

        weights = [8, 12, 14, 14, 12, 8, 6, 6, 8, 10, 10, 12]
        total = sum(weights)
        avail = doc.width
        col_widths = [avail * w / total for w in weights]

        table = Table(rows, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",  (0,0), (-1,-1), 9),
            ("VALIGN",    (0,0), (-1,-1), "TOP"),
            ("LINEABOVE", (0,0), (-1,0),  0.5, colors.grey),
            ("LINEBELOW", (0,0), (-1,-1), 0.25, colors.grey),
            ("BOX",       (0,0), (-1,-1), 0.5, colors.grey),
            ("INNERGRID", (0,0), (-1,-1), 0.25, colors.grey),
        ]))
        story.append(table)

    # Footer note
    story.append(Spacer(1, 18))
    story.append(Paragraph("Generated by Feras Aviation AD Compliance Checker", small))

    # ---- Stamp on its own page & scaled to fit ----
    stamp_flowable = _image_flowable_fit(
        source_bytes=stamp_bytes,
        path_or_url=stamp_path_or_url if stamp_bytes is None else None,
        max_w_mm=60,
        max_h_mm=60
    )
    if stamp_flowable:
        story.append(PageBreak())
        story.append(Spacer(1, 12))
        story.append(Paragraph("Approval Stamp", h2))
        story.append(Spacer(1, 12))
        story.append(stamp_flowable)

    # Watermark callbacks
    on_first, on_later = _watermark_callbacks_or_none(watermark_text)

    if on_first and on_later:
        doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    else:
        doc.build(story)

    buf.seek(0)
    return buf.getvalue()


# -----------------------------
# Batch Tally PDF (with stamp & proper logo AR)
# -----------------------------
def build_tally_pdf(
    rows: List[Dict],
    logo_url: str,
    site_url: str,
    stamp_bytes: Optional[bytes] = None,
    stamp_path_or_url: Optional[str] = None,
    watermark_text: Optional[str] = None
) -> bytes:
    """
    rows: list of dicts with keys:
      'ad_number', 'document_number', 'title', 'publication_date', 'effective_date', 'ata'
    """
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
        title="Batch AD Tally",
        author="Feras Aviation Technical Services Ltd. AD Compliance Checker",
    )

    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    normal = styles["BodyText"]
    small = ParagraphStyle("small", parent=normal, fontSize=9, leading=12, textColor=colors.grey)

    story = []

    # Logo (preserve aspect ratio on tally sheet!)
    logo_flowable = _image_flowable_fit(path_or_url=logo_url, max_w_mm=40, max_h_mm=20)
    if logo_flowable:
        story.append(logo_flowable)
    story.append(Paragraph(f'<font size="12"><a href="{site_url}">{site_url}</a></font>', small))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Batch AD Tally", h1))
    generated_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(f"Generated: {generated_ts}", small))
    story.append(Spacer(1, 12))

    # Table header
    header = ["AD Number", "Document Number", "ATA", "Effective Date", "Title"]
    data = [[Paragraph(h, ParagraphStyle("th", parent=small, fontName="Helvetica-Bold")) for h in header]]

    for r in rows:
        eff = r.get("effective_date") or "N/A"
        row_list = [
            Paragraph(r.get("ad_number",""), small),
            Paragraph(r.get("document_number",""), small),
            Paragraph(r.get("ata","") or "N/A", small),
            Paragraph(eff, small),
            Paragraph(r.get("title","") or "N/A", small)
        ]
        data.append(row_list)

    # adaptive column widths
    avail_width = doc.width
    weights = [16, 28, 10, 18, 48]  # relative weights
    total_w = sum(weights)
    col_widths = [avail_width * w / total_w for w in weights]

    table = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",  (0,0), (-1,-1), 9),
        ("VALIGN",    (0,0), (-1,-1), "TOP"),
        ("LINEABOVE", (0,0), (-1,0),  0.5, colors.grey),
        ("LINEBELOW", (0,0), (-1,-1), 0.25, colors.grey),
        ("BOX",       (0,0), (-1,-1), 0.5, colors.grey),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.grey),
    ]))
    story.append(table)

    story.append(Spacer(1, 18))
    story.append(Paragraph("Generated by Feras Aviation Technical Services Ltd. AD Compliance Checker tool", small))

    # Stamp at the end of tally sheet (batch-mode-only stamp)
    stamp_flowable = _image_flowable_fit(
        source_bytes=stamp_bytes,
        path_or_url=stamp_path_or_url if stamp_bytes is None else None,
        max_w_mm=60,
        max_h_mm=60
    )
    if stamp_flowable:
        story.append(Spacer(1, 12))
        story.append(Paragraph("Approval Stamp", styles["Heading3"]))
        story.append(Spacer(1, 8))
        story.append(stamp_flowable)

    # Optional watermark on tally as well (follows same toggle)
    on_first, on_later = _watermark_callbacks_or_none(watermark_text)
    if on_first and on_later:
        doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    else:
        doc.build(story)

    buf.seek(0)
    return buf.getvalue()


# -----------------------------
# Helpers: build records from "Records" sheet rows (Option B)
# -----------------------------
def _coerce_int(val) -> Optional[int]:
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    try:
        return int(val)
    except Exception:
        try:
            return int(float(val))
        except Exception:
            return None

def _coerce_str(val) -> str:
    try:
        if pd.isna(val):
            return ""
    except Exception:
        pass
    return str(val)

def _coerce_bool_from_yn(val) -> bool:
    s = _coerce_str(val).strip().lower()
    return s in {"y", "yes", "true", "1"}

def _parse_methods(val) -> List[str]:
    s = _coerce_str(val)
    if not s:
        return []
    parts = [p.strip() for p in re.split(r"[;,/]", s) if p.strip()]
    return parts

def build_records_for_ad(ad_no: str, df_records: pd.DataFrame) -> List[Dict]:
    """
    Expect df_records columns (case-insensitive accepted):
    AD Number, Status, Method, Method Other, Applic Aircraft, Serials,
    Performed Date, Performed Hours, Performed Cycles,
    Repetitive, Interval Value, Interval Unit, Basis
    """
    if df_records is None or df_records.empty:
        return []

    # Normalize columns
    colmap = {}
    for c in df_records.columns:
        lc = str(c).strip().lower()
        colmap[lc] = c

    records = []
    for _, row in df_records.iterrows():
        row_ad = _coerce_str(row.get(colmap.get("ad number", "AD Number"), ""))
        if row_ad.strip() != ad_no:
            continue

        status         = _coerce_str(row.get(colmap.get("status", "Status"), ""))
        method         = _parse_methods(row.get(colmap.get("method", "Method"), ""))
        method_other   = _coerce_str(row.get(colmap.get("method other", "Method Other"), ""))
        applic_air     = _coerce_str(row.get(colmap.get("applic aircraft", "Applic Aircraft"), ""))
        serials        = _coerce_str(row.get(colmap.get("serials", "Serials"), ""))
        date_val       = _coerce_str(row.get(colmap.get("performed date", "Performed Date"), ""))
        hours_val      = _coerce_int(row.get(colmap.get("performed hours", "Performed Hours")))
        cycles_val     = _coerce_int(row.get(colmap.get("performed cycles", "Performed Cycles")))
        repetitive     = _coerce_bool_from_yn(row.get(colmap.get("repetitive", "Repetitive")))
        interval_value = _coerce_int(row.get(colmap.get("interval value", "Interval Value")))
        interval_unit  = _coerce_str(row.get(colmap.get("interval unit", "Interval Unit")))
        basis          = _coerce_str(row.get(colmap.get("basis", "Basis")))

        rec = {
            "ad_number": ad_no,
            "document_number": None,
            "status": status,
            "method": method,
            "method_other": method_other,
            "applic_aircraft": applic_air,
            "applic_serials": serials,
            "performed_date": date_val or None,
            "performed_hours": hours_val,
            "performed_cycles": cycles_val,
            "repetitive": repetitive,
            "rep_interval_value": interval_value if repetitive else None,
            "rep_interval_unit": interval_unit if repetitive else None,
            "rep_basis": basis if repetitive else None,
            "next_due": None,
        }

        # Compute next_due similar to UI logic
        next_due = {}
        if repetitive:
            if interval_unit.lower() == "hours" and hours_val is not None and interval_value is not None:
                next_due["hours"] = hours_val + interval_value
            if interval_unit.lower() == "cycles" and cycles_val is not None and interval_value is not None:
                next_due["cycles"] = cycles_val + interval_value
            if interval_unit.lower() in {"days", "months", "years"} and interval_value is not None:
                next_due["calendar"] = f"+{interval_value} {interval_unit} ({basis})"
        rec["next_due"] = next_due or None

        records.append(rec)

    return records


# -----------------------------
# Main flow (single AD)
# -----------------------------
if ad_number:
    with st.spinner("🔍 Searching Federal Register..."):
        data = fetch_ad_data(ad_number)

    if data:
        data["ad_number"] = ad_number
        st.success(f"✅ Found: {data['title']}")
        col_left, col_right = st.columns([3, 1])
        with col_left:
            st.write(f"**AD Number:** {ad_number}")
            st.write(f"**Document Number:** {data['document_number']}")
            st.write(f"**Publication Date:** {data.get('publication_date') or 'N/A'}")
            st.write(f"**Effective Date (API field):** {to_ddmmyyyy(data.get('effective_date')) or 'N/A'}")
        with col_right:
            st.markdown("<div style='text-align:right;font-weight:600;'>ATA Chapter</div>", unsafe_allow_html=True)
            ata_input_placeholder = st.empty()

        st.markdown(f"[🔗 View Full AD (HTML)]({data['html_url']})")
        st.markdown(f"[📄 View PDF]({data['pdf_url']})")

        api_doc = fetch_document_json(data.get("document_number"))

        with st.spinner("📄 Extracting AD details..."):
            details = extract_details(data['html_url'], api_doc)

        # Determine ATA: subject -> SB-based -> heuristics
        detected_ata = detect_ata_from_subject(details.get("_full_html_text",""))
        if not detected_ata:
            detected_ata = detect_ata_fallback(details.get("_full_html_text",""), details.get("sb_references"))

        with col_right:
            ata_chapter = ata_input_placeholder.text_input(
                label="ATA Chapter (editable)",
                value=detected_ata or "",
                key="ata_chapter_input"
            )

        api_eff_field_iso = (data.get("effective_date") or "").strip()
        effective_resolved_iso = api_eff_field_iso if api_eff_field_iso and api_eff_field_iso.upper() != "N/A" else None
        if not effective_resolved_iso:
            effective_resolved_iso = extract_effective_from_api_document(
                api_doc,
                html_fallback_text=details.get("_full_html_text", "")
            )
        eff_display = to_ddmmyyyy(effective_resolved_iso) or to_ddmmyyyy(api_eff_field_iso)

        st.subheader("📅 Effective Date")
        st.write(eff_display or "N/A")
        if eff_display:
            data["effective_date"] = eff_display

        st.subheading = st.subheader  # alias to avoid accidental mistakes later

        st.subheader("🛩️ Applicability / Affected Aircraft")
        st.write(details.get("affected_aircraft") or "N/A")

        st.subheader("📎 SB References (from Required Actions)")
        sb_list = details.get("sb_references") or []
        st.write(", ".join(sb_list) if sb_list else "N/A")

        # --- (g) and (h) structured, NUMBERED summaries in UI ---
        st.subheader("🔧 (g) Required Actions — key points")
        bullets_g, bullets_h = summarize_g_h_sections(
            details.get("required_actions"),
            details.get("exceptions")
        )
        if bullets_g:
            st.markdown("\n".join([f"{i+1}. {b}" for i, b in enumerate(bullets_g)]))
        else:
            st.write("N/A")

        st.subheader("📌 (h) Exception to Service Information Specifications — key points")
        if bullets_h:
            st.markdown("\n".join([f"{i+1}. {b}" for i, b in enumerate(bullets_h)]))
        else:
            st.write("N/A")

        st.markdown("---")
        # Existing raw sections (unchanged)
        st.subheader("🔧 Required Actions (raw section)")
        st.write(details.get("required_actions") or "N/A")

        st.subheader("📌 Exceptions to Service Information Specifications")
        st.write(details.get("exceptions") or "N/A")

        st.subheader("📅 Compliance Deadlines")
        st.write(details.get("compliance_times") or "N/A")

        # ==============================
        # Compliance Recording Section
        # ==============================
        st.divider()
        st.subheader("✅ Compliance Status for this AD")

        with st.form("compliance_form"):
            col1, col2 = st.columns(2)
            with col1:
                status = st.selectbox(
                    "Compliance Status",
                    ["Not Evaluated", "Not Applicable", "Compliant", "Partial", "Non-Compliant"],
                    index=0,
                )
                method = st.multiselect(
                    "Method of Compliance",
                    [
                        "Service Bulletin",
                        "AMM Task",
                        "STC/Mod",
                        "DER-approved Repair",
                        "Alternative Method of Compliance (AMOC)",
                        "Work Order/ Engineering Order",
                    ],
                )
                method_other = st.text_input("If Other/Details (doc refs, SB #, AMM task, etc.)")
            with col2:
                perf_date = st.date_input("Compliance Date")
                perf_hours = st.number_input("Aircraft Hours at Compliance", min_value=0, step=1, value=0)
                perf_cycles = st.number_input("Aircraft Cycles at Compliance", min_value=0, step=1, value=0)

            st.markdown("**Applicability (aircraft/engine/component/serials)**")
            applic_aircraft = st.text_input("Aircraft / Model / Component", value="")
            applic_serials = st.text_input("Serials / MSN / PNs", value="")

            st.markdown("**Repetitive Requirements (optional)**")
            rep = st.checkbox("This AD has repetitive requirements")
            rep_col1, rep_col2, rep_col3 = st.columns(3)
            with rep_col1:
                rep_interval_value = st.number_input("Interval value", min_value=0, step=1, value=0, disabled=not rep)
            with rep_col2:
                rep_interval_unit = st.selectbox(
                    "Interval unit", ["hours", "cycles", "days", "months", "years"], disabled=not rep
                )
            with rep_col3:
                rep_basis = st.selectbox(
                    "Interval basis", ["since last compliance", "since effective date", "calendar"], disabled=not rep
                )

            submitted = st.form_submit_button("Add Compliance Entry")

        if submitted:
            record = {
                "ad_number": ad_number,
                "document_number": data.get("document_number"),
                "status": status,
                "method": method,
                "method_other": method_other,
                "applic_aircraft": applic_aircraft,
                "applic_serials": applic_serials,
                "performed_date": str(perf_date) if perf_date else None,
                "performed_hours": int(perf_hours) if perf_hours is not None else None,
                "performed_cycles": int(perf_cycles) if perf_cycles is not None else None,
                "repetitive": rep,
                "rep_interval_value": int(rep_interval_value) if rep else None,
                "rep_interval_unit": rep_interval_unit if rep else None,
                "rep_basis": rep_basis if rep else None,
                "next_due": None,
            }

            next_due = {}
            if rep:
                if rep_interval_unit == "hours" and record.get("performed_hours") is not None:
                    next_due["hours"] = record["performed_hours"] + record["rep_interval_value"]
                if rep_interval_unit == "cycles" and record.get("performed_cycles") is not None:
                    next_due["cycles"] = record["performed_cycles"] + record["rep_interval_value"]
                if rep_interval_unit in {"days", "months", "years"}:
                    next_due["calendar"] = f"+{record['rep_interval_value']} {record['rep_interval_unit']} ({rep_basis})"
            record["next_due"] = next_due or None

            st.session_state["compliance_records"].append(record)
            st.success("Compliance entry added.")

        if st.session_state["compliance_records"]:
            st.subheader("🗂️ Recorded Compliance Entries")
            for idx, rec in enumerate(st.session_state["compliance_records"], start=1):
                st.markdown(f"**Entry {idx}** — Status: {rec['status']}")
                st.json({k: v for k, v in rec.items()})

            buf_csv = io.StringIO()
            writer = csv.writer(buf_csv)
            writer.writerow([
                "ad_number","document_number","status","method","method_other","applic_aircraft",
                "applic_serials","performed_date","performed_hours","performed_cycles",
                "repetitive","rep_interval_value","rep_interval_unit","rep_basis","next_due"
            ])
            for rec in st.session_state["compliance_records"]:
                writer.writerow([
                    rec.get("ad_number"),
                    rec.get("document_number"),
                    rec.get("status"),
                    "; ".join(rec.get("method", []) or []),
                    rec.get("method_other"),
                    rec.get("applic_aircraft"),
                    rec.get("applic_serials"),
                    rec.get("performed_date"),
                    rec.get("performed_hours"),
                    rec.get("performed_cycles"),
                    rec.get("repetitive"),
                    rec.get("rep_interval_value"),
                    rec.get("rep_interval_unit"),
                    rec.get("rep_basis"),
                    json.dumps(rec.get("next_due")),
                ])
            st.download_button(
                "Download Compliance CSV",
                data=buf_csv.getvalue().encode("utf-8"),
                file_name=f"compliance_{data['document_number']}.csv",
                mime="text/csv",
            )

        # -----------------------------
        # PDF Report Download (single)
        # -----------------------------
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
                        records=st.session_state["compliance_records"],
                        logo_url=LOGO_URL,
                        site_url=SITE_URL,
                        customer=customer_for_report,
                        aircraft=aircraft_for_report,
                        ata_chapter=ata_chapter if ata_chapter else detect_ata_fallback(details.get("_full_html_text",""), details.get("sb_references")),
                        stamp_bytes=stamp_bytes_data,
                        stamp_path_or_url=stamp_path_or_url if stamp_bytes_data is None else None,
                        watermark_text=("DEMO" if add_demo_watermark else None)
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
            st.warning(
                "PDF generation requires the 'reportlab' package. "
                "Add `reportlab` to your requirements.txt (and `Pillow` for image handling)."
            )

    else:
        st.error("❌ AD not found. Please check the number exactly as it appears (e.g., 2025-01-01).")


# -----------------------------
# 📦 Batch Mode (Excel → merged PDF) — Option B
# -----------------------------
st.divider()
st.subheader("📦 Batch Mode (Excel → merged PDF)")
st.caption("""
Upload an .xlsx with:
- Sheet 1: AD list containing a column named **AD Number**. Optional columns: **Customer**, **Aircraft**.
- Sheet 2: **Records** with columns: **AD Number, Status, Method, Method Other, Applic Aircraft, Serials, Performed Date, Performed Hours, Performed Cycles, Repetitive, Interval Value, Interval Unit, Basis**.
Multiple rows per AD Number are allowed to add multiple records per AD.
""")
xlsx = st.file_uploader("Upload AD workbook (.xlsx)", type=["xlsx"], key="batch_xlsx")

if xlsx is not None and (not PANDAS_AVAILABLE or not PYPDF2_AVAILABLE or not REPORTLAB_AVAILABLE):
    missing = []
    if not PANDAS_AVAILABLE: missing.append("pandas")
    if not PYPDF2_AVAILABLE: missing.append("PyPDF2")
    if not REPORTLAB_AVAILABLE: missing.append("reportlab (and pillow)")
    st.error("Batch mode requires: " + ", ".join(missing))

if xlsx is not None and PANDAS_AVAILABLE and PYPDF2_AVAILABLE and REPORTLAB_AVAILABLE:
    if st.button("Generate merged PDF with tally"):
        try:
            # Read all sheets so we can access the 'Records' sheet
            sheets = pd.read_excel(xlsx, sheet_name=None)  # requires openpyxl
        except Exception as e:
            st.error(f"Failed to read Excel file: {e}")
            sheets = None

        if sheets is not None:
            # Find main sheet (first sheet by order)
            if len(sheets) == 0:
                st.error("The workbook is empty.")
            else:
                # First sheet is AD list
                first_sheet_name = list(sheets.keys())[0]
                df_main = sheets[first_sheet_name]
                df_records = sheets.get("Records", None)

                # try to find AD column
                ad_col = None
                for c in df_main.columns:
                    if str(c).strip().lower() in {"ad number", "ad_number", "ad"}:
                        ad_col = c
                        break
                if ad_col is None:
                    st.error(f"No column named 'AD Number' found in sheet '{first_sheet_name}'.")
                else:
                    merger = PdfMerger()
                    tally_rows = []

                    # Prepare stamp bytes once (used ONLY for tally sheet per your request)
                    tally_stamp_bytes = stamp_file.read() if stamp_file is not None else None
                    tally_stamp_url = stamp_path_or_url if tally_stamp_bytes is None else None

                    # Iterate ADs
                    for idx, row in df_main.iterrows():
                        ad_no = str(row[ad_col]).strip()
                        if not ad_no or ad_no.lower() == "nan":
                            continue

                        row_customer = ""
                        row_aircraft = ""
                        # optional columns
                        for col in df_main.columns:
                            cl = str(col).strip().lower()
                            if cl == "customer":
                                v = row[col]
                                row_customer = "" if (isinstance(v, float) and pd.isna(v)) else str(v)
                            if cl == "aircraft":
                                v = row[col]
                                row_aircraft = "" if (isinstance(v, float) and pd.isna(v)) else str(v)

                        # fetch AD data
                        data = fetch_ad_data(ad_no)
                        if not data:
                            st.warning(f"Skipping {ad_no}: not found.")
                            continue
                        data["ad_number"] = ad_no
                        api_doc = fetch_document_json(data.get("document_number"))
                        details = extract_details(data['html_url'], api_doc)

                        detected_ata = detect_ata_from_subject(details.get("_full_html_text",""))
                        if not detected_ata:
                            detected_ata = detect_ata_fallback(details.get("_full_html_text",""), details.get("sb_references"))

                        # Resolve effective date
                        api_eff_field_iso = (data.get("effective_date") or "").strip()
                        effective_resolved_iso = api_eff_field_iso if api_eff_field_iso and api_eff_field_iso.upper() != "N/A" else None
                        if not effective_resolved_iso:
                            effective_resolved_iso = extract_effective_from_api_document(
                                api_doc,
                                html_fallback_text=details.get("_full_html_text", "")
                            )
                        eff_display = to_ddmmyyyy(effective_resolved_iso) or to_ddmmyyyy(api_eff_field_iso)
                        if eff_display:
                            data["effective_date"] = eff_display

                        # Build compliance records from Records sheet (Option B)
                        records_for_this_ad = []
                        if df_records is not None and not df_records.empty:
                            try:
                                records_for_this_ad = build_records_for_ad(ad_no, df_records)
                            except Exception as e:
                                st.warning(f"Failed to parse records for {ad_no}: {e}")

                        # Single report PDF in-memory (NO stamp here, stamp only on tally)
                        try:
                            pdf_bytes = build_pdf_report(
                                ad_data=data,
                                details=details,
                                records=records_for_this_ad,
                                logo_url=LOGO_URL,
                                site_url=SITE_URL,
                                customer=row_customer or customer_for_report,
                                aircraft=row_aircraft,
                                ata_chapter=detected_ata,
                                stamp_bytes=None,  # limit stamp to tally sheet only
                                stamp_path_or_url=None,
                                watermark_text=("DEMO" if add_demo_watermark else None)
                            )
                            merger.append(io.BytesIO(pdf_bytes))
                        except Exception as e:
                            st.warning(f"Failed to build PDF for {ad_no}: {e}")
                            continue

                        # Add to tally
                        tally_rows.append({
                            "ad_number": ad_no,
                            "document_number": data.get("document_number", ""),
                            "title": data.get("title", "") or "",
                            "publication_date": data.get("publication_date", "") or "",
                            "effective_date": data.get("effective_date", "") or "N/A",
                            "ata": detected_ata or "",
                        })

                    # Build tally sheet PDF and append to merger
                    try:
                        tally_pdf = build_tally_pdf(
                            rows=tally_rows,
                            logo_url=LOGO_URL,     # preserve AR on tally via helper
                            site_url=SITE_URL,
                            stamp_bytes=tally_stamp_bytes,
                            stamp_path_or_url=tally_stamp_url,
                            watermark_text=("DEMO" if add_demo_watermark else None)
                        )
                        merger.append(io.BytesIO(tally_pdf))
                    except Exception as e:
                        st.warning(f"Failed to build/append tally sheet: {e}")

                    # Output merged
                    out_buf = io.BytesIO()
                    merger.write(out_buf)
                    merger.close()
                    out_buf.seek(0)
                    st.download_button(
                        "Download Merged PDF (with tally)",
                        data=out_buf.getvalue(),
                        file_name="AD_Merged_Report.pdf",
                        mime="application/pdf",
                    )
