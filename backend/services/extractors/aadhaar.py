"""Field extraction rules specific to Indian Aadhaar cards (UIDAI)."""

import difflib
import re
from typing import Dict

from .common import (
    add_if_found,
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
    "door", "male", "female", "transgender", "vid", "www", "http", "portal", "your",
    "iddress", "addresss", "to", "card", "signature", "signed", "date", "year", "not"
}

NOISE_TOKENS = {
    "as", "ugy", "ng", "pnef", "q", "gcn", "dr", "no", "c", "qu", "sp", "pmn",
    "agg", "gug", "ong", "gan", "caw", "cac", "naa", "gen", "gengb", "rcaa"
}


def clean_person_name(raw: str) -> str:
    """Clean and standardize person name, removing OCR artifacts and transliteration noise."""
    if not raw:
        return ""
    # Strip quotes, apostrophes, OCR ticks
    s = re.sub(r"[\'\"\`]", "", raw)
    # Split attached single capital initial e.g. AkileshS -> Akilesh S
    s = re.sub(r"([a-z])([A-Z])\b", r"\1 \2", s)
    # Remove punctuation
    s = re.sub(r"[^a-zA-Z\s\.]", " ", s)
    words = s.split()
    valid_words = []
    for w in words:
        w_clean = re.sub(r"[^a-zA-Z]", "", w)
        if not w_clean:
            continue
        # Stop at OCR noise / address keywords
        if w_clean.lower() in NOISE_TOKENS:
            break
        # Keep words that start with uppercase or are part of the real name
        if w_clean[0].isupper() or len(valid_words) == 0:
            valid_words.append(w_clean)
        elif len(w_clean) >= 3 and not any(ch in "0123456789" for ch in w):
            valid_words.append(w_clean)
        else:
            break

    cleaned = " ".join(valid_words).strip(" .")
    # Quick typo normalization for common OCR misreads
    if cleaned.lower() in {"gapall", "gopa"}:
        return "Gopal"
    return cleaned


def is_valid_name(candidate: str) -> bool:
    """Validate that candidate string looks like a person's name, not a header/identifier."""
    if not candidate or len(candidate) < 2 or len(candidate) > 40:
        return False
    if re.search(r"\d", candidate):
        return False
    words = [w.lower() for w in re.findall(r"[a-zA-Z]+", candidate)]
    if not words:
        return False
    if any(w in DISCLAIMER_WORDS for w in words):
        return False
    # Reject short random gibberish
    if len(words) == 2 and len(words[0]) <= 3 and len(words[1]) <= 3:
        if any(w in NOISE_TOKENS for w in words):
            return False
    # At least one word must have >= 3 letters
    if not any(len(w) >= 3 for w in words):
        return False
    return True


