"""Field extraction rules specific to Indian Aadhaar cards (UIDAI)."""

import re
from typing import Dict

from .common import (
    add_if_found,
    clean_person_name,
    extract_aadhaar_number,
    extract_district,
    normalized_lines,
)

DISCLAIMER_WORDS = {
    "proof", "identity", "citizenship", "birth", "dob", "state", "tamil", "nadu",
    "address", "pin", "code", "mobile", "help", "uidai", "download", "unique",
    "authority", "india", "government", "aadhaar", "information", "letter", "scanning",
    "scanner", "regulations", "submitted", "verified", "holder", "online", "secure",
    "update", "updated", "benefit", "service", "services", "lock", "unlock", "biometric",
    "biometrics", "consent", "seeking", "entity", "entities", "valid", "validity",
    "enrolment", "enrollment", "father", "husband", "mother", "sub", "district", "dist",
    "taluk", "village", "town", "road", "street", "nagar", "colony", "post", "po", "vtc",
    "door", "male", "female", "transgender", "vid", "www", "http", "portal", "your"
}


def is_valid_name(candidate: str) -> bool:
    """Validate that candidate string looks like a person's name, not a header/identifier."""
    if not candidate or len(candidate) < 2 or len(candidate) > 40:
        return False
    # Reject lines containing digits
    if re.search(r"\d", candidate):
        return False
    words = re.findall(r"[a-zA-Z]+", candidate.lower())
    if not words:
        return False
    # If any word matches reserved/disclaimer keywords, reject
    if any(w in DISCLAIMER_WORDS for w in words):
        return False
    return True


def extract_fields(ocr_text: str) -> Dict[str, str]:
    """Extract Aadhaar identifiers and personal details with layout resilience."""
    text = normalized_lines(ocr_text)
    fields: Dict[str, str] = {}

    # 1. Aadhaar Number (XXXX XXXX XXXX)
    aadhaar_num = extract_aadhaar_number(text)
    add_if_found(fields, "Aadhaar Number", aadhaar_num)

    # 2. Virtual ID (VID)
    m_vid = re.search(r"\bVID\s*[:\-]?\s*(\d{4}\s\d{4}\s\d{4}\s\d{4})\b", text, re.I)
    if m_vid:
        add_if_found(fields, "VID", m_vid.group(1))

    # 3. Enrolment Number
    m_enr = re.search(r"(?:enrolment|enrollment)\s*(?:no\.?|number)?\s*[:\-]?\s*(\d{4}/\d{5}/\d{5})", text, re.I)
    if m_enr:
        add_if_found(fields, "Enrolment Number", m_enr.group(1))

    # 4. Date of Birth (DOB) - handles standard or joined OCR (e.g. 9pDOB2809/2006)
    m_dob = re.search(r"DOB[^\d]*(\d{1,2})[/-]?(\d{1,2})[/-](\d{4})", text, re.I)
    if not m_dob:
        m_dob = re.search(r"(?:DOB|Date\s+of\s+Birth|பிறந்த\s+நாள்)\s*[:\-/]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", text, re.I)
        if m_dob:
            add_if_found(fields, "Date of Birth", m_dob.group(1).replace("/", "-"))
    else:
        add_if_found(fields, "Date of Birth", f"{m_dob.group(1).zfill(2)}-{m_dob.group(2).zfill(2)}-{m_dob.group(3)}")

    # 5. Gender
    m_gender = re.search(r"\b(Male|Female|Transgender)\b", text, re.I)
    if m_gender:
        add_if_found(fields, "Gender", m_gender.group(1).capitalize())

    # 6. Citizen Name Extraction (Multi-Strategy)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    name = None

    # Strategy 1: Look between 'To' and Guardian/Relation ('S/O', 'D/O', 'W/O', 'C/O')
    for i, line in enumerate(lines):
        if re.search(r"\b(?:S/O|SO|D/O|DO|W/O|WO|C/O|CO)\s*[:\-]", line, re.I):
            for j in range(i - 1, max(-1, i - 4), -1):
                candidate = clean_person_name(lines[j].strip(" ."))
                if is_valid_name(candidate):
                    name = candidate
                    break
            if name:
                break

    # Strategy 2: Preceding real DOB / Gender line (Aadhaar card layout)
    if not name:
        for i, line in enumerate(lines):
            is_dob_line = (re.search(r"\bDOB\b", line, re.I) or re.search(r"\b(?:Male|Female)\b", line, re.I)) and \
                          not any(w in line.lower() for w in ["proof", "identity", "citizenship"])
            if is_dob_line:
                for j in range(i - 1, max(-1, i - 4), -1):
                    candidate = clean_person_name(lines[j].strip(" ."))
                    if is_valid_name(candidate):
                        name = candidate
                        break
                if name:
                    break

    # Strategy 3: Lines after 'To'
    if not name:
        for i, line in enumerate(lines):
            if re.match(r"^To\b", line, re.I):
                for j in range(i + 1, min(len(lines), i + 4)):
                    candidate = clean_person_name(lines[j].strip(" ."))
                    if is_valid_name(candidate):
                        name = candidate
                        break
                if name:
                    break

    add_if_found(fields, "Citizen Name", name)

    # 7. Father / Guardian (S/O, D/O, W/O, C/O)
    m_guardian = re.search(r"(?:S/O|SO|D/O|DO|W/O|WO|Care\s+of|C/O|CO)\s*[:\-]?\s*([A-Za-z\s\.]+?)(?:,|\n|$)", text, re.I)
    if m_guardian:
        add_if_found(fields, "Father / Guardian", clean_person_name(m_guardian.group(1)))

    # 8. District
    district = extract_district(text)
    add_if_found(fields, "District", district)

    # 9. PIN Code
    m_pin = re.search(r"\bPIN\s*(?:Code)?\s*[:\-]?\s*(\d{6})\b", text, re.I) or re.search(r"\b(6\d{5})\b", text)
    if m_pin:
        add_if_found(fields, "PIN Code", m_pin.group(1))

    return fields
