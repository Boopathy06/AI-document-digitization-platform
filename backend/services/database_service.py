"""SQLite persistence service for government document records."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Mapping


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
    extra_fields TEXT NOT NULL DEFAULT '{}'
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
    """Create the common document table without changing any legacy tables."""
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


def fetch_duplicate_records(database_path: str | Path) -> list[dict[str, str | None]]:
    """Return only identifiers needed by the duplicate-checking service."""
    with get_connection(database_path) as connection:
        rows = connection.execute(
            "SELECT aadhaar_number, certificate_number FROM government_documents"
        ).fetchall()
    return [dict(row) for row in rows]


def save_document(
    database_path: str | Path,
    document_type: str,
    extracted_fields: Mapping[str, str],
    ocr_text: str,
    file_path: str,
) -> int:
    """Store one non-duplicate document and return its database ID."""
    common_fields = {
        "citizen_name": extracted_fields.get("Citizen Name"),
        "certificate_number": extracted_fields.get("Certificate Number"),
        "aadhaar_number": extracted_fields.get("Aadhaar Number"),
        "dob": extracted_fields.get("Date of Birth"),
        "district": extracted_fields.get("District"),
        "issue_date": extracted_fields.get("Issue Date"),
    }
    upload_date = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_connection(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO government_documents (
                document_type, citizen_name, certificate_number, aadhaar_number,
                dob, district, issue_date, upload_date, ocr_text, file_path,
                extra_fields
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        return int(cursor.lastrowid)


def count_documents(database_path: str | Path) -> int:
    """Return the number of saved records; useful for the future dashboard."""
    with get_connection(database_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM government_documents").fetchone()[0])
