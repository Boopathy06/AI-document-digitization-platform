"""Keyword-based document classifier for the document-processing pipeline."""

from dataclasses import dataclass


UNKNOWN_DOCUMENT_TYPE = "Unknown"


@dataclass(frozen=True)
class ClassificationResult:
    """The document type selected from OCR text and the matching keyword."""

    document_type: str
    matched_keyword: str | None = None


# Add a new document type by adding one rule here and, in the next module,
# creating its matching extractor in services/extractors/.
CLASSIFICATION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Aadhaar", ("unique identification authority of india", "aadhaar")),
    ("Community Certificate", ("community certificate", "caste certificate")),
    ("Birth Certificate", ("birth certificate",)),
    ("Income Certificate", ("income certificate",)),
)


def classify_document(ocr_text: str) -> ClassificationResult:
    """Classify OCR text using clear, deterministic keyword rules."""
    normalized_text = ocr_text.casefold()
    for document_type, keywords in CLASSIFICATION_RULES:
        for keyword in keywords:
            if keyword in normalized_text:
                return ClassificationResult(document_type, keyword)
    return ClassificationResult(UNKNOWN_DOCUMENT_TYPE)
