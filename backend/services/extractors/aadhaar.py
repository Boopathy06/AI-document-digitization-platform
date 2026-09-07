"""Field extraction rules specific to Aadhaar documents."""

from .common import add_if_found, first_match, labelled_date, labelled_value, normalized_lines


def extract_fields(ocr_text: str) -> dict[str, str]:
    """Extract Aadhaar identifiers and labelled personal details."""
    text = normalized_lines(ocr_text)
    fields: dict[str, str] = {}
    add_if_found(fields, "Aadhaar Number", first_match(text, r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"))
    add_if_found(fields, "VID", first_match(text, r"\bVID\s*[:\-]?\s*(\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4})\b"))
    add_if_found(fields, "Enrolment Number", first_match(
        text, r"(?:enrolment|enrollment)\s*(?:no\.?|number)?\s*[:\-]?\s*(\d{4}/\d{5}/\d{5})"
    ))
    add_if_found(fields, "Citizen Name", labelled_value(text, r"name"))
    add_if_found(fields, "Date of Birth", labelled_date(text, r"(?:date\s+of\s+birth|dob)"))
    add_if_found(fields, "Gender", labelled_value(text, r"gender|sex"))
    add_if_found(fields, "Address", labelled_value(text, r"address"))
    add_if_found(fields, "District", labelled_value(text, r"district"))
    return fields
