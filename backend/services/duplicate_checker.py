"""Duplicate detection service for document files, identifiers, and Module 12 Advanced Duplicate Detection."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

try:
    import rapidfuzz.fuzz as fuzz
except ImportError:
    fuzz = None


@dataclass(frozen=True)
class DuplicateCheckResult:
    """The outcome of a basic duplicate check, safe to display in the UI."""

    is_duplicate: bool
    reason: str


@dataclass
class AdvancedDuplicateMatch:
    """A specific matching record identified in the database."""

    record_id: int
    document_type: str
    citizen_name: Optional[str]
    certificate_number: Optional[str]
    aadhaar_number: Optional[str]
    district: Optional[str]
    issue_date: Optional[str]
    file_path: str
    match_type: str  # 'Exact Match' or 'Possible Duplicate'
    similarity_score: float  # 0 to 100
    matched_fields: List[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class AdvancedDuplicateReport:
    """Comprehensive deduplication analysis across all stored documents."""

    status: str  # 'Exact Match', 'Possible Duplicate', 'No Likely Duplicate Found'
    matches_found: int
    matches: List[AdvancedDuplicateMatch] = field(default_factory=list)
    summary_explanation: str = ""
    evaluated_at: str = ""


def check_file_duplicate(document_path: str | Path, upload_folder: str | Path) -> DuplicateCheckResult:
    """Detect an exact duplicate by comparing SHA-256 fingerprints of uploads."""
    source_path = Path(document_path).resolve()
    if not source_path.exists():
        return DuplicateCheckResult(False, "Document file does not exist.")

    source_hash = file_hash(source_path)

    for candidate_path in Path(upload_folder).iterdir():
        if not candidate_path.is_file() or candidate_path.resolve() == source_path:
            continue
        if candidate_path.stat().st_size != source_path.stat().st_size:
            continue
        if file_hash(candidate_path) == source_hash:
            return DuplicateCheckResult(True, "An identical document was uploaded previously.")

    return DuplicateCheckResult(False, "No identical uploaded file was found.")


def check_identifier_duplicate(
    extracted_fields: Mapping[str, str],
    existing_records: Iterable[Mapping[str, str | None]],
) -> DuplicateCheckResult:
    """Compare Aadhaar or certificate identifiers against future stored records."""
    candidate_aadhaar = normalize_identifier(extracted_fields.get("Aadhaar Number"))
    candidate_certificate = normalize_identifier(extracted_fields.get("Certificate Number"))

    for record in existing_records:
        stored_aadhaar = normalize_identifier(record.get("aadhaar_number") or record.get("Aadhaar Number"))
        stored_certificate = normalize_identifier(
            record.get("certificate_number") or record.get("Certificate Number")
        )
        if candidate_aadhaar and candidate_aadhaar == stored_aadhaar:
            return DuplicateCheckResult(True, "A record with the same Aadhaar number already exists.")
        if candidate_certificate and candidate_certificate == stored_certificate:
            return DuplicateCheckResult(True, "A record with the same certificate number already exists.")

    return DuplicateCheckResult(False, "No matching Aadhaar or certificate number was found.")


def file_hash(file_path: Path) -> str:
    """Calculate a SHA-256 fingerprint without loading a whole file into memory."""
    digest = sha256()
    with file_path.open("rb") as document_file:
        for chunk in iter(lambda: document_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_identifier(value: str | None) -> str:
    """Make spacing, dashes, and letter casing irrelevant for identifier checks."""
    return "".join(character for character in (value or "").upper() if character.isalnum())


def normalize_name_for_comparison(name: Optional[str]) -> str:
    """Normalize citizen name for fuzzy comparison by removing honorifics and noise."""
    if not name:
        return ""
    cleaned = re.sub(
        r"^(?:Selvan|Selvi|Thiru|Tmt|Thirumathi|Mr\.?|Mrs\.?|Ms\.?|Shri|Smt\.?|Dr\.?)\s+",
        "",
        str(name).strip(),
        flags=re.I,
    )
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def normalize_date_for_comparison(date_str: Optional[str]) -> str:
    """Standardize date into DD-MM-YYYY format for consistent matching."""
    if not date_str:
        return ""
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", str(date_str))
    if m:
        d, mon, y = m.groups()
        return f"{int(d):02d}-{int(mon):02d}-{y}"
    return str(date_str).strip()


def check_advanced_duplicates(
    extracted_fields: Mapping[str, Any],
    database_path: str | Path,
    exclude_doc_id: Optional[int] = None,
) -> AdvancedDuplicateReport:
    """Execute Module 12 Advanced Duplicate Detection against database records.
    
    Evaluates:
    - Exact match on Certificate Number, Aadhaar Number, PAN, or DL Number
    - Fuzzy match on Citizen Name (RapidFuzz token_sort_ratio) paired with Issue Date or District
    - Assigns: 'Exact Match', 'Possible Duplicate', or 'No Likely Duplicate Found'
    - Does NOT automatically delete or merge records.
    """
    from services.database_service import get_connection

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    cand_cert = normalize_identifier(
        extracted_fields.get("Certificate Number")
        or extracted_fields.get("Registration Number")
        or extracted_fields.get("PAN Number")
        or extracted_fields.get("Driving Licence Number")
    )
    cand_aadhaar = normalize_identifier(extracted_fields.get("Aadhaar Number"))
    cand_name = normalize_name_for_comparison(
        extracted_fields.get("Citizen Name")
        or extracted_fields.get("Name")
        or extracted_fields.get("Applicant Name")
        or extracted_fields.get("Child Name")
    )
    cand_date = normalize_date_for_comparison(extracted_fields.get("Issue Date") or extracted_fields.get("Date of Birth"))
    cand_district = str(extracted_fields.get("District") or "").strip().lower()

    matches: List[AdvancedDuplicateMatch] = []

    with get_connection(database_path) as conn:
        query = """
            SELECT id, document_type, citizen_name, certificate_number,
                   aadhaar_number, dob, district, issue_date, file_path, extra_fields
            FROM government_documents
        """
        params: list[Any] = []
        if exclude_doc_id is not None:
            query += " WHERE id != ?"
            params.append(exclude_doc_id)
        query += " ORDER BY id DESC"

        rows = conn.execute(query, params).fetchall()

    for row in rows:
        rec_id = row["id"]
        doc_type = row["document_type"]
        db_cit_name = row["citizen_name"]
        db_cert = normalize_identifier(row["certificate_number"])
        db_aadhaar = normalize_identifier(row["aadhaar_number"])
        db_date = normalize_date_for_comparison(row["issue_date"] or row["dob"])
        db_district = str(row["district"] or "").strip().lower()
        file_path = row["file_path"]

        # Parse extra_fields for other identifiers
        extra: Dict[str, Any] = {}
        try:
            extra = json.loads(row["extra_fields"] or "{}")
        except Exception:
            pass

        # 1. Exact Match Check (Unique Identifiers)
        if cand_cert and db_cert and cand_cert == db_cert:
            matches.append(
                AdvancedDuplicateMatch(
                    record_id=rec_id,
                    document_type=doc_type,
                    citizen_name=db_cit_name,
                    certificate_number=row["certificate_number"],
                    aadhaar_number=row["aadhaar_number"],
                    district=row["district"],
                    issue_date=row["issue_date"],
                    file_path=file_path,
                    match_type="Exact Match",
                    similarity_score=100.0,
                    matched_fields=["Certificate Number (Exact Match)"],
                    reason=f"The certificate number '{row['certificate_number']}' matches stored record #{rec_id} exactly.",
                )
            )
            continue

        if cand_aadhaar and db_aadhaar and cand_aadhaar == db_aadhaar:
            matches.append(
                AdvancedDuplicateMatch(
                    record_id=rec_id,
                    document_type=doc_type,
                    citizen_name=db_cit_name,
                    certificate_number=row["certificate_number"],
                    aadhaar_number=row["aadhaar_number"],
                    district=row["district"],
                    issue_date=row["issue_date"],
                    file_path=file_path,
                    match_type="Exact Match",
                    similarity_score=100.0,
                    matched_fields=["Aadhaar Number (Exact Match)"],
                    reason=f"The Aadhaar number matches stored record #{rec_id} exactly.",
                )
            )
            continue

        # 2. Fuzzy Name + Corroborating Attribute Matching
        if cand_name and len(cand_name) >= 3:
            db_norm_name = normalize_name_for_comparison(db_cit_name)
            if not db_norm_name and extra.get("Citizen Name"):
                db_norm_name = normalize_name_for_comparison(extra.get("Citizen Name"))

            if db_norm_name and len(db_norm_name) >= 3:
                name_sim = 0.0
                if fuzz:
                    # Token sort ratio handles rearranged words (e.g. 'Gopal N' vs 'N Gopal')
                    name_sim = float(fuzz.token_sort_ratio(cand_name, db_norm_name))
                else:
                    # Fallback standard library difflib
                    import difflib
                    name_sim = difflib.SequenceMatcher(None, cand_name, db_norm_name).ratio() * 100.0

                matched_fields = []
                score_weight = name_sim

                if name_sim >= 85.0:
                    matched_fields.append(f"Citizen Name ({name_sim:.1f}% similarity)")
                    date_match = False
                    district_match = False

                    if cand_date and db_date and cand_date == db_date:
                        date_match = True
                        matched_fields.append("Date of Issue / DOB (Exact Match)")
                        score_weight = max(score_weight, 95.0)

                    if cand_district and db_district and cand_district == db_district:
                        district_match = True
                        matched_fields.append(f"District ({row['district']})")
                        score_weight = min(100.0, score_weight + 5.0)

                    # Only flag as 'Possible Duplicate' if name is highly similar AND (date matches OR district matches OR name is near identical >= 95)
                    if date_match or (district_match and name_sim >= 90.0) or name_sim >= 95.0:
                        reasons = []
                        if name_sim >= 95.0:
                            reasons.append(f"The citizen name '{db_cit_name}' is nearly identical ({name_sim:.1f}%)")
                        else:
                            reasons.append(f"The citizen name is {name_sim:.1f}% similar")
                        if date_match:
                            reasons.append(f"and the date '{cand_date}' matches record #{rec_id}")
                        if district_match:
                            reasons.append(f"in the same district ({row['district']})")

                        matches.append(
                            AdvancedDuplicateMatch(
                                record_id=rec_id,
                                document_type=doc_type,
                                citizen_name=db_cit_name,
                                certificate_number=row["certificate_number"],
                                aadhaar_number=row["aadhaar_number"],
                                district=row["district"],
                                issue_date=row["issue_date"],
                                file_path=file_path,
                                match_type="Possible Duplicate",
                                similarity_score=round(score_weight, 1),
                                matched_fields=matched_fields,
                                reason=" ".join(reasons) + ".",
                            )
                        )

    # Sort matches by similarity score descending
    matches.sort(key=lambda m: m.similarity_score, reverse=True)

    # Determine overall status and human-friendly explanation
    if any(m.match_type == "Exact Match" for m in matches):
        status = "Exact Match"
        exact_count = sum(1 for m in matches if m.match_type == "Exact Match")
        explanation = f"Found {exact_count} exact identifier match(es) with existing records in database."
    elif matches:
        status = "Possible Duplicate"
        explanation = f"Found {len(matches)} potential matching record(s) based on normalized name and cross-referenced dates/district."
    else:
        status = "No Likely Duplicate Found"
        explanation = "No matching unique identifiers or highly similar personal records were found in the database."

    return AdvancedDuplicateReport(
        status=status,
        matches_found=len(matches),
        matches=matches,
        summary_explanation=explanation,
        evaluated_at=now_iso,
    )
