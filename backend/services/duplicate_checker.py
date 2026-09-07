"""Duplicate detection service for document files and extracted identifiers."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class DuplicateCheckResult:
    """The outcome of a duplicate check, safe to display in the UI."""

    is_duplicate: bool
    reason: str


def check_file_duplicate(document_path: str | Path, upload_folder: str | Path) -> DuplicateCheckResult:
    """Detect an exact duplicate by comparing SHA-256 fingerprints of uploads.

    Enhanced files are kept in a subfolder and are therefore not scanned. This
    works before a database exists and catches a user re-uploading the same file.
    """
    source_path = Path(document_path).resolve()
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
    """Compare Aadhaar or certificate identifiers against future stored records.

    The SQLite module will pass database records to this function before saving a
    new document. The function is deliberately independent of Flask and SQLite.
    """
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
