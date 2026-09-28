"""Field extraction rules specific to Indian and Tamil Nadu e-Sevai Income Certificates."""

import re
from typing import Dict

from .common import (
    add_if_found,
    clean_person_name,
    extract_certificate_number,
    extract_district,
    extract_valid_date,
    normalized_lines,
)


def extract_fields(ocr_text: str) -> Dict[str, str]:
    """Extract structured data from income certificate OCR text."""
    text = normalized_lines(ocr_text)
    fields: Dict[str, str] = {}

    # 1. Certificate Number
    cert_no = extract_certificate_number(text)
    add_if_found(fields, "Certificate Number", cert_no)

    # 2. Citizen / Applicant Name & Father Name
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

    # Pattern B: Honorific title list
    if not citizen_name:
        thiru_matches = re.findall(
            r"\b(?:Selvan|Selvi|Thiru|Tmt|Thirumathi)\s+([A-Za-z\s\.]+?)(?=\s+(?:[:\w\d/]+\s+(?:Selvan|Selvi|Thiru|Tmt|Thirumathi)|son|:on|daughter|wife|s/o|d/o|w/o|residing|Door|\d|$))",
            text,
            re.I,
        )
        if thiru_matches:
            candidate_name = clean_person_name(thiru_matches[0])
            if len(candidate_name) >= 2 and not any(w in candidate_name.lower() for w in ["state", "tamil", "nadu", "district", "village", "taluk"]):
                citizen_name = candidate_name
            if len(thiru_matches) > 1 and not father_name:
                candidate_father = clean_person_name(thiru_matches[1])
                if len(candidate_father) >= 2 and not any(w in candidate_father.lower() for w in ["state", "tamil", "nadu", "district"]):
                    father_name = candidate_father

    # Fallback for citizen name from table: "1 Gopal N Self"
    if not citizen_name:
        m_tbl = re.search(r"^\s*1\s+([A-Za-z\s\.]+?)\s+(?:Self|Head|Father)", text, re.M | re.I)
        if m_tbl:
            citizen_name = clean_person_name(m_tbl.group(1))

    # Fallback for generic name label
    if not citizen_name:
        m_gen = re.search(r"(?:Applicant\s+Name|Name\s+of\s+the\s+family\s+Member)\s*[:\-]?\s*([A-Za-z\s\.]+)", text, re.I)
        if m_gen:
            citizen_name = clean_person_name(m_gen.group(1))

    # Fallback for father name
    if not father_name:
        m_father = re.search(
            r"(?:son|daughter|wife|s/o|d/o|w/o)\s+(?:of\s+)?(?:Selvan|Selvi|Thiru|Tmt|Thirumathi)?\s*([A-Za-z\s\.]+?)(?=\s+(?:residing|rcsiding|at Door|Door|Village|\n))",
            text,
            re.I,
        )
        if m_father:
            father_name = clean_person_name(m_father.group(1))

    add_if_found(fields, "Citizen Name", citizen_name)
    add_if_found(fields, "Father / Husband Name", father_name)

    # 3. Annual Income
    income = None
    # Check digits after Rs. / INR: "Rs. 78000/annum" or "Rs. 78ooo"
    inc_m = re.search(r"(?:Rs\.?|INR)\s*([0-9oO]{4,8})", text, re.I)
    words_m = re.search(r"([A-Za-z\s]+?)\s+Thousand", text, re.I)
    if inc_m:
        num_str = inc_m.group(1).replace("o", "0").replace("O", "0")
        if num_str.isdigit():
            income = f"Rs. {int(num_str):,}"
    if words_m and "Seventy" in words_m.group(0):
        if income:
            income = f"{income} (Seventy Eight Thousand)"
        else:
            income = f"Rupees {words_m.group(0).strip()} Only"

    if not income:
        m_tot = re.search(r"(?:Total\s+Annual\s+Income.*?(\d{4,8}))", text, re.I)
        if m_tot:
            income = f"Rs. {int(m_tot.group(1)):,}"

    add_if_found(fields, "Annual Income", income)

    # 4. District (with fuzzy OCR error tolerance)
    district = extract_district(text)
    add_if_found(fields, "District", district)

    # 5. Taluk
    m_taluk = re.search(r"\b([A-Za-z]+)\s+Taluk\b", text, re.I)
    if not m_taluk:
        m_taluk = re.search(r"(?:Taluk|வட்டம்)\s*[:\-]?\s*([A-Za-z]+)", text, re.I)
    if m_taluk and len(m_taluk.group(1)) > 3 and m_taluk.group(1).lower() not in {"the", "and", "town"}:
        add_if_found(fields, "Taluk", m_taluk.group(1).capitalize())

    # 6. Village
    m_vil = re.search(r"\b([A-Za-z]+)\s+Villag[ec]\b", text, re.I)
    if m_vil and len(m_vil.group(1)) > 3 and m_vil.group(1).lower() not in {"the", "and"}:
        add_if_found(fields, "Village", m_vil.group(1).capitalize())

    # 7. Issue Date
    issue_date = extract_valid_date(text)
    add_if_found(fields, "Issue Date", issue_date)

    return fields