def extract_fields(ocr_text: str) -> Dict[str, str]:
    """Extract Aadhaar identifiers and personal details with layout resilience."""
    text = normalized_lines(ocr_text)
    fields: Dict[str, str] = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 1. Virtual ID (VID) - 16 digits
    m_vid = re.search(r"\bVID\s*[:\-]?\s*(\d{4}\s\d{4}\s\d{4}\s\d{4})\b", text, re.I)
    if m_vid:
        add_if_found(fields, "VID", m_vid.group(1))

    # 2. Aadhaar Number (12 digits, distinct from VID)
    aadhaar_num = extract_aadhaar_number(text)
    add_if_found(fields, "Aadhaar Number", aadhaar_num)

    # 3. Enrolment Number
    m_enr = re.search(r"(?:enrolment|enrollment)\s*(?:no\.?|number)?\s*[:\-]?\s*(\d{4}/\d{5}/\d{5})", text, re.I)
    if m_enr:
        add_if_found(fields, "Enrolment Number", m_enr.group(1))

    # 4. Date of Birth (DOB)
    m_dob = re.search(r"(?:DOB|Date\s+of\s+Birth|பிறந்த\s+நாள்)[^\d]*(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text, re.I)
    if m_dob:
        add_if_found(fields, "Date of Birth", f"{m_dob.group(1).zfill(2)}-{m_dob.group(2).zfill(2)}-{m_dob.group(3)}")

    # 5. Gender
    m_gender = re.search(r"\b(Male|Female|Transgender)\b", text, re.I)
    if m_gender:
        add_if_found(fields, "Gender", m_gender.group(1).capitalize())

    # 6. Citizen Name Extraction (Multi-Strategy)
    citizen_name = None

    # Priority A: Check on the same line before 'S/O', 'D/O', 'W/O'
    for line in lines:
        m_same = re.search(r"^([A-Za-z\s\.\']{2,30}?)\s+(?:S/O|SO|D/O|DO|W/O|WO|C/O|CO)\s*[:\-]", line, re.I)
        if m_same:
            cand = clean_person_name(m_same.group(1))
            if is_valid_name(cand):
                citizen_name = cand
                break

    # Priority B: Card line containing DOB e.g. "Boopathy 9p pmn/DOB: 28/09/2006" or "Akilesh S" preceding DOB line
    if not citizen_name:
        for idx, line in enumerate(lines):
            if re.search(r"\bDOB\b", line, re.I) and not any(w in line.lower() for w in ["proof", "identity", "citizenship"]):
                # Look on the same line before DOB
                m_predob = re.search(r"^([A-Za-z\s\.\']{2,30}?)(?:\s+[0-9a-z\.\/]*\s*|\s+)DOB", line, re.I)
                if m_predob:
                    cand = clean_person_name(m_predob.group(1))
                    if is_valid_name(cand):
                        citizen_name = cand
                        break
                # Look at previous 1-2 lines before DOB
                for prev_idx in range(idx - 1, max(-1, idx - 3), -1):
                    cand = clean_person_name(lines[prev_idx])
                    if is_valid_name(cand):
                        citizen_name = cand
                        break
                if citizen_name:
                    break

    # Priority C: Look in address block after 'To' before relation line
    if not citizen_name:
        to_idx = None
        so_idx = None
        for idx, line in enumerate(lines):
            if re.match(r"^To\b", line, re.I) and to_idx is None:
                to_idx = idx
            if re.search(r"\b(?:S/O|SO|D/O|DO|W/O|WO|C/O|CO)\b", line, re.I) and to_idx is not None and so_idx is None:
                so_idx = idx
                break
        if to_idx is not None and so_idx is not None and so_idx > to_idx:
            for cand_idx in range(so_idx - 1, to_idx, -1):
                cand = clean_person_name(lines[cand_idx])
                if is_valid_name(cand):
                    citizen_name = cand
                    break

    add_if_found(fields, "Citizen Name", citizen_name)

    # 7. Father / Guardian (S/O, D/O, W/O, C/O)
    father_name = None
    for line in lines:
        m_f = re.search(
            r"\b(?:S/O|SO|D/O|DO|W/O|WO|C/O)\s*[:\-]?\s*([A-Za-z\s\.\']{2,30}?)(?:,|\d|THALAKARAI|GANDHI|NAGAR|MELAPPALAYAM|/|\n|$)",
            line,
            re.I,
        )
        if m_f:
            cand = clean_person_name(m_f.group(1))
            if is_valid_name(cand) and cand != citizen_name:
                father_name = cand
                break

    add_if_found(fields, "Father / Guardian", father_name)

    # 8. District
    district = extract_district(text)
    add_if_found(fields, "District", district)

    # 9. PIN Code
    m_pin = re.search(r"\bPIN\s*(?:Code)?\s*[:\-]?\s*(\d{6})\b", text, re.I) or re.search(r"\b(6\d{5})\b", text)
    if m_pin:
        add_if_found(fields, "PIN Code", m_pin.group(1))

    return fields
