"""Field extraction rules specific to birth certificates."""

from .common import add_if_found, labelled_date, labelled_value, normalized_lines


def extract_fields(ocr_text: str) -> dict[str, str]:
    """Extract child, registration, location, and issue details."""
    text = normalized_lines(ocr_text)
    fields: dict[str, str] = {}
    add_if_found(fields, "Citizen Name", labelled_value(text, r"(?:child'?s?\s+)?name"))
    add_if_found(fields, "Date of Birth", labelled_date(text, r"(?:date\s+of\s+birth|dob)"))
    add_if_found(fields, "Certificate Number", labelled_value(
        text, r"(?:certificate|registration)\s*(?:number|no\.?|#)"
    ))
    add_if_found(fields, "Place of Birth", labelled_value(text, r"place\s+of\s+birth"))
    add_if_found(fields, "District", labelled_value(text, r"district"))
    add_if_found(fields, "Issue Date", labelled_date(text, r"(?:issue(?:d)?\s+date|date\s+of\s+issue)"))
    return fields
