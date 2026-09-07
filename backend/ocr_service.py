"""EasyOCR text extraction service for Module 2."""

from functools import lru_cache
from pathlib import Path

import easyocr


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
OCR_LANGUAGES = ["en", "ta"]
MINIMUM_CONFIDENCE = 0.35
EASYOCR_MODEL_FOLDER = Path.home() / ".EasyOCR" / "model"
TAMIL_MODEL_FILE = EASYOCR_MODEL_FOLDER / "tamil.pth"


class OCRProcessingError(Exception):
    """Raised when a document cannot be processed by the OCR service."""


@lru_cache(maxsize=1)
def get_reader() -> easyocr.Reader:
    """Create the best available reader once, with an offline-safe fallback."""
    if not TAMIL_MODEL_FILE.exists():
        return easyocr.Reader(["en"], gpu=False)

    try:
        return easyocr.Reader(OCR_LANGUAGES, gpu=False)
    except Exception:
        # The Tamil model is downloaded by EasyOCR on first use. Keep English
        # OCR functional when that download is unavailable (for example offline).
        return easyocr.Reader(["en"], gpu=False)


def extract_text(document_path: str | Path) -> str:
    """Extract all detected English text from an uploaded image.

    EasyOCR natively accepts image files. PDF rendering is deliberately kept out
    of this module and will be added as a separate conversion step later.
    """
    path = Path(document_path)
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise OCRProcessingError(
            "OCR currently supports PNG, JPG, and JPEG files. "
            "PDF-to-image conversion will be added in a later module."
        )

    try:
        detected_lines = get_reader().readtext(
            str(path),
            detail=1,
            paragraph=False,
            canvas_size=3200,
            contrast_ths=0.05,
            adjust_contrast=0.7,
            text_threshold=0.6,
            low_text=0.4,
        )
    except Exception as error:
        raise OCRProcessingError("Unable to read text from this image.") from error

    recognised_text = [
        text.strip()
        for _bounding_box, text, confidence in detected_lines
        if confidence >= MINIMUM_CONFIDENCE and text.strip()
    ]
    return "\n".join(recognised_text)
