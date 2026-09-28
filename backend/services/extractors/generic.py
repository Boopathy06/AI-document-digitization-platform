"""Fallback extractor for unclassified or generic documents."""

import re
from typing import Dict

from .common import (
    add_if_found,
    clean_person_name,
    extract_aadhaar_number,
    extract_certificate_number,
    extract_district,
    extract_issue_date,
    normalized_lines,
)


def extract_fields(ocr_text: str) -> Dict[str, str]:
    """Extract common fields from any document using broad patterns."""
    text = normalized_lines(ocr_text)
    fields: Dict[str, str] = {}

    # 1. Certificate / Identifier Number
    cert_no = extract_certificate_number(text)
    add_if_found(fields, "Certificate Number", cert_no)

    # 2. Aadhaar Number (if present)
    aadhaar = extract_aadhaar_number(text)
    add_if_found(fields, "Aadhaar Number", aadhaar)

    # 3. Citizen Name
    m_name = re.search(r"(?:Name\s*(?:of\s+(?:the\s+)?Student|of\s+Applicant)?|Applicant)\s*[:\-]?\s*([A-Za-z\s\.]+?)(?=\s+(?:Roll|Reg|DOB|Date|No|\d)|$|\n)", text, re.I)
    if m_name:
        add_if_found(fields, "Citizen Name", clean_person_name(m_name.group(1)))

    # 4. Roll / Registration Number
    m_roll = re.search(r"(?:Roll|Reg(?:istration)?)\s*(?:No|Number|#)?\s*[:\-]?\s*([A-Za-z0-9]+)", text, re.I)
    if m_roll:
        add_if_found(fields, "Roll Number", m_roll.group(1).upper())

    # 5. District
    district = extract_district(text)
    add_if_found(fields, "District", district)

    # 6. Date / DOB
    m_dob = re.search(r"(?:DOB|Date\s+of\s+Birth)\s*[:\-/]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", text, re.I)
    if m_dob:
        add_if_found(fields, "Date of Birth", m_dob.group(1).replace("/", "-"))

    # 7. Issue / Document Date
    issue_date = extract_issue_date(text)
    add_if_found(fields, "Issue Date", issue_date)

    return fields
