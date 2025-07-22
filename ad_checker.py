
import streamlit as st
import pandas as pd

st.set_page_config(page_title="AD Compliance Checker", layout="wide")

st.title("📋 Airworthiness Directive (AD) Compliance Checker")

st.markdown("Use this tool to verify compliance of your aircraft against applicable Airworthiness Directives.")

uploaded_ad_file = st.file_uploader("Upload AD PDF", type="pdf", help="Upload an Airworthiness Directive document.")
uploaded_aircraft_data = st.file_uploader("Upload Aircraft Compliance Data", type=["csv", "xlsx"], help="Upload your aircraft's compliance record.")

if uploaded_ad_file and uploaded_aircraft_data:
    st.info("✅ Files uploaded successfully. Compliance logic to be implemented.")
    # TODO: Add AD parser, compare with aircraft data
else:
    st.warning("⬆️ Please upload both the AD and aircraft compliance file.")

st.markdown("---")
st.markdown("ℹ️ *Future versions will support automated parsing and matching of conditions, thresholds, and actions.*")
