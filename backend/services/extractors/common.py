"""Reusable extraction helpers for government document OCR processing."""

import difflib
import re
from typing import Dict, List, Optional


TN_DISTRICTS = [
    "Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore",
    "Dharmapuri", "Dindigul", "Erode", "Kallakurichi", "Kanchipuram",
    "Kanyakumari", "Karur", "Krishnagiri", "Madurai", "Mayiladuthurai",
    "Nagapattinam", "Namakkal", "Nilgiris", "Perambalur", "Pudukkottai",
    "Ramanathapuram", "Ranipet", "Salem", "Sivaganga", "Tenkasi",
    "Thanjavur", "Theni", "Thoothukudi", "Tiruchirappalli", "Tirunelveli",
    "Tirupathur", "Tiruppur", "Tiruvallur", "Tiruvannamalai", "Tiruvarur",
    "Vellore", "Viluppuram", "Virudhunagar",
]


def normalized_lines(text: str) -> str:
    """Clean extra spaces while retaining readable line breaks."""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_district(text: str) -> Optional[str]:
    """Extract district name using Tamil Nadu district lookup and fuzzy OCR tolerance."""
    # 1. Look for explicit label: District : Tiruppur or மாவட்டம் : Tiruppur
    m = re.search(r"(?:District|மாவட்டம்)\s*[:\-]?\s*([A-Za-z]+)", text, re.I)
    if m:
        candidate = m.group(1).capitalize()
        close = difflib.get_close_matches(candidate, TN_DISTRICTS, n=1, cutoff=0.7)
        if close:
            return close[0]

    # 2. Look for pattern "... [DistrictName] District" (e.g. Ticuppur District -> Tiruppur)
    m2 = re.search(r"\b([A-Za-z]{4,15})\s+District\b", text, re.I)
    if m2:
        candidate = m2.group(1).capitalize()
        close = difflib.get_close_matches(candidate, TN_DISTRICTS, n=1, cutoff=0.6)
        if close:
            return close[0]
        if candidate.lower() not in {"the", "and", "town", "taluk", "village"}:
            return candidate

    # 3. Check for any known Tamil Nadu district in text
    for d in TN_DISTRICTS:
        if re.search(r"\b" + re.escape(d) + r"\b", text, re.I):
            return d

    # 4. Fuzzy search across full words in text for district names
    words = re.findall(r"\b[A-Za-z]{4,15}\b", text)
    for word in words:
        close = difflib.get_close_matches(word.capitalize(), TN_DISTRICTS, n=1, cutoff=0.85)
        if close:
            return close[0]

    return None


def extract_certificate_number(text: str) -> Optional[str]:
    """Extract certificate identifier matching state portal standards (e.g. TN-4202307056380, TN-GCC-BC-2026-3391)."""
    # 1. State certificate format: TN- followed by alphanumeric characters and hyphens
    tn_match = re.search(r"\b(TN-[A-Z0-9\-]{8,24})\b", text, re.I)
    if tn_match:
        return tn_match.group(1).upper().strip("-")

    # Contiguous TN followed by digits
    tn_match2 = re.search(r"\b(TN[0-9]{10,18})\b", text, re.I)
    if tn_match2:
        return f"TN-{tn_match2.group(1)[2:]}"

    # 2. Keyed in label: Certificate No: ... or Certificate Number
    m = re.search(
        r"(?:Certificate\s*(?:Number|No\.?)|சான்றிதழ்\s*எண்|unique\s*certificate\s*number)[^\w\n]*([A-Z0-9\-/]+)",
        text,
        re.I,
    )
    if m and len(m.group(1)) >= 6:
        val = m.group(1).strip()
        if val.upper().startswith("TN") and not val.upper().startswith("TN-"):
            val = f"TN-{val[2:]}"
        return val

    # 3. Generic Cert / Reg number label
    m2 = re.search(r"(?:Cert(?:ificate)?|Reg(?:istration)?)\s*(?:No\.?|#)\s*[:\-]?\s*([A-Z0-9\-/]+)", text, re.I)
    if m2 and len(m2.group(1)) >= 6:
        return m2.group(1).strip()

    return None


def extract_aadhaar_number(text: str) -> Optional[str]:
    """Extract a valid 12-digit Indian Aadhaar number."""
    m = re.search(r"\b([2-9]\d{3}\s\d{4}\s\d{4})\b", text)
    if m:
        return m.group(1)
    m2 = re.search(r"\b([2-9]\d{11})\b", text)
    if m2:
        val = m2.group(1)
        return f"{val[:4]} {val[4:8]} {val[8:]}"
    return None


def extract_valid_date(text: str) -> Optional[str]:
    """Extract valid calendar date between 1950 and 2030, filtering OCR year typos."""
    # First check digital signature date: Date: 11/07/2023
    m_sig = re.search(r"(?:Date|நாள்)\s*[:\-]?\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text, re.I)
    if m_sig:
        d, m, y = m_sig.groups()
        if 1950 <= int(y) <= 2030 and 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            return f"{d.zfill(2)}-{m.zfill(2)}-{y}"

    # Search all dates in text
    dates = re.findall(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    valid_dates = []
    for d, m, y in dates:
        if 1950 <= int(y) <= 2030 and 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            valid_dates.append(f"{d.zfill(2)}-{m.zfill(2)}-{y}")

    return valid_dates[0] if valid_dates else None


# Alias for backward compatibility
extract_issue_date = extract_valid_date


def clean_person_name(name_str: str) -> str:
    """Clean person name from honorifics, OCR noise, and trailing clauses."""
    cleaned = re.sub(r"^(?:This is to certify that|certify that|Thiru|Tmt|Selvi|Mr\.?|Mrs\.?|Ms\.?|Shri|Smt\.?)\s+", "", name_str.strip(), flags=re.I)
    cleaned = re.sub(r"\s+(?:son|daughter|wife|s/o|d/o|w/o|residing|rcsiding|at Door|Door|Village|Town|Taluk|District).*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"[^\w\s\.]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def add_if_found(fields: Dict[str, str], field_name: str, value: Optional[str]) -> None:
    """Add field to result dictionary if value is present and valid."""
    if value and str(value).strip():
        fields[field_name] = str(value).strip()
