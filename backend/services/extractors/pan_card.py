"""Field extraction rules specific to Indian Permanent Account Number (PAN) cards.

Enhanced:
- Explicit label-based extraction (Name:, Father's Name:)
- Layout-based fallback (lines above DOB)
- Strict NON_PAN_WORDS filtering
"""

import re
from typing import Dict

from .common import (
    add_if_found,
    clean_person_name,
    extract_pan_number,
    extract_valid_date,
    normalized_lines,
    validate_and_clean_citizen_name,
)

NON_PAN_WORDS = {
    "income", "tax", "department", "govt", "government", "india",
    "permanent", "account", "number", "card", "signature", "father",
    "name", "date", "birth", "incometax", "holder", "pan",
}


def extract_fields(ocr_text: str) -> Dict[str, str]:
    """Extract standard PAN card fields (PAN number, holder name, father name, DOB)."""
    text = normalized_lines(ocr_text)
    fields: Dict[str, str] = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 1. Permanent Account Number (PAN)
    pan = extract_pan_number(text)
    add_if_found(fields, "Certificate Number", pan)
    add_if_found(fields, "PAN Number", pan)

    # 2. Date of Birth – explicit label first
    m_dob_label = re.search(
        r"(?:Date\s+of\s+Birth|DOB|Date\s+of\s+Issue)\s*[:\-/]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        text,
        re.I,
    )
    if m_dob_label:
        dob_raw = m_dob_label.group(1)
        parts = re.split(r"[/-]", dob_raw)
        if len(parts) == 3 and 1950 <= int(parts[2]) <= 2030:
            add_if_found(fields, "Date of Birth", f"{parts[0].zfill(2)}-{parts[1].zfill(2)}-{parts[2]}")
    else:
        dob_val = extract_valid_date(text)
        add_if_found(fields, "Date of Birth", dob_val)

    # 3. Citizen Name & Father Name
    citizen_name = None
    father_name = None

    # Strategy 1: Explicit "Name:" label
    m_name = re.search(
        r"^\s*(?:Name|Card\s+Holder'?s?\s*Name)\s*[:\-]?\s*([A-Za-z\s\.]{2,40}?)(?:\s*(?:\n|$))",
        text,
        re.I | re.M,
    )
    if m_name:
        cand = clean_person_name(m_name.group(1))
        if len(cand) >= 2 and not any(w in cand.lower() for w in NON_PAN_WORDS):
            citizen_name = cand

    # Strategy 2: Explicit "Father's Name:" label
    m_father = re.search(
        r"^\s*Father'?s?\s*(?:Name)?\s*[:\-]?\s*([A-Za-z\s\.]{2,40}?)(?:\s*(?:\n|$))",
        text,
        re.I | re.M,
    )
    if m_father:
        cand_f = clean_person_name(m_father.group(1))
        if len(cand_f) >= 2 and not any(w in cand_f.lower() for w in NON_PAN_WORDS):
            father_name = cand_f

    # Strategy 3: Layout fallback – lines above DOB line
    if not citizen_name or not father_name:
        for idx, line in enumerate(lines):
            if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b", line) or re.search(r"\bDOB\b", line, re.I):
                candidate_lines = []
                for prev_idx in range(idx - 1, max(-1, idx - 5), -1):
                    cand = clean_person_name(lines[prev_idx])
                    if (
                        len(cand) >= 2
                        and not any(w in cand.lower() for w in NON_PAN_WORDS)
                        and not re.search(r"\d", lines[prev_idx])
                        and len(lines[prev_idx]) <= 50
                    ):
                        candidate_lines.insert(0, cand)
                if len(candidate_lines) >= 2:
                    if not citizen_name:
                        citizen_name = candidate_lines[0]
                    if not father_name:
                        father_name = candidate_lines[1]
                elif len(candidate_lines) == 1 and not citizen_name:
                    citizen_name = candidate_lines[0]
                break

    # Validate names
    citizen_name = validate_and_clean_citizen_name(citizen_name)
    father_name = validate_and_clean_citizen_name(father_name)

    # Ensure they're different
    if citizen_name and father_name and citizen_name.lower() == father_name.lower():
        father_name = None

    add_if_found(fields, "Citizen Name", citizen_name)
    add_if_found(fields, "Father / Guardian", father_name)

    return fields
