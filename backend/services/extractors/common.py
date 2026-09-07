"""Small reusable helpers for document-specific OCR field extractors."""

import re


DATE_PATTERN = (
    r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{4})"
)


def normalized_lines(text: str) -> str:
    """Clean OCR whitespace while retaining the line structure of labels."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def labelled_value(text: str, label_pattern: str) -> str | None:
    """Find a short value on the same line as a labelled field."""
    match = re.search(
        rf"(?im)^\s*(?:{label_pattern})\s*[:\-]?\s*([^\n]{{2,80}})$",
        text,
    )
    return match.group(1).strip(" :-#") if match else None


def labelled_date(text: str, label_pattern: str) -> str | None:
    """Find a date near a date-related field label."""
    match = re.search(
        rf"(?is)(?:{label_pattern})\s*[:\-]?\s*[^\n]{{0,20}}?({DATE_PATTERN})",
        text,
    )
    return match.group(1).strip() if match else None


def first_match(text: str, pattern: str) -> str | None:
    """Return the first matched group, or the whole match if there is no group."""
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return (match.group(1) if match.lastindex else match.group(0)).strip()


def add_if_found(fields: dict[str, str], field_name: str, value: str | None) -> None:
    """Only include reliable, non-empty values in the displayed result."""
    if value:
        fields[field_name] = value
