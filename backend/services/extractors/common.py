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
        close = difflib.get_close_matches(candidate, TN_DISTRICTS, n=1, cutoff=0.65)
        if close:
            return close[0]

    # 3. Check for direct match of any known Tamil Nadu district in text
    for d in TN_DISTRICTS:
        if re.search(r"\b" + re.escape(d) + r"\b", text, re.I):
            return d

    # 5. Infer district from taluk if present (e.g. Avinashi Taluk -> Tiruppur)
    m_taluk = re.search(r"\b([A-Za-z]{4,15})\s+Taluk\b", text, re.I)
    if m_taluk:
        taluk_cand = m_taluk.group(1).lower()
        if taluk_cand in TALUK_TO_DISTRICT_MAP:
            return TALUK_TO_DISTRICT_MAP[taluk_cand]

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
    """Extract a valid 12-digit Indian Aadhaar number, avoiding 16-digit VIDs."""
    # Priority 1: Line following 'Your Aadhaar No'
    m_lbl = re.search(r"Your\s+Aadhaar\s+No[^\d\n]*\n\s*([2-9]\d{3}\s?\d{4}\s?\d{4})", text, re.I)
    if m_lbl:
        clean = re.sub(r"\s+", "", m_lbl.group(1))
        if len(clean) == 12:
            return f"{clean[:4]} {clean[4:8]} {clean[8:]}"

    # Priority 2: 12-digit formatted number NOT preceded by VID and NOT part of 16 digits
    matches = re.findall(r"(?<!\d)(?<!VID\s)(?<!VID:\s)\b([2-9]\d{3}\s\d{4}\s\d{4})(?!\s\d{4})\b", text)
    if matches:
        return matches[0]

    # Priority 3: Contiguous 12 digits NOT part of VID
    vid_match = re.search(r"\bVID\s*[:\-]?\s*(\d{4}\s\d{4}\s\d{4}\s\d{4})\b", text, re.I)
    vid_digits = vid_match.group(1).replace(" ", "") if vid_match else ""

    matches2 = re.findall(r"(?<!\d)([2-9]\d{11})(?!\d)", text)
    for m in matches2:
        if not vid_digits.startswith(m):
            return f"{m[:4]} {m[4:8]} {m[8:]}"

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


