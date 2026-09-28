"""Field extraction rules specific to Indian Birth Certificates."""

import re
from typing import Dict

from .common import (
    add_if_found,
    clean_person_name,
    extract_certificate_number,
    extract_district,
    extract_issue_date,
    normalized_lines,
)


def extract_fields(ocr_text: str) -> Dict[str, str]:
    """Extract child, registration, location, and issue details."""
    text = normalized_lines(ocr_text)
    fields: Dict[str, str] = {}

    # 1. Certificate / Registration Number
    cert_no = extract_certificate_number(text)
    add_if_found(fields, "Certificate Number", cert_no)

    # 2. Child Name
    m_name = re.search(r"(?:Child\s+Name|Name\s+of\s+Child|Name)\s*[:\-]?\s*([A-Za-z\s\.]+?)(?=\s*(?:\n|Date|DOB|Father|Mother|District|$))", text, re.I)
    if m_name:
        add_if_found(fields, "Citizen Name", clean_person_name(m_name.group(1)))

    # 3. Date of Birth
    m_dob = re.search(r"(?:Date\s+of\s+Birth|DOB|பிறந்த\s+நாள்)\s*[:\-/]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", text, re.I)
    if m_dob:
        add_if_found(fields, "Date of Birth", m_dob.group(1).replace("/", "-"))

    # 4. Father's Name
    m_father = re.search(r"(?:Father'?s?\s+Name|Father)\s*[:\-]?\s*([A-Za-z\s\.]+?)(?:,|\n|$)", text, re.I)
    if m_father:
        add_if_found(fields, "Father's Name", clean_person_name(m_father.group(1)))

    # 5. Mother's Name
    m_mother = re.search(r"(?:Mother'?s?\s+Name|Mother)\s*[:\-]?\s*([A-Za-z\s\.]+?)(?:,|\n|$)", text, re.I)
    if m_mother:
        add_if_found(fields, "Mother's Name", clean_person_name(m_mother.group(1)))

    # 6. Place of Birth
    m_place = re.search(r"Place\s+of\s+Birth\s*[:\-]?\s*([A-Za-z0-9\s,]+?)(?:\.|\n|$)", text, re.I)
    if m_place:
        add_if_found(fields, "Place of Birth", m_place.group(1).strip())

    # 7. District
    district = extract_district(text)
    add_if_found(fields, "District", district)

    # 8. Issue Date
    issue_date = extract_issue_date(text)
    add_if_found(fields, "Issue Date", issue_date)

    return fields
