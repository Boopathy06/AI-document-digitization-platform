"""Field extraction rules specific to Indian Driving Licences.

Enhanced:
- Explicit label-first name extraction (Name:, S/O:)
- DL number extraction with multiple formats
- DOB label vs fallback date disambiguation
- Issue & validity date extraction
"""

import re
from typing import Dict

from .common import (
    add_if_found,
    clean_person_name,
    extract_district,
    extract_driving_licence_number,
    extract_valid_date,
    normalized_lines,
    validate_and_clean_citizen_name,
)

NON_DL_WORDS = {
    "driving", "licence", "license", "transport", "department", "union",
    "india", "form", "signature", "authority", "date", "issue", "validity",
    "motor", "vehicles", "act", "badge", "blood", "group", "vehicle",
    "driving licence", "renewal", "valid", "expiry", "endorsement",
}


def extract_fields(ocr_text: str) -> Dict[str, str]:
    """Extract standard Driving Licence fields (DL number, holder name, DOB, dates)."""
    text = normalized_lines(ocr_text)
    fields: Dict[str, str] = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 1. Driving Licence Number
    dl_no = extract_driving_licence_number(text)
    add_if_found(fields, "Certificate Number", dl_no)
    add_if_found(fields, "Driving Licence Number", dl_no)

    # 2. Date of Birth – explicit label
    m_dob = re.search(
        r"(?:DOB|Date\s+of\s+Birth)\s*[:\-/]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        text,
        re.I,
    )
    if m_dob:
        add_if_found(fields, "Date of Birth", m_dob.group(1).replace("/", "-"))
    else:
        add_if_found(fields, "Date of Birth", extract_valid_date(text))

    # 3. Citizen Name – explicit label first
    citizen_name = None

    m_name = re.search(
        r"(?:Name|Holder)\s*[:\-]?\s*([A-Za-z\s\.]{2,40}?)"
        r"(?=\s*(?:S/O|D/O|W/O|DOB|Date|Address|Father|$|\n))",
        text,
        re.I,
    )
    if m_name:
        cand = clean_person_name(m_name.group(1))
        if len(cand) >= 2 and not any(w in cand.lower() for w in NON_DL_WORDS):
            citizen_name = cand

    # Fallback: first clean all-caps or Title-case line
    if not citizen_name:
        for line in lines:
            # Skip header lines and lines with numbers
            if re.search(r"\d", line):
                continue
            if any(w in line.lower() for w in NON_DL_WORDS):
                continue
            cand = clean_person_name(line)
            if len(cand) >= 4 and re.match(r"^[A-Za-z\s\.]{4,40}$", cand):
                citizen_name = cand
                break

    citizen_name = validate_and_clean_citizen_name(citizen_name)
    add_if_found(fields, "Citizen Name", citizen_name)

    # 4. Father / Guardian
    m_fat = re.search(
        r"(?:S/O|D/O|W/O|Father'?s?\s+Name)\s*[:\-]?\s*([A-Za-z\s\.]{2,40}?)(?:,|\n|$)",
        text,
        re.I,
    )
    if m_fat:
        cand_f = validate_and_clean_citizen_name(m_fat.group(1))
        add_if_found(fields, "Father / Guardian", cand_f)

    # 5. Issue Date & Validity Date
    # Look for "Issue Date" or "Date of Issue" label
    m_issue = re.search(
        r"(?:Date\s+of\s+Issue|Issue\s+Date|Issued\s+On)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        text,
        re.I,
    )
    if m_issue:
        add_if_found(fields, "Issue Date", m_issue.group(1).replace("/", "-"))
    else:
        issue_date = extract_valid_date(text)
        add_if_found(fields, "Issue Date", issue_date)

    # Validity / Expiry Date
    m_valid = re.search(
        r"(?:Valid(?:ity)?\s+(?:Till|Upto|Until|To)|Expiry|Expires)\s*[:\-]?\s*"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        text,
        re.I,
    )
    if m_valid:
        add_if_found(fields, "Valid Till", m_valid.group(1).replace("/", "-"))

    # 6. Blood Group
    m_blood = re.search(r"\b(A|B|AB|O)[+-]\b", text)
    if m_blood:
        add_if_found(fields, "Blood Group", m_blood.group(0))

    # 7. District
    district = extract_district(text)
    add_if_found(fields, "District", district)

    return fields
