"""PDF Document Processing & Multi-Page Digitization Service for Module 10.

Converts multi-page government PDF files into high-resolution images (300 DPI)
for quality assessment, enhancement, OCR text extraction, and structured field parsing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymupdf

logger = logging.getLogger(__name__)


class PDFProcessingError(Exception):
    """Raised when PDF conversion, reading, or multi-page rendering fails."""


@dataclass
class PDFPageInfo:
    """Information and rendered assets for an individual PDF page."""

    page_number: int  # 1-indexed
    image_path: Path
    relative_image_path: str
    width: int
    height: int
    dpi: int
    embedded_text: str = ""


@dataclass
class PDFDocumentResult:
    """Comprehensive multi-page extraction result from a PDF document."""

    pdf_path: Path
    total_pages: int
    pages: List[PDFPageInfo] = field(default_factory=list)
    primary_image_path: Optional[Path] = None
    relative_primary_image_path: Optional[str] = None
    combined_embedded_text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


def is_pdf(file_path: str | Path) -> bool:
    """Return True if the file has a .pdf extension."""
    return Path(file_path).suffix.lower() == ".pdf"


def get_pdf_page_count(pdf_path: str | Path) -> int:
    """Return total number of pages in the PDF file."""
    path = Path(pdf_path)
    if not path.is_file():
        raise PDFProcessingError(f"PDF file does not exist: {path}")

    try:
        with pymupdf.open(str(path)) as doc:
            return len(doc)
    except Exception as error:
        raise PDFProcessingError(f"Could not open PDF file to count pages: {error}") from error


def render_pdf_to_images(
    pdf_path: str | Path,
    output_dir: str | Path,
    dpi: int = 300,
    max_pages: Optional[int] = None,
) -> PDFDocumentResult:
    """Render all pages of a PDF to high-resolution PNG images at specified DPI.

    Args:
        pdf_path: Path to the source PDF file.
        output_dir: Directory where rendered page images will be stored.
        dpi: Target DPI for rasterization (300 DPI recommended for OCR).
        max_pages: Optional limit on the number of pages to process.

    Returns:
        PDFDocumentResult containing page metadata, paths, and embedded text.
    """
    path = Path(pdf_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not path.is_file():
        raise PDFProcessingError(f"PDF document not found: {path}")

    try:
        doc = pymupdf.open(str(path))
    except Exception as error:
        raise PDFProcessingError(f"Failed to read PDF file '{path.name}': {error}") from error

    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
        raise PDFProcessingError(f"PDF document '{path.name}' contains zero pages.")

    pages_to_render = total_pages if max_pages is None else min(total_pages, max_pages)
    rendered_pages: List[PDFPageInfo] = []
    combined_embedded_parts: List[str] = []
    meta = doc.metadata or {}

    stem = path.stem

    for page_idx in range(pages_to_render):
        page_num = page_idx + 1
        page = doc[page_idx]

        # 1. Extract any embedded vector / selectable text
        page_text = page.get_text("text").strip()
        if page_text:
            combined_embedded_parts.append(page_text)

        # 2. Render page to high-resolution pixmap
        # Standard PDF points are 72 DPI. Target DPI zoom = dpi / 72.
        zoom = dpi / 72.0
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        page_filename = f"{stem}_page_{page_num}.png"
        page_path = out_dir / page_filename
        pix.save(str(page_path))

        rendered_pages.append(
            PDFPageInfo(
                page_number=page_num,
                image_path=page_path,
                relative_image_path=f"pdf_pages/{page_filename}",
                width=pix.width,
                height=pix.height,
                dpi=dpi,
                embedded_text=page_text,
            )
        )

    doc.close()

    primary_image = rendered_pages[0].image_path if rendered_pages else None
    relative_primary = rendered_pages[0].relative_image_path if rendered_pages else None

    return PDFDocumentResult(
        pdf_path=path,
        total_pages=total_pages,
        pages=rendered_pages,
        primary_image_path=primary_image,
        relative_primary_image_path=relative_primary,
        combined_embedded_text="\n\n".join(combined_embedded_parts),
        metadata={
            "format": meta.get("format", "PDF"),
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "creator": meta.get("creator", ""),
            "creationDate": meta.get("creationDate", ""),
            "page_count": total_pages,
        },
    )
