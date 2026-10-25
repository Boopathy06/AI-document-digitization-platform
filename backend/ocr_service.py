"""PaddleOCR (with EasyOCR fallback) text extraction service for Module 2.

Extracts text with spatial line sorting and confidence filtering tailored for
printed documents, handwritten forms, and bilingual government certificates.
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import easyocr
except ImportError:
    easyocr = None


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
OCR_LANGUAGES = ["en", "ta"]
MINIMUM_CONFIDENCE = 0.12
EASYOCR_MODEL_FOLDER = Path.home() / ".EasyOCR" / "model"
TAMIL_MODEL_FILE = EASYOCR_MODEL_FOLDER / "tamil.pth"


class OCRProcessingError(Exception):
    """Raised when a document cannot be processed by the OCR service."""


@lru_cache(maxsize=1)
def get_paddle_ocr():
    """Initialize PaddleOCR engine with Windows shm.dll safety and CPU batch efficiency."""
    try:
        import torch  # Prevents Windows PyTorch / Paddle OpenMP conflict
        from paddleocr import PaddleOCR
        return PaddleOCR(
            use_angle_cls=True,
            lang="en",
            use_gpu=False,
            show_log=False,
            det_limit_side_len=1600,
            rec_batch_num=16,
        )
    except Exception:
        return None


@lru_cache(maxsize=1)
def get_reader():
    """Create the best available EasyOCR reader once, with an offline-safe fallback."""
    if easyocr is None:
        return None
    if TAMIL_MODEL_FILE.exists():
        try:
            return easyocr.Reader(OCR_LANGUAGES, gpu=False)
        except Exception:
            pass
    try:
        return easyocr.Reader(["en"], gpu=False)
    except Exception:
        return None


SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}


def extract_text_and_confidence(document_path: str | Path) -> Tuple[str, Optional[float]]:
    """Extract text and return both the formatted string and the average OCR confidence."""
    path = Path(document_path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise OCRProcessingError(
            f"Unsupported file format '{suffix}'. Supported formats are: PNG, JPG, JPEG, and PDF."
        )

    # Multi-page PDF Handling (Module 10)
    if suffix == ".pdf":
        try:
            from pdf_service import render_pdf_to_images
            temp_out = path.parent / "pdf_pages" / path.stem
            pdf_result = render_pdf_to_images(path, temp_out, dpi=200)
            page_text_blocks: List[str] = []
            CERT_KEYWORDS = (
                "certificate", "certify", "income", "community", "birth", "death",
                "aadhaar", "unique identification", "pan card", "driving licence", "license",
                "son of", "daughter of", "wife of", "residing", "resident", "tahsildar",
                "government", "revenue", "department"
            )
            for page in pdf_result.pages:
                raw_emb = (page.embedded_text or "").strip()
                has_rich_text = (
                    len(raw_emb) >= 150
                    and sum(1 for kw in CERT_KEYWORDS if kw in raw_emb.lower()) >= 2
                )
                if has_rich_text:
                    text_piece = raw_emb
                else:
                    text_piece = extract_text(page.image_path)
                    if raw_emb and text_piece and raw_emb not in text_piece:
                        text_piece = text_piece + "\n" + raw_emb
                    elif not text_piece and raw_emb:
                        text_piece = raw_emb
                if text_piece:
                    page_text_blocks.append(text_piece)

            if not page_text_blocks and pdf_result.combined_embedded_text:
                return pdf_result.combined_embedded_text, 0.95

            return "\n\n".join(page_text_blocks), 0.90
        except Exception as error:
            raise OCRProcessingError(f"Failed to process PDF pages for OCR: {error}") from error

    valid_items: List[Tuple] = []

    # 1. Primary Engine: PaddleOCR
    paddle_engine = get_paddle_ocr()
    if paddle_engine is not None:
        try:
            paddle_res = paddle_engine.ocr(str(path), cls=True)
            if paddle_res and paddle_res[0]:
                for line in paddle_res[0]:
                    if line and len(line) >= 2 and line[1]:
                        text_val = str(line[1][0]).strip()
                        conf_val = float(line[1][1])
                        if text_val and conf_val >= MINIMUM_CONFIDENCE:
                            valid_items.append((line[0], text_val, conf_val))
        except Exception:
            valid_items = []

    # 2. Fallback Engine: EasyOCR
    if not valid_items:
        try:
            reader = get_reader()
            if reader is not None:
                detected_items = reader.readtext(
                    str(path),
                    detail=1,
                    paragraph=False,
                    min_size=5,
                    text_threshold=0.35,
                    low_text=0.25,
                    link_threshold=0.4,
                    contrast_ths=0.1,
                    adjust_contrast=0.6,
                )
                valid_items = [
                    item for item in detected_items
                    if item[2] >= MINIMUM_CONFIDENCE and item[1].strip()
                ]
        except Exception as error:
            if not valid_items:
                raise OCRProcessingError("Unable to read text from this image.") from error

    if not valid_items:
        return "", None

    avg_conf = sum(item[2] for item in valid_items) / len(valid_items)
    sorted_text_lines = sort_boxes_into_lines(valid_items)
    return "\n".join(sorted_text_lines), avg_conf


def extract_text(document_path: str | Path) -> str:
    """Extract all detected text with reading-order layout and confidence filtering.
    
    Uses PaddleOCR as primary engine for high accuracy on printed & handwritten text,
    with automatic fallback to EasyOCR. Supports multi-page PDF documents via rasterization.
    """
    text, _ = extract_text_and_confidence(document_path)
    return text



def sort_boxes_into_lines(items: List[Tuple]) -> List[str]:
    """Group bounding boxes by vertical line and sort left-to-right."""
    # Box coordinates: [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    parsed = []
    for box, text, conf in items:
        cy = (box[0][1] + box[2][1]) / 2.0
        cx = (box[0][0] + box[1][0]) / 2.0
        height = abs(box[2][1] - box[0][1])
        parsed.append({"cy": cy, "cx": cx, "h": height, "text": text.strip()})

    # Sort primarily by vertical center
    parsed.sort(key=lambda p: p["cy"])

    lines: List[List[dict]] = []
    for item in parsed:
        placed = False
        for line in lines:
            line_avg_cy = sum(el["cy"] for el in line) / len(line)
            line_avg_h = sum(el["h"] for el in line) / len(line)
            # If vertical distance is within 60% of average line height, group on same line
            if abs(item["cy"] - line_avg_cy) < max(14.0, line_avg_h * 0.65):
                line.append(item)
                placed = True
                break
        if not placed:
            lines.append([item])

    result_lines: List[str] = []
    for line in lines:
        # Sort words in line from left to right
        line.sort(key=lambda el: el["cx"])
        line_str = " ".join(el["text"] for el in line)
        if line_str:
            result_lines.append(line_str)

    return result_lines
