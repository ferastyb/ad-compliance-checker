# ad_checker.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
import json
import io
import csv
from datetime import datetime

# --- PDF (ReportLab) imports ---
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.utils import ImageReader
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# -----------------------------
# Page setup + Branding
# -----------------------------
st.set_page_config(page_title="FAA AD Compliance Checker", layout="centered")

LOGO_URL = "https://www.ferasaviation.info/gallery/FA__logo.png?ts=1754692591"
SITE_URL = "https://www.ferasaviation.info"

# Logo
st.image(LOGO_URL, width=180)
# Website under logo (clickable)
st.markdown(f"[🌐 www.ferasaviation.info]({SITE_URL})")

st.title("🛠️ AD Compliance Checker")

# Session state for compliance entries
if "compliance_records" not in st.session_state:
    st.session_state["compliance_records"] = []

# -----------------------------
# Input
# -----------------------------
ad_number = st.text_input("Enter AD Number (e.g., 2020-06-14):").strip()

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
            timeout=10
        )
        response.raise_for_status()
        results = response.json().get("results", [])

        for doc in results:
            title = doc.get("title", "")
            if ad_number in title or "airworthiness directive" in title.lower():
                return {
                    "title": title,
                    "effective_date": doc.get("effective_on"),
                    "html_url": doc.get("html_url"),
                    "pdf_url": doc.get("pdf_url"),
                    "document_number": doc.get("document_number"),
                    "publication_date": doc.get("publication_date")
                }

    except requests.RequestException as e:
        st.error(f"❌ Request failed: {e}")

    return None


def extract_details_from_html(html_url: str):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(html_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        def find_section_text(keyword: str):
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
            return "Retrieving..."

        return {
            "affected_aircraft": find_section_text("Applicability"),
            "required_actions": find_section_text("Compliance"),
            "compliance_times": find_section_text("Compliance Time")
        }

    except Exception as e:
        return {
            "affected_aircraft": f"Error extracting: {e}",
            "required_actions": "N/A",
            "compliance_times": "N/A"
        }

# -----------------------------
# PDF report builder
# -----------------------------
def build_pdf_report(ad_data: dict, details: dict, records: list, logo_url: str, site_url: str) -> bytes:
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
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    h3 = styles["Heading3"]
    normal = styles["BodyText"]
    small = ParagraphStyle("small", parent=normal, fontSize=9, leading=12, textColor=colors.grey)

    story = []

    # Header with Logo + site
    try:
        resp = requests.get(logo_url, timeout=10)
        resp.raise_for_status()
        logo_reader = ImageReader(io.BytesIO(resp.content))
        img = Image(logo_reader, width=40*mm, height=14*mm)
        story.append(img)
    except Exception:
        pass

    story.append(Paragraph(f'<font size="12"><a href="{site_url}">{site_url}</a></font>', small))
    story.append(Spacer(1, 6))

    # Title
    story.append(Paragraph("AD Compliance Report", h1))
    story.append(Spacer(1, 6))
    generated_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(f"Generated: {generated_ts}", small))
    story.append(Spacer(1, 12))

    # AD Metadata
    story.append(Paragraph("Airworthiness Directive", h2))
    meta_data = [
        ["AD Number", ad_data.get("ad_number") or ""],   # <-- Added AD Number here
        ["Document Number", ad_data.get("document_number") or ""],
        ["AD Title", ad_data.get("title") or ""],
        ["Publication Date", ad_data.get("publication_date") or "N/A"],
        ["Effective Date", ad_data.get("effective_date") or "N/A"],
        ["HTML", ad_data.get("html_url") or ""],
        ["PDF", ad_data.get("pdf_url") or ""],
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

    # Extracted Sections
    story.append(Paragraph("Extracted Details", h2))
    for section_title, key in [
        ("Applicability / Affected Aircraft", "affected_aircraft"),
        ("Required Actions", "required_actions"),
        ("Compliance Deadlines", "compliance_times"),
    ]:
        story.append(Paragraph(section_title, h3))
        text = (details.get(key) or "").replace("\n", "<br/>")
        if not text.strip():
            text = "N/A"
        story.append(Paragraph(text, normal))
        story.append(Spacer(1, 8))

    # Compliance Records
    story.append(Paragraph("Compliance Records", h2))
    if not records:
        story.append(Paragraph("No compliance records added.", normal))
    else:
        header = [
            "Status", "Method", "Details",
            "Applicability (Aircraft/Component)", "Serials",
            "Date", "Hours", "Cycles", "Repetitive", "Interval", "Basis", "Next Due"
        ]
        rows = [header]
        for rec in records:
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
        # Attach AD number so it shows in PDF report
        data["ad_number"] = ad_number

        st.success(f"✅ Found: {data['title']}")
        st.write(f"**AD Number:** {ad_number}")
        st.write(f"**Document Number:** {data['document_number']}")
        st.write(f"**Publication Date:** {data.get('publication_date') or 'N/A'}")
        st.write(f"**Effective Date:** {data['effective_date'] or 'N/A'}")
        st.markdown(f"[🔗 View Full AD (HTML)]({data['html_url']})")
        st.markdown(f"[📄 View PDF]({data['pdf_url']})")

        with st.spinner("📄 Extracting AD details from HTML..."):
            details = extract_details_from_html(data['html_url'])

        st.subheader("🛩️ Affected Aircraft / SB References")
        st.write(details['affected_aircraft'])

        st.subheader("🔧 Required Actions")
        st.write(details['required_actions'])

        st.subheader("📅 Compliance Deadlines")
        st.write(details['compliance_times'])

        # (rest of compliance form + CSV + PDF generation remains unchanged)
        # ...
