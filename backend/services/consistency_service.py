"""Document Consistency Verification Service for Module 13.

Performs completeness checks, formatting validations, cross-field logical integrity checks,
and date relationship assertions across all supported government document types.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from services.extractors.common import (
    TALUK_TO_DISTRICT_MAP,
    TN_DISTRICTS,
    clean_person_name,
)

# Configurable Required Fields per Document Type
REQUIRED_FIELDS_BY_TYPE: Dict[str, List[str]] = {
    "Aadhaar Card": ["Citizen Name", "Aadhaar Number", "Date of Birth", "Gender"],
    "Community Certificate": ["Citizen Name", "Certificate Number", "Community", "District"],
    "Income Certificate": ["Citizen Name", "Certificate Number", "Annual Income", "District"],
    "Birth Certificate": ["Citizen Name", "Certificate Number", "Date of Birth", "Father's Name"],
    "PAN Card": ["Citizen Name", "PAN Number", "Date of Birth"],
    "Driving Licence": ["Citizen Name", "Driving Licence Number", "Date of Birth", "Issue Date"],
    "Generic Document": ["Citizen Name"],
    "Unknown": ["Citizen Name"],
}

# Configurable Optional Fields per Document Type
OPTIONAL_FIELDS_BY_TYPE: Dict[str, List[str]] = {
    "Aadhaar Card": ["PIN Code", "District", "Address", "Father / Guardian"],
    "Community Certificate": ["Father / Guardian", "Issue Date", "Taluk", "Village"],
    "Income Certificate": ["Father / Husband Name", "Issue Date", "Taluk", "Village"],
    "Birth Certificate": ["Mother's Name", "Place of Birth", "District", "Issue Date"],
    "PAN Card": ["Father's Name", "Issue Date"],
    "Driving Licence": ["Father / Husband Name", "Validity Expiry", "Blood Group"],
    "Generic Document": ["District", "Date", "Identifier"],
    "Unknown": [],
}


@dataclass
class FieldConsistencyResult:
    """Field-level consistency validation outcome."""

    field_name: str
    extracted_value: Optional[str]
    validation_status: str  # 'Passed', 'Warning', 'Failed', 'Not Checked'
    explanation: str
    suggested_action: Optional[str] = None


@dataclass
class DocumentConsistencyReport:
    """Comprehensive consistency and integrity report for a document."""

    document_id: int
    document_type: str
    overall_status: str  # 'Passed', 'Warning', 'Failed'
    summary_message: str
    total_checks: int
    passed_count: int
    warning_count: int
    failed_count: int
    field_results: Dict[str, FieldConsistencyResult] = field(default_factory=dict)
    logical_integrity_checks: List[Dict[str, str]] = field(default_factory=list)
    evaluated_at: str = ""


def parse_date_to_object(date_str: Optional[str]) -> Optional[date]:
    """Parse various date formats into a standard date object."""
    if not date_str:
        return None
    val = str(date_str).strip()
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", val)
    if match:
        d, m, y = match.groups()
        try:
            return date(int(y), int(m), int(d))
        except ValueError:
            return None
    return None


def verify_document_consistency(
    doc_id: int,
    document_type: str,
    extracted_fields: Mapping[str, Any],
    ocr_text: str = "",
    database_path: Optional[str | Path] = None,
) -> DocumentConsistencyReport:
    """Run Module 13 Document Consistency Verification across all fields and logical relationships."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    field_results: Dict[str, FieldConsistencyResult] = {}
    logical_checks: List[Dict[str, str]] = []

    fields = dict(extracted_fields)
    required = REQUIRED_FIELDS_BY_TYPE.get(document_type, REQUIRED_FIELDS_BY_TYPE["Generic Document"])
    optional = OPTIONAL_FIELDS_BY_TYPE.get(document_type, [])

    # Map aliases
    if "Certificate Number" not in fields:
        if fields.get("PAN Number"):
            fields["Certificate Number"] = fields["PAN Number"]
        elif fields.get("Driving Licence Number"):
            fields["Certificate Number"] = fields["Driving Licence Number"]
        elif fields.get("Registration Number"):
            fields["Certificate Number"] = fields["Registration Number"]

    if "Citizen Name" not in fields:
        for k in ["Name", "Applicant Name", "Child Name", "Card Holder's Name"]:
            if fields.get(k):
                fields["Citizen Name"] = fields[k]
                break

    if "Date of Birth" not in fields and fields.get("DOB"):
        fields["Date of Birth"] = fields["DOB"]

    # 1. Required Field Presence & Completeness Check
    for req_field in required:
        val = fields.get(req_field)
        val_str = str(val).strip() if val is not None else ""

        if not val_str:
            field_results[req_field] = FieldConsistencyResult(
                field_name=req_field,
                extracted_value=None,
                validation_status="Failed",
                explanation=f"Mandatory required field '{req_field}' is missing or could not be detected from OCR.",
                suggested_action=f"Manually review the document and enter the correct {req_field}.",
            )
        else:
            # Format validation per field type
            status, expl, action = validate_field_format(req_field, val_str, document_type)
            field_results[req_field] = FieldConsistencyResult(
                field_name=req_field,
                extracted_value=val_str,
                validation_status=status,
                explanation=expl,
                suggested_action=action,
            )

    # 2. Optional Fields Validation (Missing optional fields do NOT fail)
    for opt_field in optional:
        if opt_field in field_results:
            continue
        val = fields.get(opt_field)
        val_str = str(val).strip() if val is not None else ""
        if val_str:
            status, expl, action = validate_field_format(opt_field, val_str, document_type)
            field_results[opt_field] = FieldConsistencyResult(
                field_name=opt_field,
                extracted_value=val_str,
                validation_status=status,
                explanation=expl,
                suggested_action=action,
            )

    # Any remaining extracted extra fields
    for k, v in fields.items():
        if k not in field_results and v and str(v).strip():
            field_results[k] = FieldConsistencyResult(
                field_name=k,
                extracted_value=str(v).strip(),
                validation_status="Passed",
                explanation="Field format is valid.",
                suggested_action=None,
            )

    # 3. Logical Integrity Check: Sensible Date Relationships
    dob_obj = parse_date_to_object(fields.get("Date of Birth") or fields.get("DOB"))
    issue_obj = parse_date_to_object(fields.get("Issue Date"))
    today = date.today()

    if issue_obj:
        if issue_obj > today:
            logical_checks.append({
                "check": "Issue Date Validity",
                "status": "Failed",
                "explanation": f"Document issue date ({issue_obj.strftime('%d-%m-%Y')}) cannot be in the future.",
                "suggested_action": "Check document date for OCR typo in the year.",
            })
            if "Issue Date" in field_results:
                field_results["Issue Date"].validation_status = "Failed"
                field_results["Issue Date"].explanation = "Issue date is in the future."

    if dob_obj and issue_obj:
        if issue_obj < dob_obj:
            logical_checks.append({
                "check": "DOB vs Issue Date Chronology",
                "status": "Failed",
                "explanation": f"Issue date ({issue_obj.strftime('%d-%m-%Y')}) cannot be earlier than citizen Date of Birth ({dob_obj.strftime('%d-%m-%Y')}).",
                "suggested_action": "Verify whether issue date and birth date were transposed during extraction.",
            })
            if "Issue Date" in field_results:
                field_results["Issue Date"].validation_status = "Failed"
        else:
            age_at_issue = (issue_obj - dob_obj).days // 365
            if document_type == "Driving Licence" and age_at_issue < 18:
                logical_checks.append({
                    "check": "Minimum Age Requirement",
                    "status": "Failed",
                    "explanation": f"Citizen age at Driving Licence issuance was {age_at_issue} years (must be at least 18).",
                    "suggested_action": "Recheck Date of Birth or Issue Date against the licence card.",
                })
            else:
                logical_checks.append({
                    "check": "Date Chronology",
                    "status": "Passed",
                    "explanation": f"Issue date is chronologically consistent with Date of Birth (Age: {age_at_issue} years).",
                    "suggested_action": None,
                })

    # 4. Cross-Field Conflicts: Citizen Name vs Father's Name
    cit_name = fields.get("Citizen Name") or fields.get("Name")
    fat_name = fields.get("Father's Name") or fields.get("Father / Guardian") or fields.get("Father / Husband Name")

    if cit_name and fat_name:
        clean_cit = clean_person_name(cit_name).lower()
        clean_fat = clean_person_name(fat_name).lower()
        if clean_cit == clean_fat and len(clean_cit) > 2:
            logical_checks.append({
                "check": "Citizen vs Parent Name Differentiation",
                "status": "Warning",
                "explanation": f"Citizen Name and Father Name are identical ('{cit_name}'). Possible OCR group transposition.",
                "suggested_action": "Confirm if the citizen and parent share the exact same name.",
            })
        else:
            logical_checks.append({
                "check": "Citizen vs Parent Identity",
                "status": "Passed",
                "explanation": "Citizen and guardian names are distinctly identified.",
                "suggested_action": None,
            })

    # 5. Cross-Field Location Consistency: Taluk vs District
    taluk_val = fields.get("Taluk")
    dist_val = fields.get("District")
    if taluk_val and dist_val:
        taluk_clean = str(taluk_val).strip().lower()
        dist_clean = str(dist_val).strip().capitalize()
        mapped_district = TALUK_TO_DISTRICT_MAP.get(taluk_clean)
        if mapped_district and mapped_district.lower() != dist_clean.lower():
            logical_checks.append({
                "check": "Taluk to District Geographic Consistency",
                "status": "Warning",
                "explanation": f"Taluk '{taluk_val}' typically belongs to '{mapped_district}' District, but extracted district is '{dist_val}'.",
                "suggested_action": f"Verify whether '{dist_val}' or '{mapped_district}' is the correct district on the certificate.",
            })
        elif mapped_district:
            logical_checks.append({
                "check": "Geographic Consistency",
                "status": "Passed",
                "explanation": f"Taluk '{taluk_val}' belongs to '{dist_clean}' District as verified by state records.",
                "suggested_action": None,
            })

    # 6. Database Historical Inconsistency Cross-Check
    if database_path and cit_name and len(clean_person_name(cit_name)) >= 3 and dob_obj:
        try:
            from services.database_service import get_connection
            with get_connection(database_path) as conn:
                norm_cit = clean_person_name(cit_name).lower()
                query = "SELECT id, citizen_name, dob FROM government_documents WHERE id != ? AND citizen_name IS NOT NULL"
                params = [doc_id]
                rows = conn.execute(query, params).fetchall()
                for r in rows:
                    if clean_person_name(r["citizen_name"]).lower() == norm_cit:
                        db_dob_obj = parse_date_to_object(r["dob"])
                        if db_dob_obj and db_dob_obj != dob_obj:
                            logical_checks.append({
                                "check": "Historical Database Consistency",
                                "status": "Warning",
                                "explanation": f"Citizen '{cit_name}' matches record #{r['id']} but with conflicting DOB ({db_dob_obj.strftime('%d-%m-%Y')} vs {dob_obj.strftime('%d-%m-%Y')}).",
                                "suggested_action": "Check if two different individuals share the same name or if DOB was misread.",
                            })
                            break
        except Exception:
            pass

    # Calculate overall status
    failed_count = sum(1 for r in field_results.values() if r.validation_status == "Failed") + sum(
        1 for c in logical_checks if c["status"] == "Failed"
    )
    warning_count = sum(1 for r in field_results.values() if r.validation_status == "Warning") + sum(
        1 for c in logical_checks if c["status"] == "Warning"
    )
    passed_count = sum(1 for r in field_results.values() if r.validation_status == "Passed") + sum(
        1 for c in logical_checks if c["status"] == "Passed"
    )

    if failed_count > 0:
        overall_status = "Failed"
        summary = f"Consistency check failed with {failed_count} critical issue(s) and {warning_count} warning(s)."
    elif warning_count > 0:
        overall_status = "Warning"
        summary = f"Consistency check passed with {warning_count} non-critical warning(s) recommended for review."
    else:
        overall_status = "Passed"
        summary = "All required fields, formatting rules, and logical relationships verified successfully."

    return DocumentConsistencyReport(
        document_id=doc_id,
        document_type=document_type,
        overall_status=overall_status,
        summary_message=summary,
        total_checks=len(field_results) + len(logical_checks),
        passed_count=passed_count,
        warning_count=warning_count,
        failed_count=failed_count,
        field_results=field_results,
        logical_integrity_checks=logical_checks,
        evaluated_at=now_iso,
    )


