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
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# -----------------------------
# Page setup + Branding (UI)
# -----------------------------
st.set_page_config(page_title="FAA AD Compliance Checker", layout="centered")

LOGO_URL = "https://www.ferasaviation.info/gallery/FA__logo.png?ts=1754692591"
SITE_URL = "https://www.ferasaviation.info"

# UI logo (unchanged)
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
        return datetime.strptime(date_str.strip(), "%B %d, %Y").date().isoformat()  # YYYY-MM-DD
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
        window = t[eff_idx:eff_idx + 180]
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
# NEW: Section + SB Utilities
# -----------------------------
def parse_lettered_sections(full_text: str):
    """
    Build a dict of lettered sections from plain text:
      { 'a': {'title': 'Authority', 'text': '...'}, 'c': {'title': 'Applicability', 'text': '...'}, ... }
    Robust to punctuation after title and varying whitespace.
    """
    sections = {}
    if not full_text:
        return sections

    t = full_text.replace("\u00a0", " ")
    # Find all section headers like "(c) Applicability", "(g) Required Actions", capturing positions
    header_re = re.compile(r"\(\s*([a-z])\s*\)\s*([A-Za-z][^\n]{0,120})", re.IGNORECASE)
    matches = list(header_re.finditer(t))
    for i, m in enumerate(matches):
        letter = m.group(1).lower()
        title = (m.group(2) or "").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(t)
        body = t[start:end].strip()
        # Clean title trailing punctuation
        title = re.sub(r"[.:;\s]+$", "", title)
        sections[letter] = {"title": title, "text": body}
    return sections

def find_sb_references(text: str) -> list[str]:
    if not text:
        return []
    sb_pat = re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)*-SB[0-9A-Z]+(?:-[0-9A-Z]+)*\b")
    refs = sb_pat.findall(text.upper())
    seen, ordered = set(), []
    for r in refs:
        if r not in seen:
            seen.add(r)
            ordered.append(r)
    return ordered

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
            text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
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


