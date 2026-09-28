"""Field extraction rules specific to Indian and Tamil Nadu Community Certificates."""

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
    """Extract structured fields from community / caste certificate OCR text."""
    text = normalized_lines(ocr_text)
    fields: Dict[str, str] = {}

    # 1. Certificate Number
    cert_no = extract_certificate_number(text)
    add_if_found(fields, "Certificate Number", cert_no)

    # 2. Citizen Name & Father / Guardian Name
    citizen_name = None
    father_name = None

    # Pattern A: Full Tamil Nadu certificate sentence with applicant and father:
    # "This is to certify that Selvan/Thiru/Selvi/Tmt [Applicant] son/daughter of Thiru [Father] residing at..."
    m_full = re.search(
        r"(?:certi[tf]y\s+that\s+)?(?:Selvan|Selvi|Thiru|Tmt|Thirumathi)\s+([A-Za-z\s\.]+?)\s+(?:son|daughter|wife|s/o|d/o|w/o)\s+(?:of\s+)?(?:Selvan|Selvi|Thiru|Tmt|Thirumathi)?\s*([A-Za-z\s\.]+?)(?=\s+(?:residing|Door|at|\d|,|\.))",
        text,
        re.I,
    )
    if m_full:
        cand_cit = clean_person_name(m_full.group(1))
        cand_fat = clean_person_name(m_full.group(2))
        if len(cand_cit) >= 2 and not any(w in cand_cit.lower() for w in ["state", "tamil", "nadu", "district", "village"]):
            citizen_name = cand_cit
        if len(cand_fat) >= 2 and not any(w in cand_fat.lower() for w in ["state", "tamil", "nadu", "district"]):
            father_name = cand_fat

    # Pattern B: Solo applicant name after honorific title
    if not citizen_name:
        m_cert = re.search(
            r"(?:certi[tf]y\s+that\s+)?(?:Selvan|Selvi|Thiru|Tmt|Thirumathi)\s+([A-Za-z\s\.]+?)(?=\s+(?:son|daughter|wife|s/o|d/o|w/o|belongs|residing|Door|\d|$))",
            text,
            re.I,
        )
        if m_cert:
            cand = clean_person_name(m_cert.group(1))
            if len(cand) >= 2 and not any(w in cand.lower() for w in ["state", "tamil", "nadu", "district", "village"]):
                citizen_name = cand

    # Pattern C: Explicit label e.g. "Applicant Name: Boopathy"
    if not citizen_name:
        m_name = re.search(r"(?:Applicant\s+Name|Name)\s*[:\-]?\s*([A-Za-z\s\.]+?)(?=\s*(?:\n|Community|Caste|Father|$))", text, re.I)
        if m_name:
            cand = clean_person_name(m_name.group(1))
            if cand.lower() not in ["certificate", "government", "tamil nadu"]:
                citizen_name = cand

    # Fallback for father name if not yet found
    if not father_name:
        m_fat = re.search(
            r"(?:son|daughter|wife|s/o|d/o|w/o)\s+(?:of\s+)?(?:Selvan|Selvi|Thiru|Tmt|Thirumathi)?\s*([A-Za-z\s\.]+?)(?=\s+(?:residing|Door|at|\d|,|\.|\n))",
            text,
            re.I,
        )
        if m_fat:
            father_name = clean_person_name(m_fat.group(1))

    add_if_found(fields, "Citizen Name", citizen_name)
    add_if_found(fields, "Father / Guardian", father_name)

    # 3. Community / Caste
    community = None
    # Strategy 1: "belongs to Kongu Vellalars Community, which is recognized as a Backward Class"
    m_comm = re.search(r"belongs\s+to\s+([A-Za-z0-9\s\-]+?)\s+Community", text, re.I)
    if m_comm:
        caste = m_comm.group(1).strip()
        m_cat = re.search(r"recognized\s+as\s+(?:a\s+)?([A-Za-z\s]+?)\s+as\s+per", text, re.I)
        if m_cat:
            community = f"{caste} ({m_cat.group(1).strip()})"
        else:
            community = caste
    else:
        m_direct = re.search(r"belongs\s+to\s+(?:the\s+|a\s+)?([A-Za-z0-9\s\-]+?\s*(?:Community|Class|Caste))", text, re.I)
        if m_direct:
            community = m_direct.group(1).strip()

    # Strategy 2: Explicit label "Community : Kongu Vellalar" (ignoring header "COMMUNITY CERTIFICATE")
    if not community:
        for match in re.finditer(r"(?:Community|Caste|சாதி)\s*[:\-]?\s*([A-Za-z0-9\s\-]+?)(?:,|\.|\n|$)", text, re.I):
            val = match.group(1).strip()
            if val.upper() not in ["CERTIFICATE", "COMMUNITY", "CASTE", "GOVERNMENT"]:
                community = val
                break

    add_if_found(fields, "Community", community)

    # 4. District
    district = extract_district(text)
    add_if_found(fields, "District", district)

    # 5. Issue Date
    issue_date = extract_issue_date(text)
    add_if_found(fields, "Issue Date", issue_date)

    return fields