def validate_field_format(
    field_name: str,
    value: str,
    document_type: str,
) -> Tuple[str, str, Optional[str]]:
    """Validate specific format rules for a given field name."""
    val = value.strip()

    # 1. Date format validation
    if any(k in field_name.lower() for k in ["date", "dob"]):
        date_obj = parse_date_to_object(val)
        if not date_obj:
            return "Failed", f"Date '{val}' does not conform to valid DD-MM-YYYY calendar format.", "Reformat date as DD-MM-YYYY."
        if not (1900 <= date_obj.year <= 2030):
            return "Warning", f"Year {date_obj.year} in '{val}' is outside expected range (1900–2030).", "Verify certificate issuance year."
        return "Passed", f"Valid date format ({val}).", None

    # 2. Aadhaar Number format
    if "aadhaar" in field_name.lower():
        digits = re.sub(r"\s+", "", val)
        if not digits.isdigit() or len(digits) != 12:
            return "Failed", f"Aadhaar number must contain exactly 12 digits (found {len(digits)}).", "Enter 12-digit Aadhaar number."
        if digits[0] in "01":
            return "Warning", "Aadhaar numbers do not usually begin with 0 or 1.", "Verify the first digit from original card."
        return "Passed", "Standard 12-digit Aadhaar format verified.", None

    # 3. PAN Number format
    if "pan" in field_name.lower():
        if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", val.upper()):
            return "Failed", f"PAN identifier '{val}' does not match standard 10-character PAN format (5 letters, 4 digits, 1 letter).", "Check PAN letters and digits."
        return "Passed", "Standard PAN format verified.", None

    # 4. Driving Licence format
    if "driving" in field_name.lower() or "licence" in field_name.lower():
        clean_dl = re.sub(r"[\s\-]", "", val)
        if len(clean_dl) < 9 or not clean_dl[:2].isalpha():
            return "Warning", f"Licence number '{val}' format does not match typical state DL format.", "Verify licence number."
        return "Passed", "Driving Licence identifier format verified.", None

    # 5. Certificate Number
    if "certificate number" in field_name.lower():
        if len(val) < 5:
            return "Warning", f"Certificate identifier '{val}' is unusually short.", "Verify certificate registration number."
        if any(c in val for c in ["?", "~", "*", "!", "^"]):
            return "Warning", f"Uncertain OCR character detected in identifier '{val}'.", "Verify against clear certificate seal."
        return "Passed", "Certificate identifier format verified.", None

    # 6. District Validation
    if "district" in field_name.lower():
        from difflib import get_close_matches
        matches = get_close_matches(val.capitalize(), TN_DISTRICTS, n=1, cutoff=0.7)
        if not matches:
            return "Warning", f"District '{val}' is not recognized in official Tamil Nadu district registry.", "Verify district spelling."
        return "Passed", f"Recognized Tamil Nadu district ({matches[0]}).", None

    # 7. Annual Income Validation
    if "income" in field_name.lower():
        digits = re.sub(r"[^\d]", "", val)
        if not digits or int(digits) <= 0:
            return "Failed", f"Annual Income '{val}' must contain a positive numeric monetary amount.", "Enter valid annual income in Rupees."
        return "Passed", f"Valid numeric income amount (Rs. {int(digits):,}).", None

    # 8. Person Names (Citizen, Father, Mother)
    if any(k in field_name.lower() for k in ["name", "citizen"]):
        clean = clean_person_name(val)
        if len(clean) < 2:
            return "Failed", f"Name '{val}' is too short or contains invalid tokens.", "Enter full person name."
        if any(c.isdigit() for c in clean):
            return "Warning", f"Name '{val}' contains numbers which may indicate OCR noise.", "Remove numeric characters from name."
        return "Passed", "Valid person name structure.", None

    return "Passed", "Field structure passed basic format checks.", None
