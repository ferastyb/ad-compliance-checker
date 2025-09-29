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
    """
    Build a PDF summarizing the AD search result, extracted sections, and compliance records.
    PDF-only: logo is converted to grayscale and resized to ~30%, placed above the website link.
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab is not installed. Add 'reportlab' to your requirements.txt.")

    # Prepare grayscale 30% logo (pass BytesIO to ReportLab Image to avoid ImageReader error)
    logo_flowable = None
    try:
        from PIL import Image as PILImage
        resp = requests.get(logo_url, timeout=10)
        resp.raise_for_status()
        pil_img = PILImage.open(io.BytesIO(resp.content)).convert("L")  # grayscale
        w, h = pil_img.size
        pil_img = pil_img.resize((max(1, int(w * 0.3)), max(1, int(h * 0.3))), PILImage.LANCZOS)  # 30%
        logo_buf = io.BytesIO()
        pil_img.save(logo_buf, format="PNG")
        logo_buf.seek(0)
        logo_flowable = Image(logo_buf)  # let ReportLab infer dimensions
    except Exception:
        # Fallback: original logo bytes with a reasonable width
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

    # Grayscale logo above website
    if logo_flowable:
        story.append(logo_flowable)

    # Website link
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
        ["AD Number", ad_data.get("ad_number") or ""],   # AD Number above Document Number
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
        # Attach AD number so it shows in the PDF report
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

            # Compute a simple "Next Due" for hours/cycles; store calendar as a definition
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
                    pdf_bytes = build_pdf_report(
                        ad_data=data,                  # includes ad_number
                        details=details,
                        records=st.session_state["compliance_records"],
                        logo_url=LOGO_URL,
                        site_url=SITE_URL
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
        st.error("❌ AD not found. Please check the number exactly as it appears (e.g., 2020-06-14).")
