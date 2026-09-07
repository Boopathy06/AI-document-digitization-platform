"""Fallback extractor for documents without a dedicated extractor yet."""

from .common import add_if_found, first_match, labelled_date, labelled_value, normalized_lines


def extract_fields(ocr_text: str) -> dict[str, str]:
    """Extract only broadly labelled fields from an unknown document."""
    text = normalized_lines(ocr_text)
    fields: dict[str, str] = {}
    add_if_found(fields, "Citizen Name", labelled_value(text, r"(?:applicant\s+|full\s+)?name"))
    add_if_found(fields, "Date of Birth", labelled_date(text, r"(?:date\s+of\s+birth|dob)"))
    add_if_found(fields, "Certificate Number", labelled_value(
        text, r"(?:certificate|cert(?:ificate)?)\s*(?:number|no\.?|#|id)"
    ))
    add_if_found(fields, "District", labelled_value(text, r"district"))
    add_if_found(fields, "Issue Date", labelled_date(
        text, r"(?:issue(?:d)?\s+date|date\s+of\s+issue|issued\s+on)"
    ))
    add_if_found(fields, "Aadhaar Number", first_match(text, r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"))
    return fields