# Comprehensive Taluk to District mapping for Tamil Nadu
TALUK_TO_DISTRICT_MAP: Dict[str, str] = {
    # Tiruppur
    "avinashi": "Tiruppur", "tiruppur": "Tiruppur", "palladam": "Tiruppur",
    "dharapuram": "Tiruppur", "kangeyam": "Tiruppur", "uthukuli": "Tiruppur",
    "madathukulam": "Tiruppur", "udumalpet": "Tiruppur",
    # Salem
    "salem": "Salem", "attur": "Salem", "omalur": "Salem", "mettur": "Salem",
    "sankari": "Salem", "edappadi": "Salem", "gangavalli": "Salem", "valapady": "Salem",
    "yercaud": "Salem", "kadayampatti": "Salem", "pethanaickenpalayam": "Salem",
    # Coimbatore
    "coimbatore": "Coimbatore", "pollachi": "Coimbatore", "mettupalayam": "Coimbatore",
    "sulur": "Coimbatore", "annur": "Coimbatore", "kinathukadavu": "Coimbatore", "valparai": "Coimbatore",
    # Chennai & Tiruvallur & Chengalpattu
    "egmore": "Chennai", "mylapore": "Chennai", "guindy": "Chennai", "tondiarpet": "Chennai",
    "velachery": "Chennai", "mambalam": "Chennai", "ambattur": "Tiruvallur", "avadi": "Tiruvallur",
    "poonamallee": "Tiruvallur", "ponneri": "Tiruvallur", "gummidipoondi": "Tiruvallur",
    "tiruttani": "Tiruvallur", "tambaram": "Chengalpattu", "pallavaram": "Chengalpattu",
    "vandalur": "Chengalpattu", "chengalpattu": "Chengalpattu", "maduranthakam": "Chengalpattu",
    # Erode
    "erode": "Erode", "perundurai": "Erode", "bhavani": "Erode", "gobichettipalayam": "Erode",
    "sathyamangalam": "Erode", "anthiyur": "Erode", "kodumudi": "Erode", "modakkurichi": "Erode",
    # Madurai
    "madurai": "Madurai", "melur": "Madurai", "thirumangalam": "Madurai", "usilampatti": "Madurai",
    "vadipatti": "Madurai", "peraiyur": "Madurai",
    # Trichy
    "tiruchirappalli": "Tiruchirappalli", "srirangam": "Tiruchirappalli", "manapparai": "Tiruchirappalli",
    "musiri": "Tiruchirappalli", "thuraiyur": "Tiruchirappalli", "lalgudi": "Tiruchirappalli",
    # Dindigul
    "dindigul": "Dindigul", "palani": "Dindigul", "kodaikanal": "Dindigul", "nilakottai": "Dindigul",
    "oddanchatram": "Dindigul", "natham": "Dindigul", "vedasandur": "Dindigul",
    # Namakkal
    "namakkal": "Namakkal", "rasipuram": "Namakkal", "tiruchengode": "Namakkal", "paramathi": "Namakkal",
    # Karur
    "karur": "Karur", "kulithalai": "Karur", "aravakurichi": "Karur",
    # Dharmapuri & Krishnagiri
    "dharmapuri": "Dharmapuri", "harur": "Dharmapuri", "palacode": "Dharmapuri", "pennagaram": "Dharmapuri",
    "krishnagiri": "Krishnagiri", "hosur": "Krishnagiri", "denkanikottai": "Krishnagiri",
    # Thanjavur & Tiruvarur & Nagapattinam & Mayiladuthurai
    "thanjavur": "Thanjavur", "kumbakonam": "Thanjavur", "pattukkottai": "Thanjavur",
    "tiruvarur": "Tiruvarur", "mannargudi": "Tiruvarur", "nagapattinam": "Nagapattinam",
    "mayiladuthurai": "Mayiladuthurai", "sirkazhi": "Mayiladuthurai",
    # Vellore, Tirupathur, Ranipet
    "vellore": "Vellore", "katpadi": "Vellore", "gudiyatham": "Vellore",
    "tirupathur": "Tirupathur", "vaniyambadi": "Tirupathur", "ambur": "Tirupathur",
    "ranipet": "Ranipet", "walajah": "Ranipet", "arakkonam": "Ranipet", "arcot": "Ranipet",
    # Tiruvannamalai, Viluppuram, Cuddalore, Kallakurichi
    "tiruvannamalai": "Tiruvannamalai", "arani": "Tiruvannamalai", "cheyyar": "Tiruvannamalai",
    "viluppuram": "Viluppuram", "tindivanam": "Viluppuram", "gingee": "Viluppuram",
    "cuddalore": "Cuddalore", "chidambaram": "Cuddalore", "panruti": "Cuddalore", "vridhachalam": "Cuddalore",
    "kallakurichi": "Kallakurichi", "sankarapuram": "Kallakurichi", "ulundurpet": "Kallakurichi",
    # South: Tirunelveli, Tenkasi, Thoothukudi, Kanyakumari
    "tirunelveli": "Tirunelveli", "palayamkottai": "Tirunelveli", "ambasamudram": "Tirunelveli",
    "tenkasi": "Tenkasi", "sankarankovil": "Tenkasi", "kadayanallur": "Tenkasi",
    "thoothukudi": "Thoothukudi", "tiruchendur": "Thoothukudi", "kovilpatti": "Thoothukudi",
    "kanyakumari": "Kanyakumari", "agastheeswaram": "Kanyakumari", "kalkulam": "Kanyakumari",
}

