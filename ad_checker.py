def extract_details_from_html(html_url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(html_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        full_text = soup.get_text("\n", strip=True).replace("\u00a0", " ")

        def find_section_text(keyword):
            candidates = soup.find_all(["strong", "h4", "h3", "h2"])
            for tag in candidates:
                if tag.get_text(strip=True).lower().startswith(keyword.lower()):
                    content = ""
                    for sibling in tag.next_siblings:
                        if getattr(sibling, "name", "") in ["strong", "h4", "h3", "h2"]:
                            break
                        if hasattr(sibling, "get_text"):
                            content += sibling.get_text(separator="\n", strip=True) + "\n"
                        elif isinstance(sibling, str):
                            content += sibling.strip() + "\n"
                    return content.strip()
            return None  # return None so we know to try regex fallback

        # First pass: try visible headers
        details = {
            "affected_aircraft": find_section_text("Applicability"),
            "required_actions": find_section_text("Compliance") or find_section_text("Required Actions"),
            "compliance_times": find_section_text("Compliance Time"),
            "unsafe_condition": find_section_text("Unsafe Condition"),
        }

        # Second pass: regex over raw text for common phrases
        def regex_grab(labels):
            for lbl in labels:
                m = re.search(rf"{re.escape(lbl)}\s*:?[\s\n]+(.+?)(?:\n\s*\n|\Z)", full_text, flags=re.I | re.S)
                if m:
                    return m.group(1).strip()
            return None

        details["affected_aircraft"] = details["affected_aircraft"] or regex_grab(
            ["Applicability", "(c) Applicability"]
        ) or "Not found"

        details["unsafe_condition"] = details["unsafe_condition"] or regex_grab(
            ["Unsafe Condition", "(e) Unsafe Condition"]
        ) or "Not found"

        details["required_actions"] = details["required_actions"] or regex_grab(
            ["Required Actions", "Actions and Compliance", "(i) Required Actions", "(h) Compliance"]
        ) or "Not found"

        details["compliance_times"] = details["compliance_times"] or regex_grab(
            ["Compliance Time", "Compliance", "(h) Compliance"]
        ) or "Not found"

        # Effective date fallback when API has N/A
        eff = regex_grab(["(d) Effective Date", "Effective Date", "This AD is effective"])
        if eff:
            details["effective_date_text"] = eff

        return details

    except Exception as e:
        return {
            "affected_aircraft": f"Error extracting: {e}",
            "required_actions": "N/A",
            "compliance_times": "N/A",
            "unsafe_condition": "N/A",
        }
