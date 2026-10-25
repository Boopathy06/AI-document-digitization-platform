"""SQLite persistence service for government document records."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Mapping, Optional


CREATE_DOCUMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS government_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_type TEXT NOT NULL,
    citizen_name TEXT,
    certificate_number TEXT,
    aadhaar_number TEXT,
    dob TEXT,
    district TEXT,
    issue_date TEXT,
    upload_date TEXT NOT NULL,
    ocr_text TEXT,
    file_path TEXT NOT NULL,
    extra_fields TEXT NOT NULL DEFAULT '{}',
    verification_status TEXT DEFAULT 'needs_review',
    verified_by TEXT,
    verified_at TEXT,
    field_corrections TEXT DEFAULT '{}',
    verification_flags TEXT DEFAULT '[]',
    consistency_results TEXT DEFAULT '{}',
    quality_score REAL DEFAULT NULL,
    quality_report TEXT DEFAULT '{}'
)
"""


@contextmanager
def get_connection(database_path: str | Path) -> Generator[sqlite3.Connection, None, None]:
    """Provide a transactional SQLite connection that reliably closes on exit."""
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database(database_path: str | Path) -> None:
    """Create the common document table and ensure all modern schema columns exist."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(path) as connection:
        connection.execute(CREATE_DOCUMENTS_TABLE)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_certificate "
            "ON government_documents(certificate_number)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_aadhaar "
            "ON government_documents(aadhaar_number)"
        )

        # Safe migrations for existing databases
        cursor = connection.execute("PRAGMA table_info(government_documents)")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        columns_to_add = [
            ("verification_status", "TEXT DEFAULT 'needs_review'"),
            ("verified_by", "TEXT"),
            ("verified_at", "TEXT"),
            ("field_corrections", "TEXT DEFAULT '{}'"),
            ("verification_flags", "TEXT DEFAULT '[]'"),
            ("consistency_results", "TEXT DEFAULT '{}'"),
            ("quality_score", "REAL DEFAULT NULL"),
            ("quality_report", "TEXT DEFAULT '{}'"),
        ]
        for col_name, col_def in columns_to_add:
            if col_name not in existing_cols:
                try:
                    connection.execute(f"ALTER TABLE government_documents ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass


def fetch_duplicate_records(database_path: str | Path) -> list[dict[str, str | None]]:
    """Return only identifiers needed by the duplicate-checking service."""
    with get_connection(database_path) as connection:
        rows = connection.execute(
            "SELECT id, document_type, citizen_name, aadhaar_number, certificate_number, issue_date, district, file_path FROM government_documents"
        ).fetchall()
    return [dict(row) for row in rows]


def save_document(
    database_path: str | Path,
    document_type: str,
    extracted_fields: Mapping[str, str],
    ocr_text: str,
    file_path: str,
    verification_status: Optional[str] = None,
    quality_score: Optional[float] = None,
    quality_report: Optional[str] = None,
) -> int:
    """Store one non-duplicate document with automated verification and quality indicators."""
    initialize_database(database_path)

    from services.extractors.common import TALUK_TO_DISTRICT_MAP, validate_and_clean_citizen_name

    raw_name = (
        extracted_fields.get("Citizen Name")
        or extracted_fields.get("Name")
        or extracted_fields.get("Applicant Name")
        or extracted_fields.get("Child Name")
    )
    cleaned_name = validate_and_clean_citizen_name(raw_name) if raw_name else None
    citizen_name = cleaned_name or (raw_name.strip() if raw_name else None)

    district = extracted_fields.get("District")
    if not district and extracted_fields.get("Taluk"):
        taluk_key = str(extracted_fields.get("Taluk")).strip().lower()
        if taluk_key in TALUK_TO_DISTRICT_MAP:
            district = TALUK_TO_DISTRICT_MAP[taluk_key]

    common_fields = {
        "citizen_name": citizen_name,
        "certificate_number": (
            extracted_fields.get("Certificate Number")
            or extracted_fields.get("Registration Number")
            or extracted_fields.get("PAN Number")
            or extracted_fields.get("Driving Licence Number")
        ),
        "aadhaar_number": extracted_fields.get("Aadhaar Number"),
        "dob": extracted_fields.get("Date of Birth") or extracted_fields.get("DOB"),
        "district": district,
        "issue_date": extracted_fields.get("Issue Date"),
    }
    upload_date = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Automated verification analysis
    final_status = verification_status
    verification_flags_json = "[]"
    try:
        from services.verification_service import analyze_document_fields
        report = analyze_document_fields(
            doc_id=0,
            document_type=document_type,
            extracted_fields=dict(extracted_fields),
            ocr_text=ocr_text,
            current_status=verification_status,
        )
        if not final_status:
            final_status = report.overall_status
        flagged_list = [
            {"field": fname, "reasons": finfo.issue_reasons}
            for fname, finfo in report.fields.items()
            if finfo.is_flagged
        ]
        verification_flags_json = json.dumps(flagged_list, ensure_ascii=False)
    except Exception:
        if not final_status:
            final_status = "needs_review"

    with get_connection(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO government_documents (
                document_type, citizen_name, certificate_number, aadhaar_number,
                dob, district, issue_date, upload_date, ocr_text, file_path,
                extra_fields, verification_status, verification_flags,
                quality_score, quality_report
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_type,
                common_fields["citizen_name"],
                common_fields["certificate_number"],
                common_fields["aadhaar_number"],
                common_fields["dob"],
                common_fields["district"],
                common_fields["issue_date"],
                upload_date,
                ocr_text,
                file_path,
                json.dumps(dict(extracted_fields), ensure_ascii=False),
                final_status,
                verification_flags_json,
                quality_score,
                quality_report or "{}",
            ),
        )
        return int(cursor.lastrowid)



def count_documents(database_path: str | Path) -> int:
    """Return the number of saved records; useful for the future dashboard."""
    with get_connection(database_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM government_documents").fetchone()[0])