DISALLOWED_NAME_WORDS = {
    "government", "department", "certificate", "revenue", "income", "tamil", "nadu",
    "india", "signature", "date", "issue", "taluk", "district", "village", "door",
    "permanent", "account", "licence", "driving", "transport", "corporation", "greater",
    "chennai", "public", "health", "authority", "unique", "identification", "community",
    "caste", "annual", "rupees", "thousand", "hundred", "father", "mother", "child",
    "registration", "birth", "death", "valid", "validity", "union", "state", "form",
    "male", "female", "transgender", "gender", "address", "holder", "card",
}


def clean_person_name(name_str: str) -> str:
    """Clean person name from honorifics, OCR noise, and trailing clauses."""
    cleaned = re.sub(
        r"^(?:This is to certify that|certify that|Thiru|Tmt|Selvan|Selvi|Mr\.?|Mrs\.?|Ms\.?|Shri|Smt\.?|Dr\.?)\s+",
        "",
        name_str.strip(),
        flags=re.I,
    )
    cleaned = re.sub(
        r"\s+(?:son|daughter|wife|s/o|d/o|w/o|residing|rcsiding|at Door|Door|Village|Town|Taluk|District).*",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"[^\w\s\.]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def validate_and_clean_citizen_name(name_str: Optional[str]) -> Optional[str]:
    """Strictly validate and return clean person name, eliminating headers and keywords."""
    if not name_str or not str(name_str).strip():
        return None
    cleaned = clean_person_name(str(name_str))
    if len(cleaned) < 2 or len(cleaned) > 60:
        return None
    # Check if candidate consists mostly of invalid boilerplate words
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", cleaned)]
    if not words:
        return None
    if any(w in DISALLOWED_NAME_WORDS for w in words):
        return None
    # Check that at least 60% of characters are alphabetic
    alpha_count = sum(1 for c in cleaned if c.isalpha())
    if alpha_count / max(1, len(cleaned)) < 0.6:
        return None
    return cleaned


def extract_pan_number(text: str) -> Optional[str]:
    """Extract standard Indian Permanent Account Number (5 letters, 4 digits, 1 letter)."""
    # 1. Direct standard regex: 5 uppercase letters, 4 digits, 1 letter
    m = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text)
    if m:
        return m.group(1).upper()
    # 2. Preceded by PAN label
    m_lbl = re.search(r"(?:PAN|Permanent\s+Account\s+Number)[^\w\n]*([A-Z0-9]{10})\b", text, re.I)
    if m_lbl:
        val = m_lbl.group(1).upper()
        if re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", val):
            return val
    return None


def extract_driving_licence_number(text: str) -> Optional[str]:
    """Extract Indian Driving Licence number across state formats."""
    # Pattern 1: DL-1420110012345 or TN38 20110012345 or TN3820110012345
    m1 = re.search(r"\b([A-Z]{2}[- ]?\d{2}[- ]?\d{4}[- ]?\d{7})\b", text, re.I)
    if m1:
        return re.sub(r"\s+", " ", m1.group(1)).strip().upper()
    # Pattern 2: TN-01-2015-0001234 or TN0120150001234
    m2 = re.search(r"\b([A-Z]{2}[0-9]{2}\s?[0-9]{11})\b", text, re.I)
    if m2:
        return m2.group(1).upper()
    # Pattern 3: Keyed after DL No / Licence No
    m3 = re.search(r"(?:DL\s*No\.?|Licence\s*No\.?|License\s*No\.?)[^\w\n]*([A-Z0-9\-\s/]{8,20})", text, re.I)
    if m3:
        val = m3.group(1).strip().upper()
        if len(val) >= 8 and any(c.isdigit() for c in val):
            return val
    return None


def add_if_found(fields: Dict[str, str], field_name: str, value: Optional[str]) -> None:
    """Add field to result dictionary if value is present and valid."""
    if value and str(value).strip():
        fields[field_name] = str(value).strip()

