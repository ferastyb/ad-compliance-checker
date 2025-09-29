import streamlit as st
import requests
from bs4 import BeautifulSoup

st.set_page_config(page_title=" FAA AD Compliance Checker", layout="centered")
st.title("🛠️ AD Compliance Checker")

# --- Session state for compliance entries ---
if "compliance_records" not in st.session_state:
    st.session_state["compliance_records"] = []

ad_number = st.text_input("Enter AD Number (e.g., 2020-06-14):").strip()

def fetch_ad_data(ad_number):
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
                    "document_number": doc.get("document_number")
                }

    except requests.RequestException as e:
        st.error(f"❌ Request failed: {e}")

    return None

def extract_details_from_html(html_url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(html_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        def find_section_text(keyword):
            candidates = soup.find_all(["strong", "h4", "h3", "h2"])
            for tag in candidates:
                if tag.get_text(strip=True).lower().startswith(keyword.lower()):
                    content = ""
                    for sibling in tag.next_siblings:
                        if sibling.name in ["strong", "h4", "h3", "h2"]:
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

if ad_number:
    with st.spinner("🔍 Searching Federal Register..."):
        data = fetch_ad_data(ad_number)

    if data:
        st.success(f"✅ Found: {data['title']}")
        st.write(f"**Document Number:** {data['document_number']}")
        st.write(f"**Effective Date:** {data['effective_date']}")
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
                    ["Service Bulletin", "AMM Task", "STC/Mod", "DER-approved Repair", "Alternative Method of Compliance (AMOC)", "Other"],
                )
                method_other = st.text_input("If Other/Details (doc refs, SB #, AMM task, etc.)")
            with col2:
                perf_date = st.date_input("Compliance Date", value=None)
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
                rep_interval_unit = st.selectbox("Interval unit", ["hours", "cycles", "days", "months", "years"], disabled=not rep)
            with rep_col3:
                rep_basis = st.selectbox("Interval basis", ["since last compliance", "since effective date", "calendar"], disabled=not rep)

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
            # Compute a simple "Next Due" field based on the unit (hours/cycles only here; calendar can be inferred outside)
            next_due = {}
            if rep:
                if rep_interval_unit == "hours" and record.get("performed_hours") is not None:
                    next_due["hours"] = record["performed_hours"] + record["rep_interval_value"]
                if rep_interval_unit == "cycles" and record.get("performed_cycles") is not None:
                    next_due["cycles"] = record["performed_cycles"] + record["rep_interval_value"]
                # For calendar units we store the definition; exact next date may require fleet utilization
                if rep_interval_unit in {"days", "months", "years"}:
                    next_due["calendar"] = f"+{record['rep_interval_value']} {record['rep_interval_unit']} ({record['rep_basis']})"
            record["next_due"] = next_due or None

            st.session_state.compliance_records.append(record)
            st.success("Compliance entry added.")

        # Show recorded entries
        if st.session_state.compliance_records:
            st.subheader("🗂️ Recorded Compliance Entries")
            for idx, rec in enumerate(st.session_state.compliance_records, start=1):
                st.markdown(f"**Entry {idx}** — Status: {rec['status']}")
                st.write({k: v for k, v in rec.items() if k not in ("ad_number",)})

            # Offer export of entries
            import json, io, csv
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["ad_number","document_number","status","method","method_other","applic_aircraft","applic_serials","performed_date","performed_hours","performed_cycles","repetitive","rep_interval_value","rep_interval_unit","rep_basis","next_due"])
            for rec in st.session_state.compliance_records:
                writer.writerow([
                    rec.get("ad_number"),
                    rec.get("document_number"),
                    rec.get("status"),
                    "; ".join(rec.get("method", [])),
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
            st.download_button("Download Compliance CSV", data=buf.getvalue().encode("utf-8"), file_name=f"compliance_{data['document_number']}.csv", mime="text/csv")

    else:
        st.error("❌ AD not found. Please check the number exactly as it appears (e.g., 2020-06-14).")
