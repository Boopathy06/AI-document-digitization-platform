"""Field extraction rules specific to community certificates."""

from .common import add_if_found, labelled_date, labelled_value, normalized_lines


def extract_fields(ocr_text: str) -> dict[str, str]:
    """Extract the holder, certificate, community, and district details."""
    text = normalized_lines(ocr_text)
    fields: dict[str, str] = {}
    add_if_found(fields, "Citizen Name", labelled_value(text, r"(?:applicant\s+)?name"))
    add_if_found(fields, "Certificate Number", labelled_value(
        text, r"(?:certificate|community)\s*(?:number|no\.?|#)"
    ))
    add_if_found(fields, "Community", labelled_value(text, r"(?:community|caste)"))
    add_if_found(fields, "District", labelled_value(text, r"district"))
    add_if_found(fields, "Issue Date", labelled_date(text, r"(?:issue(?:d)?\s+date|date\s+of\s+issue)"))
    return fields
