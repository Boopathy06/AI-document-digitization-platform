"""Intelligent document classifier for the document-processing pipeline.

Supports regex, keyword, and bilingual (English/Tamil) detection for Indian
government records, state certificates (Tamil Nadu e-Sevai), and Aadhaar cards.
"""

import re
from dataclasses import dataclass
from typing import List, Tuple


UNKNOWN_DOCUMENT_TYPE = "Unknown"


@dataclass(frozen=True)
class ClassificationResult:
    """The document type selected from OCR text and the matching rule."""

    document_type: str
    matched_keyword: str | None = None


# Classification rules ordered by specificity.
CLASSIFICATION_PATTERNS: List[Tuple[str, List[str]]] = [
    (
        "Income Certificate",
        [
            r"incom[ec]?\s*certifi?[ck]at[eo]?",
            r"வருமான",
            r"annual\s+(?:family\s+)?income",
            r"total\s+annual\s+income",
            r"source\s+of\s+income",
            r"family\s+annual\s+income",
            r"verification\s+is\s+rs\.",
            r"\bTN-4202\d+",
        ],
    ),
    (
        "Birth Certificate",
        [
            r"birth\s*certifi?[ck]at[eo]?",
            r"certificate\s+of\s+birth",
            r"பிறப்பு",
            r"place\s+of\s+birth",
            r"child\s+name",
            r"born\s+on",
        ],
    ),
    (
        "Community Certificate",
        [
            r"communit[ye]\s*certifi?[ck]at[eo]?",
            r"caste\s*certifi?[ck]at[eo]?",
            r"சாதி",
            r"சமூக",
            r"backward\s+class",
            r"most\s+backward\s+class",
            r"scheduled\s+caste",
            r"scheduled\s+tribe",
            r"community\s*[:\-]",
            r"caste\s*[:\-]",
            r"\b(?:BC|MBC|SC|ST)\s*[-:]\s*(?:Backward|Class|Community)",
        ],
    ),
    (
        "Aadhaar Card",
        [
            r"aadha+r",
            r"uidai",
            r"unique\s+identification\s+authority",
            r"ஆதார்",
            r"\b\d{4}\s\d{4}\s\d{4}\b",
            r"help@uidai\.gov\.in",
            r"mera\s+aadhaar",
            r"enrolment\s+no",
        ],
    ),
    (
        "Student Permission Form",
        [
            r"student\s+permission\s+form",
            r"permission\s+details",
            r"permission\s+requested",
            r"kongu\s+engineering\s+college",
        ],
    ),
]


def classify_document(ocr_text: str) -> ClassificationResult:
    """Classify OCR text using resilient pattern rules that tolerate OCR noise."""
    if not ocr_text or not ocr_text.strip():
        return ClassificationResult(UNKNOWN_DOCUMENT_TYPE)

    cleaned_text = ocr_text.strip()

    for document_type, patterns in CLASSIFICATION_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, cleaned_text, flags=re.IGNORECASE):
                return ClassificationResult(document_type, pattern)

    return ClassificationResult(UNKNOWN_DOCUMENT_TYPE)
