"""OCR-Aware Smart Verification & Field Anomaly Detection Service for Module 11.

Identifies fields that may have been extracted incorrectly or contain uncertain OCR characters,
displays original text context alongside extracted values, and manages authorized corrections.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.database_service import get_connection

# Common suspicious characters resulting from OCR misreads
SUSPICIOUS_CHARS_REGEX = re.compile(r"[\?~*!|{}\\<>\^§]")

# Valid TN District list for validation
TN_DISTRICTS = {
    "Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore", "Dharmapuri",
    "Dindigul", "Erode", "Kallakurichi", "Kanchipuram", "Kanyakumari", "Karur",
    "Krishnagiri", "Madurai", "Mayiladuthurai", "Nagapattinam", "Namakkal",
    "Nilgiris", "Perambalur", "Pudukkottai", "Ramanathapuram", "Ranipet",
    "Salem", "Sivaganga", "Tenkasi", "Thanjavur", "Theni", "Thoothukudi",
    "Tiruchirappalli", "Tirunelveli", "Tirupathur", "Tiruppur", "Tiruvallur",
    "Tiruvannamalai", "Tiruvarur", "Vellore", "Viluppuram", "Virudhunagar",
}


@dataclass
class FieldVerificationInfo:
    """Detailed verification analysis for a single extracted field."""

    field_name: str
    extracted_value: Optional[str]
    is_flagged: bool
    confidence_score: float  # 0.0 to 1.0
    issue_reasons: List[str] = field(default_factory=list)
    suggested_value: Optional[str] = None
    ocr_context: str = ""


@dataclass
class DocumentVerificationReport:
    """Comprehensive verification analysis of all fields in a document."""

    document_id: int
    document_type: str
    overall_status: str  # 'needs_review', 'auto_verified', 'manually_verified'
    total_fields: int
    flagged_fields_count: int
    fields: Dict[str, FieldVerificationInfo] = field(default_factory=dict)
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None
    correction_history: List[Dict[str, Any]] = field(default_factory=list)


def ensure_verification_schema(database_path: str | Path) -> None:
    """Ensure database has verification columns and audit tables for Module 11."""
    with get_connection(database_path) as conn:
        # Check existing columns in government_documents
        cursor = conn.execute("PRAGMA table_info(government_documents)")
        existing_cols = {row["name"] for row in cursor.fetchall()}

        if "verification_status" not in existing_cols:
            conn.execute(
                "ALTER TABLE government_documents ADD COLUMN verification_status TEXT DEFAULT 'needs_review'"
            )
        if "verified_by" not in existing_cols:
            conn.execute(
                "ALTER TABLE government_documents ADD COLUMN verified_by TEXT"
            )
        if "verified_at" not in existing_cols:
            conn.execute(
                "ALTER TABLE government_documents ADD COLUMN verified_at TEXT"
            )
        if "field_corrections" not in existing_cols:
            conn.execute(
                "ALTER TABLE government_documents ADD COLUMN field_corrections TEXT DEFAULT '{}'"
            )
        if "verification_flags" not in existing_cols:
            conn.execute(
                "ALTER TABLE government_documents ADD COLUMN verification_flags TEXT DEFAULT '[]'"
            )

        # Verification Audit Logs Table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT NOT NULL,
                corrected_by TEXT NOT NULL,
                corrected_at TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (document_id) REFERENCES government_documents(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_doc_id ON verification_audit_logs(document_id)"
        )


def find_ocr_context_snippet(raw_ocr: str, value: Optional[str], window: int = 50) -> str:
    """Find surrounding text context where an extracted field appears in raw OCR text."""
    if not raw_ocr or not value or not str(value).strip():
        return ""

    val_str = str(value).strip()
    idx = raw_ocr.lower().find(val_str.lower())
    if idx == -1:
        # Try matching first word if multi-word
        first_token = val_str.split()[0] if val_str.split() else ""
        if first_token and len(first_token) >= 3:
            idx = raw_ocr.lower().find(first_token.lower())

    if idx != -1:
        start = max(0, idx - window)
        end = min(len(raw_ocr), idx + len(val_str) + window)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(raw_ocr) else ""
        snippet = raw_ocr[start:end].replace("\n", " ").strip()
        return f"{prefix}{snippet}{suffix}"

    return ""


def analyze_document_fields(
    doc_id: int,
    document_type: str,
    extracted_fields: Dict[str, Any],
    ocr_text: str,
    current_status: Optional[str] = None,
    verified_by: Optional[str] = None,
    verified_at: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> DocumentVerificationReport:
    """Run OCR-aware anomaly detection and confidence scoring across all extracted fields."""
    field_reports: Dict[str, FieldVerificationInfo] = {}
    flagged_count = 0

    fields_to_check = dict(extracted_fields)

    # 1. Certificate Number Validation
    cert_no = fields_to_check.get("Certificate Number") or fields_to_check.get("certificate_number")
    if document_type in {"Community Certificate", "Income Certificate", "Birth Certificate"}:
        info = validate_certificate_number(cert_no, ocr_text)
        field_reports["Certificate Number"] = info
        if info.is_flagged:
            flagged_count += 1

    # 2. Aadhaar Number Validation
    aadhaar_no = fields_to_check.get("Aadhaar Number") or fields_to_check.get("aadhaar_number")
    if document_type == "Aadhaar Card" or aadhaar_no:
        info = validate_aadhaar_number(aadhaar_no, ocr_text)
        field_reports["Aadhaar Number"] = info
        if info.is_flagged:
            flagged_count += 1

    # 3. Citizen Name Validation
    citizen_name = (
        fields_to_check.get("Citizen Name")
        or fields_to_check.get("citizen_name")
        or fields_to_check.get("Applicant Name")
        or fields_to_check.get("Name")
    )
    name_info = validate_person_name(citizen_name, "Citizen Name", ocr_text)
    field_reports["Citizen Name"] = name_info
    if name_info.is_flagged:
        flagged_count += 1

    # 4. Father / Guardian Name Validation
    father_name = (
        fields_to_check.get("Father / Guardian")
        or fields_to_check.get("Father's Name")
        or fields_to_check.get("Father / Husband Name")
    )
    if father_name:
        father_info = validate_person_name(father_name, "Father / Guardian", ocr_text)
        field_reports["Father / Guardian"] = father_info
        if father_info.is_flagged:
            flagged_count += 1

    # 5. District Validation
    district = fields_to_check.get("District") or fields_to_check.get("district")
    dist_info = validate_district(district, ocr_text)
    field_reports["District"] = dist_info
    if dist_info.is_flagged:
        flagged_count += 1

    # 6. Date of Birth Validation
    dob = fields_to_check.get("Date of Birth") or fields_to_check.get("dob") or fields_to_check.get("DOB")
    if dob:
        dob_info = validate_date(dob, "Date of Birth", ocr_text)
        field_reports["Date of Birth"] = dob_info
        if dob_info.is_flagged:
            flagged_count += 1

    # 7. Issue Date Validation
    issue_date = fields_to_check.get("Issue Date") or fields_to_check.get("issue_date")
    if issue_date:
        issue_info = validate_date(issue_date, "Issue Date", ocr_text)
        field_reports["Issue Date"] = issue_info
        if issue_info.is_flagged:
            flagged_count += 1

    # Extra non-standard fields pass-through
    for k, v in fields_to_check.items():
        standard_keys = {
            "Certificate Number", "certificate_number", "Aadhaar Number", "aadhaar_number",
            "Citizen Name", "citizen_name", "Applicant Name", "Name", "Child Name",
            "Father / Guardian", "Father's Name", "Father / Husband Name",
            "District", "district", "Date of Birth", "dob", "DOB", "Issue Date", "issue_date",
        }
        if k not in standard_keys and k not in field_reports and v:
            c_score = 0.95
            is_f = False
            reasons = []
            if SUSPICIOUS_CHARS_REGEX.search(str(v)):
                is_f = True
                c_score = 0.60
                reasons.append("Uncertain OCR characters detected")
            field_reports[k] = FieldVerificationInfo(
                field_name=k,
                extracted_value=str(v),
                is_flagged=is_f,
                confidence_score=c_score,
                issue_reasons=reasons,
                ocr_context=find_ocr_context_snippet(ocr_text, str(v)),
            )
            if is_f:
                flagged_count += 1

    # Determine overall status
    if current_status == "manually_verified":
        overall_status = "manually_verified"
    elif flagged_count > 0:
        overall_status = "needs_review"
    else:
        overall_status = "auto_verified"

    return DocumentVerificationReport(
        document_id=doc_id,
        document_type=document_type,
        overall_status=overall_status,
        total_fields=len(field_reports),
        flagged_fields_count=flagged_count,
        fields=field_reports,
        verified_by=verified_by,
        verified_at=verified_at,
        correction_history=history or [],
    )


def validate_certificate_number(value: Optional[str], ocr_text: str) -> FieldVerificationInfo:
    """Validate government certificate identifier for OCR anomalies or missing tokens."""
    if not value or not str(value).strip():
        return FieldVerificationInfo(
            field_name="Certificate Number",
            extracted_value=None,
            is_flagged=True,
            confidence_score=0.20,
            issue_reasons=["Certificate Number was not detected by OCR"],
            ocr_context="",
        )

    val = str(value).strip()
    reasons = []
    confidence = 0.95
    suggested = None

    if re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", val):
        # PAN format successfully validated
        return FieldVerificationInfo(
            field_name="Certificate Number",
            extracted_value=val,
            is_flagged=False,
            confidence_score=0.98,
            issue_reasons=[],
            suggested_value=None,
            ocr_context=find_ocr_context_snippet(ocr_text, val),
        )

    if re.match(r"^[A-Z]{2}[0-9]{2}\s?[0-9]{11}$", val):
        # Driving Licence format successfully validated
        return FieldVerificationInfo(
            field_name="Certificate Number",
            extracted_value=val,
            is_flagged=False,
            confidence_score=0.98,
            issue_reasons=[],
            suggested_value=None,
            ocr_context=find_ocr_context_snippet(ocr_text, val),
        )

    if SUSPICIOUS_CHARS_REGEX.search(val):
        reasons.append(f"Uncertain OCR character '{SUSPICIOUS_CHARS_REGEX.search(val).group()}' detected in identifier")
        confidence = 0.50

    if val.startswith("TN") and not val.startswith("TN-") and len(val) > 4:
        suggested = f"TN-{val[2:].lstrip('-')}"
        reasons.append("Missing standard hyphen separator in TN certificate prefix")
        confidence = min(confidence, 0.75)

    if any(noise in val.lower() for noise in ["rmtr", "certificateno", "date"]):
        reasons.append("Header label OCR fragments found attached to number")
        confidence = min(confidence, 0.60)

    if len(val) < 6:
        reasons.append(f"Identifier length ({len(val)}) is unusually short for a government certificate")
        confidence = min(confidence, 0.55)

    is_flagged = len(reasons) > 0
    return FieldVerificationInfo(
        field_name="Certificate Number",
        extracted_value=val,
        is_flagged=is_flagged,
        confidence_score=confidence,
        issue_reasons=reasons,
        suggested_value=suggested,
        ocr_context=find_ocr_context_snippet(ocr_text, val),
    )


def validate_aadhaar_number(value: Optional[str], ocr_text: str) -> FieldVerificationInfo:
    """Validate 12-digit Aadhaar number against format anomalies."""
    if not value or not str(value).strip():
        return FieldVerificationInfo(
            field_name="Aadhaar Number",
            extracted_value=None,
            is_flagged=True,
            confidence_score=0.20,
            issue_reasons=["Aadhaar number was not detected in document"],
            ocr_context="",
        )

    val = str(value).strip()
    reasons = []
    confidence = 0.98
    suggested = None

    digits = re.sub(r"\D", "", val)
    if len(digits) != 12:
        if len(digits) == 16:
            reasons.append("16-digit Virtual ID (VID) extracted instead of 12-digit Aadhaar number")
        else:
            reasons.append(f"Contains {len(digits)} digits instead of expected 12 digits")
        confidence = 0.45

    if SUSPICIOUS_CHARS_REGEX.search(val):
        reasons.append("Uncertain OCR character detected in Aadhaar string")
        confidence = min(confidence, 0.50)

    if len(digits) == 12 and val != f"{digits[:4]} {digits[4:8]} {digits[8:]}":
        suggested = f"{digits[:4]} {digits[4:8]} {digits[8:]}"

    is_flagged = len(reasons) > 0
    return FieldVerificationInfo(
        field_name="Aadhaar Number",
        extracted_value=val,
        is_flagged=is_flagged,
        confidence_score=confidence,
        issue_reasons=reasons,
        suggested_value=suggested,
        ocr_context=find_ocr_context_snippet(ocr_text, val),
    )


def validate_person_name(value: Optional[str], field_name: str, ocr_text: str) -> FieldVerificationInfo:
    """Validate person name for artifacts, truncated tokens, or noise."""
    if not value or not str(value).strip():
        return FieldVerificationInfo(
            field_name=field_name,
            extracted_value=None,
            is_flagged=True,
            confidence_score=0.20,
            issue_reasons=[f"{field_name} could not be extracted"],
            ocr_context="",
        )

    val = str(value).strip()
    reasons = []
    confidence = 0.95
    suggested = None

    if SUSPICIOUS_CHARS_REGEX.search(val):
        reasons.append(f"Uncertain character '{SUSPICIOUS_CHARS_REGEX.search(val).group()}' detected in name")
        confidence = 0.50

    if any(char.isdigit() for char in val):
        reasons.append("Numeric digits found inside person name")
        confidence = min(confidence, 0.60)

    noise_words = {"iddress", "regulations", "address", "government", "unique", "authority"}
    val_lower = val.lower()
    for nw in noise_words:
        if nw in val_lower:
            reasons.append(f"Extracted name contains non-name keyword '{nw}'")
            confidence = min(confidence, 0.40)
            break

    if "'" in val:
        cleaned = re.sub(r"['`’]", " ", val).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        suggested = cleaned
        reasons.append("Unwanted apostrophe/punctuation in name")
        confidence = min(confidence, 0.70)

    if len(val) < 2:
        reasons.append(f"{field_name} is too short (< 2 characters)")
        confidence = min(confidence, 0.40)

    is_flagged = len(reasons) > 0
    return FieldVerificationInfo(
        field_name=field_name,
        extracted_value=val,
        is_flagged=is_flagged,
        confidence_score=confidence,
        issue_reasons=reasons,
        suggested_value=suggested,
        ocr_context=find_ocr_context_snippet(ocr_text, val),
    )


def validate_district(value: Optional[str], ocr_text: str) -> FieldVerificationInfo:
    """Validate district against known Tamil Nadu revenue districts."""
    if not value or not str(value).strip():
        return FieldVerificationInfo(
            field_name="District",
            extracted_value=None,
            is_flagged=False,
            confidence_score=0.50,
            issue_reasons=[],
            ocr_context="",
        )

    val = str(value).strip()
    reasons = []
    confidence = 0.95
    suggested = None

    matched = None
    for dist in TN_DISTRICTS:
        if dist.lower() == val.lower():
            matched = dist
            break

    if not matched:
        from difflib import get_close_matches
        matches = get_close_matches(val, list(TN_DISTRICTS), n=1, cutoff=0.75)
        if matches:
            suggested = matches[0]
            reasons.append(f"District '{val}' likely misspelling of official district '{matches[0]}'")
            confidence = 0.70
        else:
            reasons.append(f"District '{val}' not recognized in standard Tamil Nadu district registry")
            confidence = 0.50

    is_flagged = len(reasons) > 0
    return FieldVerificationInfo(
        field_name="District",
        extracted_value=val,
        is_flagged=is_flagged,
        confidence_score=confidence,
        issue_reasons=reasons,
        suggested_value=suggested,
        ocr_context=find_ocr_context_snippet(ocr_text, val),
    )


def validate_date(value: Optional[str], field_name: str, ocr_text: str) -> FieldVerificationInfo:
    """Validate date format (DD-MM-YYYY or DD/MM/YYYY)."""
    if not value or not str(value).strip():
        return FieldVerificationInfo(
            field_name=field_name,
            extracted_value=None,
            is_flagged=False,
            confidence_score=0.50,
            ocr_context="",
        )

    val = str(value).strip()
    reasons = []
    confidence = 0.95
    suggested = None

    norm_val = val.replace("/", "-")
    parts = norm_val.split("-")
    if len(parts) == 3:
        try:
            day = int(parts[0])
            month = int(parts[1])
            year = int(parts[2])
            if day < 1 or day > 31:
                reasons.append(f"Invalid day value ({day}) in date")
                confidence = 0.40
            if month < 1 or month > 12:
                reasons.append(f"Invalid month value ({month}) in date")
                confidence = 0.40
            if year < 1900 or year > 2100:
                reasons.append(f"Invalid year value ({year}) in date")
                confidence = 0.40
        except ValueError:
            reasons.append("Date contains non-numeric characters")
            confidence = 0.50
    else:
        reasons.append(f"Date '{val}' does not conform to DD-MM-YYYY structure")
        confidence = 0.50

    is_flagged = len(reasons) > 0
    return FieldVerificationInfo(
        field_name=field_name,
        extracted_value=val,
        is_flagged=is_flagged,
        confidence_score=confidence,
        issue_reasons=reasons,
        suggested_value=suggested,
        ocr_context=find_ocr_context_snippet(ocr_text, val),
    )


# ---------------- Database Operations ----------------


def get_document_verification_details(
    database_path: str | Path,
    doc_id: int,
) -> Optional[DocumentVerificationReport]:
    """Retrieve document details and run verification analysis."""
    ensure_verification_schema(database_path)
    with get_connection(database_path) as conn:
        row = conn.execute(
            """
            SELECT id, document_type, citizen_name, certificate_number,
                   aadhaar_number, dob, district, issue_date, upload_date,
                   ocr_text, file_path, extra_fields, verification_status,
                   verified_by, verified_at, field_corrections, verification_flags
            FROM government_documents
            WHERE id = ?
            """,
            (doc_id,),
        ).fetchone()

        if not row:
            return None

        audit_rows = conn.execute(
            """
            SELECT field_name, old_value, new_value, corrected_by, corrected_at, notes
            FROM verification_audit_logs
            WHERE document_id = ?
            ORDER BY id ASC
            """,
            (doc_id,),
        ).fetchall()
        history = [dict(ar) for ar in audit_rows]

    doc = dict(row)
    extra_fields = {}
    try:
        extra_fields = json.loads(doc.get("extra_fields") or "{}")
    except Exception:
        pass

    all_fields = dict(extra_fields)
    if doc.get("citizen_name") and "Citizen Name" not in all_fields:
        all_fields["Citizen Name"] = doc["citizen_name"]
    if doc.get("certificate_number") and "Certificate Number" not in all_fields:
        all_fields["Certificate Number"] = doc["certificate_number"]
    if doc.get("aadhaar_number") and "Aadhaar Number" not in all_fields:
        all_fields["Aadhaar Number"] = doc["aadhaar_number"]
    if doc.get("district") and "District" not in all_fields:
        all_fields["District"] = doc["district"]
    if doc.get("dob") and "Date of Birth" not in all_fields:
        all_fields["Date of Birth"] = doc["dob"]
    if doc.get("issue_date") and "Issue Date" not in all_fields:
        all_fields["Issue Date"] = doc["issue_date"]

    return analyze_document_fields(
        doc_id=doc["id"],
        document_type=doc["document_type"],
        extracted_fields=all_fields,
        ocr_text=doc.get("ocr_text") or "",
        current_status=doc.get("verification_status"),
        verified_by=doc.get("verified_by"),
        verified_at=doc.get("verified_at"),
        history=history,
    )


def apply_field_corrections(
    database_path: str | Path,
    doc_id: int,
    corrected_fields: Dict[str, Any],
    reviewer_name: str = "Authorized Reviewer",
    notes: Optional[str] = None,
) -> DocumentVerificationReport:
    """Save human-in-the-loop field corrections and update verification status."""
    ensure_verification_schema(database_path)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_connection(database_path) as conn:
        row = conn.execute(
            """
            SELECT id, document_type, citizen_name, certificate_number,
                   aadhaar_number, dob, district, issue_date, ocr_text,
                   extra_fields, field_corrections
            FROM government_documents
            WHERE id = ?
            """,
            (doc_id,),
        ).fetchone()

        if not row:
            raise ValueError(f"Document with ID {doc_id} does not exist.")

        doc = dict(row)
        extra_fields = json.loads(doc.get("extra_fields") or "{}")
        correction_history = json.loads(doc.get("field_corrections") or "{}")

        changes_made = {}
        for field_k, new_v in corrected_fields.items():
            new_v_str = str(new_v).strip() if new_v is not None else ""
            old_v_str = str(extra_fields.get(field_k, "")).strip()

            if not old_v_str:
                col_map = {
                    "Citizen Name": "citizen_name",
                    "Certificate Number": "certificate_number",
                    "Aadhaar Number": "aadhaar_number",
                    "Date of Birth": "dob",
                    "District": "district",
                    "Issue Date": "issue_date",
                }
                if field_k in col_map:
                    old_v_str = str(doc.get(col_map[field_k]) or "").strip()

            if new_v_str != old_v_str:
                changes_made[field_k] = {"old": old_v_str, "new": new_v_str}
                conn.execute(
                    """
                    INSERT INTO verification_audit_logs (
                        document_id, field_name, old_value, new_value,
                        corrected_by, corrected_at, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (doc_id, field_k, old_v_str, new_v_str, reviewer_name, now_iso, notes),
                )

        for field_k, new_v in corrected_fields.items():
            extra_fields[field_k] = str(new_v).strip() if new_v is not None else ""

        citizen_name = (
            extra_fields.get("Citizen Name")
            or extra_fields.get("Applicant Name")
            or extra_fields.get("Name")
            or doc.get("citizen_name")
        )
        certificate_number = extra_fields.get("Certificate Number") or doc.get("certificate_number")
        aadhaar_number = extra_fields.get("Aadhaar Number") or doc.get("aadhaar_number")
        dob = extra_fields.get("Date of Birth") or extra_fields.get("DOB") or doc.get("dob")
        district = extra_fields.get("District") or doc.get("district")
        issue_date = extra_fields.get("Issue Date") or doc.get("issue_date")

        correction_history[now_iso] = {
            "reviewer": reviewer_name,
            "changes": changes_made,
            "notes": notes,
        }

        conn.execute(
            """
            UPDATE government_documents
            SET citizen_name = ?,
                certificate_number = ?,
                aadhaar_number = ?,
                dob = ?,
                district = ?,
                issue_date = ?,
                extra_fields = ?,
                verification_status = 'manually_verified',
                verified_by = ?,
                verified_at = ?,
                field_corrections = ?
            WHERE id = ?
            """,
            (
                citizen_name,
                certificate_number,
                aadhaar_number,
                dob,
                district,
                issue_date,
                json.dumps(extra_fields, ensure_ascii=False),
                reviewer_name,
                now_iso,
                json.dumps(correction_history, ensure_ascii=False),
                doc_id,
            ),
        )

    return get_document_verification_details(database_path, doc_id)
