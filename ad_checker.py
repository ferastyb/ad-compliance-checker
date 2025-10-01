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
    from reportlab.lib import colors
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
# NEW: Bullet summarizer for (g) and (h)
# -----------------------------
def summarize_to_bullets(text: str | None, max_items: int = 8) -> list[str]:
    """
    Create concise bullet points from an AD paragraph.
    - If the text already has numbered/lettered items, extract those.
    - Otherwise, split into sentences and keep the most action-heavy lines.
    """
    if not text or text.strip().upper() == "N/A":
        return []

    t = text.replace("\u00a0", " ").strip()

    # 1) Prefer explicit list items (1., (1), a.), etc.
    items = []
    for line in t.splitlines():
        m = re.match(r"^\s*(?:\(?\d+\)|\d+\.)\s+(.*)$", line.strip())
        if not m:
            m = re.match(r"^\s*(?:\(?[a-zA-Z]\)|[a-zA-Z]\.)\s+(.*)$", line.strip())
        if m:
            item = m.group(1).strip().rstrip(";:,")
            if len(item) > 2:
                items.append(item)

    if items:
        # Keep the first clause per item to make bullets punchy
        clean = []
        for it in items:
            part = re.split(r"(?<=[.;:])\s+", it)[0]
            clean.append(part)
        seen, out = set(), []
        for c in clean:
            key = c.lower()
            if key not in seen:
                seen.add(key); out.append(c)
        return out[:max_items]

    # 2) Otherwise, score sentences by action keywords
    sentences = re.split(r'(?<=[.!?])\s+', t)
    keywords = [
        "inspect", "replace", "modify", "repair", "remove", "install",
        "before", "after", "within", "until", "thereafter", "repeat",
        "prohibit", "comply", "in accordance", "per", "service bulletin",
        "amm", "stc", "amoc", "der", "except", "unless"
    ]
    ranked = []
    for s in sentences:
        s_clean = s.strip().rstrip(";")
        if not s_clean:
            continue
        score = sum(1 for k in keywords if k in s_clean.lower())
        if re.match(r"^(inspect|replace|modify|repair|remove|install|revise|accomplish)\b", s_clean.lower()):
            score += 2
        ranked.append((score, s_clean))

    ranked.sort(key=lambda x: (-x[0], len(x[1])))
    bullets = [s for score, s in ranked if score > 0][:max_items]

    if not bullets:
        bullets = sentences[: min(max_items, 5)]

    seen, out = set(), []
    for b in bullets:
        key = b.lower()
        if key not in seen:
            seen.add(key); out.append(b)
    return out[:max_items]

# -----------------------------
# ATA Chapter detection (from (d) Subject first)
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

def extract_effective_from_api_document(doc_json: dict, html_fallback_text: str | None = None) -> str | None:
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
def extract_details(ad_html_url: str, api_doc: dict | None):
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
def _image_flowable_fit(source_bytes: bytes | None = None, path_or_url: str | None = None,
                        max_w_mm: float = 60, max_h_mm: float = 60):
    """Return a ReportLab Image flowable scaled proportionally to fit within max box."""
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
# PDF report builder
# -----------------------------
def build_pdf_report(
    ad_data: dict,
    details: dict,
    records: list,
    logo_url: str,
    site_url: str,
    customer: str,
    aircraft: str,
    ata_chapter: str | None,
    stamp_bytes: bytes | None = None,
    stamp_path_or_url: str | None = None
) -> bytes:
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab is not installed. Add 'reportlab' to your requirements.txt.")

    # Prepare grayscale 30% logo
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
        try:
            resp = requests.get(logo_url, timeout=10)
            resp.raise_for_status()
            logo_flowable = Image(io.BytesIO(resp.content), width=40*mm)
        except Exception:
            logo_flowable = None

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

    story = []

    if logo_flowable:
        story.append(logo_flowable)
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

    # --- New: Bullet summaries for (g) and (h) ---
    story.append(Paragraph("Action Items (Summarized)", h3))

    bullets_g = summarize_to_bullets(details.get("required_actions"))
    if bullets_g:
        for i, b in enumerate(bullets_g, 1):
            story.append(Paragraph(f"{i}. {b}", normal))
    else:
        story.append(Paragraph("Required Actions: N/A", normal))

    story.append(Spacer(1, 6))

    bullets_h = summarize_to_bullets(details.get("exceptions"))
    if bullets_h:
        for i, b in enumerate(bullets_h, 1):
            story.append(Paragraph(f"{i}. {b}", normal))
    else:
        story.append(Paragraph("Exceptions: N/A", normal))

    story.append(Spacer(1, 10))
    # --- End new block ---

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
    # --------------------------------------------------------------------------

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
    # ----------------------------------------------

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

        st.subheader("🛩️ Applicability / Affected Aircraft")
        st.write(details.get("affected_aircraft") or "N/A")

        st.subheader("📎 SB References (from Required Actions)")
        sb_list = details.get("sb_references") or []
        st.write(", ".join(sb_list) if sb_list else "N/A")

        # --- New: Bullet summaries in UI ---
        st.subheader("🔧 (g) Required Actions — Summary")
        bullets_g = summarize_to_bullets(details.get("required_actions"))
        if bullets_g:
            st.markdown("\n".join([f"{i+1}. {b}" for i, b in enumerate(bullets_g)]))
        else:
            st.write("N/A")

        st.subheader("📌 (h) Exceptions to Service Information Specifications — Summary")
        bullets_h = summarize_to_bullets(details.get("exceptions"))
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
                        "Other",
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

            buf = io.StringIO()
            writer = csv.writer(buf)
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
                data=buf.getvalue().encode("utf-8"),
                file_name=f"compliance_{data['document_number']}.csv",
                mime="text/csv",
            )

        # -----------------------------
        # PDF Report Download
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
                        ata_chapter=ata_chapter if ata_chapter else detected_ata,
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
            st.warning(
                "PDF generation requires the 'reportlab' package. "
                "Add `reportlab` to your requirements.txt (and `Pillow` for image handling)."
            )

    else:
        st.error("❌ AD not found. Please check the number exactly as it appears (e.g., 2025-01-01).")