def extract_details_from_html(html_url: str):
    """
    Extract:
      - Affected Aircraft from (c) Applicability (fallback: header-based search)
      - Required Actions from (g) Required Actions (for context)
      - SB References from the (g) text (fallback: whole document)
      - Compliance Time (legacy)

    Returns a dict incl. '_full_html_text' for date parsing fallback.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(html_url, headers=headers, timeout=12)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        full_text = soup.get_text("\n", strip=True)

        # Parse all lettered sections once
        sections = parse_lettered_sections(full_text)

        # Helper: legacy header-based content (fallback)
        def legacy_find_section_text(keyword: str):
            candidates = soup.find_all(["strong", "h4", "h3", "h2"])
            for tag in candidates:
                if tag.get_text(strip=True).lower().startswith(keyword.lower()):
                    content = ""
                    for sibling in tag.next_siblings:
                        if getattr(sibling, "name", "") in ["strong", "h4", "h3", "h2"]:
                            break
                        if hasattr(sibling, 'get_text'):
                            content += sibling.get_text(separator="\n", strip=True) + "\n"
                        elif isinstance(sibling, str):
                            content += sibling.strip() + "\n"
                    return content.strip()
            return ""

        # (c) Applicability
        applic_text = None
        csec = sections.get("c")
        if csec:
            # Prefer when the title actually mentions Applicability
            if re.search(r"\bApplicability\b", csec["title"], flags=re.IGNORECASE):
                applic_text = csec["text"]
            else:
                # Even if the title is odd, use the text if it clearly contains applicability-related words
                if re.search(r"\bapplicab|aircraft|model|serial|msn|pn\b", csec["text"], flags=re.IGNORECASE):
                    applic_text = csec["text"]

        if not applic_text:
            # Fallback to legacy header scan
            applic_text = legacy_find_section_text("Applicability")

        # (g) Required Actions
        req_actions_text = None
        gsec = sections.get("g")
        if gsec:
            if re.search(r"\bRequired Actions\b", gsec["title"], flags=re.IGNORECASE):
                req_actions_text = gsec["text"]
            else:
                if re.search(r"\baction|comply|do the following\b", gsec["text"], flags=re.IGNORECASE):
                    req_actions_text = gsec["text"]

        if not req_actions_text:
            req_actions_text = legacy_find_section_text("Required Actions")

        # SB References: prefer from (g) text; else scan whole page
        sb_refs = find_sb_references(req_actions_text) if req_actions_text else []
        if not sb_refs:
            sb_refs = find_sb_references(full_text)

        return {
            "affected_aircraft": (applic_text or "N/A").strip(),
            "required_actions": (req_actions_text or "N/A").strip(),
            "compliance_times": (legacy_find_section_text("Compliance Time") or "N/A").strip(),
            "sb_references": sb_refs,
            "_full_html_text": full_text,
        }

    except Exception as e:
        return {
            "affected_aircraft": f"Error extracting: {e}",
            "required_actions": "N/A",
            "compliance_times": "N/A",
            "sb_references": [],
            "_full_html_text": "",
        }

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
    aircraft: str
) -> bytes:
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab is not installed. Add 'reportlab' to your requirements.txt.")

    # Prepare grayscale 30% logo (pass BytesIO to ReportLab Image)
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
    from reportlab.lib import colors
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

    story.append(Paragraph("Required Actions (raw section)", h3))
    ra_text = (details.get("required_actions") or "").replace("\n", "<br/>") or "N/A"
    story.append(Paragraph(ra_text, normal))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Compliance Deadlines", h3))
    ct_text = (details.get("compliance_times") or "").replace("\n", "<br/>") or "N/A"
    story.append(Paragraph(ct_text, normal))
    story.append(Spacer(1, 8))

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
        rows = [header]
        for rec in records_list:
            next_due = rec.get("next_due") or {}
            if isinstance(next_due, dict):
                nd_hours = next_due.get("hours")
                nd_cycles = next_due.get("cycles")
                nd_cal = next_due.get("calendar")
                nd_text = ", ".join([str(x) for x in [f"H:{nd_hours}" if nd_hours is not None else None,
                                                     f"C:{nd_cycles}" if nd_cycles is not None else None,
                                                     nd_cal] if x])
            else:
                nd_text = str(next_due)

            rows.append([
                rec.get("status", ""),
                "; ".join(rec.get("method", []) or []),
                rec.get("method_other", ""),
                rec.get("applic_aircraft", ""),
                rec.get("applic_serials", ""),
                rec.get("performed_date", ""),
                str(rec.get("performed_hours", "")),
                str(rec.get("performed_cycles", "")),
                "Yes" if rec.get("repetitive") else "No",
                (f"{rec.get('rep_interval_value','')} {rec.get('rep_interval_unit','')}".strip() if rec.get("repetitive") else ""),
                (rec.get("rep_basis","") if rec.get("repetitive") else ""),
                nd_text,
            ])

        widths = [18*mm, 25*mm, 28*mm, 30*mm, 28*mm, 18*mm, 14*mm, 14*mm, 16*mm, 20*mm, 20*mm, 26*mm]
        table = Table(rows, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("BOX", (0,0), (-1,-1), 0.5, colors.grey),
            ("INNERGRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
        ]))
        story.append(table)

    story.append(Spacer(1, 12))
    story.append(Paragraph("Generated by Feras Aviation AD Compliance Checker", small))

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
        data["ad_number"] = ad_number  # ensure it appears in PDF
        st.success(f"✅ Found: {data['title']}")
        st.write(f"**AD Number:** {ad_number}")
        st.write(f"**Document Number:** {data['document_number']}")
        st.write(f"**Publication Date:** {data.get('publication_date') or 'N/A'}")
        # Effective date shown as dd-mm-yyyy
        st.write(f"**Effective Date (API field):** {to_ddmmyyyy(data.get('effective_date')) or 'N/A'}")
        st.markdown(f"[🔗 View Full AD (HTML)]({data['html_url']})")
        st.markdown(f"[📄 View PDF]({data['pdf_url']})")

        # Extract page details (incl. full_text)
        with st.spinner("📄 Extracting AD details from HTML..."):
            details = extract_details_from_html(data['html_url'])

        # Fetch per-document JSON and resolve effective date (ISO → flip)
        api_doc = fetch_document_json(data.get("document_number"))
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
            data["effective_date"] = eff_display  # Use flipped format in PDF

        # ---------------- Affected Aircraft + SB References (UI) ----------------
        st.subheader("🛩️ Applicability / Affected Aircraft")
        st.write(details.get("affected_aircraft") or "N/A")

        sb_list = details.get("sb_references") or []
        st.subheader("📎 SB References (from Required Actions)")
        st.write(", ".join(sb_list) if sb_list else "N/A")

        st.subheader("🔧 Required Actions (raw section)")
        st.write(details.get("required_actions") or "N/A")

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
            }

            next_due = {}
            if rep:
                if rep_interval_unit == "hours" and record.get("performed_hours") is not None:
                    next_due["hours"] = record["performed_hours"] + record["rep_interval_value"]
                if rep_interval_unit == "cycles" and record.get("performed_cycles") is not None:
                    next_due["cycles"] = record["performed_cycles"] + record["rep_interval_value"]
                if rep_interval_unit in {"days", "months", "years"}:
                    next_due["calendar"] = f"+{record['rep_interval_value']} {record['rep_interval_unit']} ({record['rep_basis']})"
            record["next_due"] = next_due or None

            st.session_state["compliance_records"].append(record)
            st.success("Compliance entry added.")

        # Show recorded entries + CSV export
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

                    pdf_bytes = build_pdf_report(
                        ad_data=data,
                        details=details,
                        records=st.session_state["compliance_records"],
                        logo_url=LOGO_URL,
                        site_url=SITE_URL,
                        customer=customer_for_report,
                        aircraft=aircraft_for_report
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
                "Add `reportlab` to your requirements.txt (and `Pillow` for grayscale logo)."
            )

    else:
        st.error("❌ AD not found. Please check the number exactly as it appears (e.g., 2025-01-01).")
