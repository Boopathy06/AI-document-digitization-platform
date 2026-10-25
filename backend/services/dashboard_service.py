"""Dashboard service for Module 8: Document management, analytics, and search."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple


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


def ensure_dashboard_tables(database_path: str | Path) -> None:
    """Ensure supporting tables like duplicate_logs exist."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS duplicate_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                reason TEXT NOT NULL,
                detected_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_dup_detected_at ON duplicate_logs(detected_at)"
        )


def log_duplicate_attempt(database_path: str | Path, filename: str, reason: str) -> None:
    """Record a blocked duplicate document for auditing and statistics."""
    ensure_dashboard_tables(database_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection(database_path) as connection:
        connection.execute(
            "INSERT INTO duplicate_logs (filename, reason, detected_at) VALUES (?, ?, ?)",
            (filename, reason, timestamp),
        )


def get_dashboard_stats(database_path: str | Path) -> Dict[str, Any]:
    """Calculate summary statistics for the dashboard overview."""
    ensure_dashboard_tables(database_path)
    with get_connection(database_path) as connection:
        # Total documents
        total_docs = connection.execute(
            "SELECT COUNT(*) FROM government_documents"
        ).fetchone()[0]

        # Breakdown by document type
        type_rows = connection.execute(
            """
            SELECT document_type, COUNT(*) as count 
            FROM government_documents 
            GROUP BY document_type 
            ORDER BY count DESC
            """
        ).fetchall()
        type_breakdown = {row["document_type"]: row["count"] for row in type_rows}

        # Total duplicates blocked
        dup_count = connection.execute(
            "SELECT COUNT(*) FROM duplicate_logs"
        ).fetchone()[0]

        # Distinct districts represented
        district_count = connection.execute(
            """
            SELECT COUNT(DISTINCT district) 
            FROM government_documents 
            WHERE district IS NOT NULL AND TRIM(district) != ''
            """
        ).fetchone()[0]

        # Pending verification count (needs_review)
        pending_review_count = 0
        try:
            pending_review_count = connection.execute(
                "SELECT COUNT(*) FROM government_documents WHERE verification_status = 'needs_review'"
            ).fetchone()[0]
        except Exception:
            pass

        # Verified count (auto_verified or manually_verified or verified)
        verified_count = 0
        try:
            verified_count = connection.execute(
                "SELECT COUNT(*) FROM government_documents WHERE verification_status IN ('auto_verified', 'manually_verified', 'verified')"
            ).fetchone()[0]
        except Exception:
            pass

        # Recent 5 documents
        recent_rows = connection.execute(
            """
            SELECT id, document_type, citizen_name, certificate_number, district, upload_date
            FROM government_documents
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()
        recent_documents = [dict(row) for row in recent_rows]

        # Recent 5 duplicate attempts
        recent_dup_rows = connection.execute(
            """
            SELECT id, filename, reason, detected_at
            FROM duplicate_logs
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()
        recent_duplicates = [dict(row) for row in recent_dup_rows]

    return {
        "total_documents": total_docs,
        "type_breakdown": type_breakdown,
        "duplicates_blocked": dup_count,
        "districts_count": district_count,
        "pending_verification": pending_review_count,
        "verified_documents": verified_count,
        "recent_documents": recent_documents,
        "recent_duplicates": recent_duplicates,
    }


def get_all_documents(
    database_path: str | Path,
    search_query: Optional[str] = None,
    document_type: Optional[str] = None,
    district: Optional[str] = None,
    verification_status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Retrieve filtered, searchable, and paginated documents."""
    ensure_dashboard_tables(database_path)

    conditions: List[str] = []
    params: List[Any] = []

    if search_query and search_query.strip():
        term = f"%{search_query.strip()}%"
        conditions.append(
            "(citizen_name LIKE ? OR certificate_number LIKE ? OR aadhaar_number LIKE ? OR district LIKE ? OR ocr_text LIKE ?)"
        )
        params.extend([term, term, term, term, term])

    if document_type and document_type.strip() and document_type != "All":
        conditions.append("document_type = ?")
        params.append(document_type.strip())

    if district and district.strip() and district != "All":
        conditions.append("district = ?")
        params.append(district.strip())

    if verification_status and verification_status.strip() and verification_status != "All":
        if verification_status == "verified":
            conditions.append("verification_status IN ('auto_verified', 'manually_verified', 'verified')")
        else:
            conditions.append("verification_status = ?")
            params.append(verification_status.strip())

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with get_connection(database_path) as connection:
        count_sql = f"SELECT COUNT(*) FROM government_documents {where_clause}"
        total_count = connection.execute(count_sql, params).fetchone()[0]

        sql = f"""
            SELECT id, document_type, citizen_name, certificate_number, 
                   aadhaar_number, dob, district, issue_date, upload_date, file_path, extra_fields,
                   verification_status, verified_by, verified_at, quality_score
            FROM government_documents
            {where_clause}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """
        rows = connection.execute(sql, params + [limit, offset]).fetchall()
        documents = []
        for row in rows:
            doc_dict = dict(row)
            if (not doc_dict.get("citizen_name") or not doc_dict.get("district")) and doc_dict.get("extra_fields"):
                try:
                    ef = json.loads(doc_dict["extra_fields"])
                    if not doc_dict.get("citizen_name"):
                        doc_dict["citizen_name"] = (
                            ef.get("Citizen Name")
                            or ef.get("Applicant Name")
                            or ef.get("Name")
                            or ef.get("Child Name")
                        )
                    if not doc_dict.get("district") and ef.get("District"):
                        doc_dict["district"] = ef.get("District")
                except Exception:
                    pass
            documents.append(doc_dict)

    return documents, total_count


def get_document_by_id(database_path: str | Path, doc_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve full details of a specific document including parsed extra fields."""
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT id, document_type, citizen_name, certificate_number,
                   aadhaar_number, dob, district, issue_date, upload_date,
                   ocr_text, file_path, extra_fields,
                   verification_status, verified_by, verified_at,
                   field_corrections, verification_flags, consistency_results,
                   quality_score, quality_report
            FROM government_documents
            WHERE id = ?
            """,
            (doc_id,),
        ).fetchone()

    if not row:
        return None

    doc = dict(row)
    try:
        doc["extra_fields_parsed"] = json.loads(doc.get("extra_fields") or "{}")
    except Exception:
        doc["extra_fields_parsed"] = {}
    try:
        doc["field_corrections_parsed"] = json.loads(doc.get("field_corrections") or "{}")
    except Exception:
        doc["field_corrections_parsed"] = {}
    try:
        doc["verification_flags_parsed"] = json.loads(doc.get("verification_flags") or "[]")
    except Exception:
        doc["verification_flags_parsed"] = []
    try:
        doc["consistency_results_parsed"] = json.loads(doc.get("consistency_results") or "{}")
    except Exception:
        doc["consistency_results_parsed"] = {}
    try:
        doc["quality_report_parsed"] = json.loads(doc.get("quality_report") or "{}")
    except Exception:
        doc["quality_report_parsed"] = {}

    return doc



def get_distinct_districts(database_path: str | Path) -> List[str]:
    """Retrieve list of unique districts present in database."""
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT district 
            FROM government_documents 
            WHERE district IS NOT NULL AND TRIM(district) != ''
            ORDER BY district ASC
            """
        ).fetchall()
    return [row["district"] for row in rows]


def get_distinct_document_types(database_path: str | Path) -> List[str]:
    """Retrieve list of unique document types present in database."""
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT document_type 
            FROM government_documents 
            ORDER BY document_type ASC
            """
        ).fetchall()
    return [row["document_type"] for row in rows]
