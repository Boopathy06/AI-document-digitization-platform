"""Automated test suite for Module 10: PDF Digitization & Multi-Page Document Ingestion."""

import io
import json
import shutil
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pymupdf
from app import create_app
from ocr_service import extract_text
from pdf_service import (
    PDFProcessingError,
    get_pdf_page_count,
    is_pdf,
    render_pdf_to_images,
)


from services.dashboard_service import ensure_dashboard_tables
from services.database_service import initialize_database


def create_sample_pdf(output_path: Path, pages: int = 1) -> Path:
    """Helper to generate a synthetically structured PDF certificate."""
    doc = pymupdf.open()
    
    # Page 1: Standard Tamil Nadu Community Certificate content
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text(
        (50, 100),
        "GOVERNMENT OF TAMIL NADU\n"
        "REVENUE DEPARTMENT\n"
        "COMMUNITY CERTIFICATE\n"
        "Certificate No: TN-5202611094821 Date: 15-04-2024\n"
        "This is to certify that Selvan Boopathy son of Thiru Gopal residing at Door No.2/208\n"
        "Thalakarai, Avinashi Taluk Tiruppur District belongs to Kongu Vellalars Community,\n"
        "which is recognized as a Backward Class.\n"
        "District: Tiruppur",
        fontsize=12,
    )

    # Page 2 (if requested): Attestation & digital signature info
    if pages > 1:
        p2 = doc.new_page(width=595, height=842)
        p2.insert_text(
            (50, 100),
            "OFFICIAL ATTESTATION & VALIDATION\n"
            "This document is electronically verified under e-Sevai.\n"
            "Zonal Deputy Tahsildar, Avinashi.\n"
            "Valid across the State of Tamil Nadu.",
            fontsize=12,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    doc.close()
    return output_path


class TestModule10PDFDigitization(unittest.TestCase):
    """Unit and integration tests for PDF multi-page processing."""

    def setUp(self):
        """Set up isolated test scratch folder and test client."""
        self.test_scratch = BASE_DIR / "tests" / "scratch" / "test_pdf"
        self.test_scratch.mkdir(parents=True, exist_ok=True)
        self.test_db_path = self.test_scratch / "test_documents.db"

        # Initialize schema in test database
        initialize_database(self.test_db_path)
        ensure_dashboard_tables(self.test_db_path)

        # Configure test Flask application
        self.app = create_app()
        self.app.config.update({
            "TESTING": True,
            "DATABASE_PATH": self.test_db_path,
            "UPLOAD_FOLDER": self.test_scratch / "uploads",
            "ENHANCED_FOLDER": self.test_scratch / "enhanced",
            "PDF_PAGES_FOLDER": self.test_scratch / "uploads" / "pdf_pages",
        })
        self.app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
        self.app.config["ENHANCED_FOLDER"].mkdir(parents=True, exist_ok=True)
        self.app.config["PDF_PAGES_FOLDER"].mkdir(parents=True, exist_ok=True)

        self.client = self.app.test_client()

    def tearDown(self):
        """Clean up test scratch files."""
        if self.test_scratch.exists():
            shutil.rmtree(self.test_scratch, ignore_errors=True)

    def test_is_pdf_detection(self):
        """Verify extension checks for PDFs."""
        self.assertTrue(is_pdf("certificate.pdf"))
        self.assertTrue(is_pdf("DOCUMENT.PDF"))
        self.assertTrue(is_pdf(Path("/path/to/file.pdf")))
        self.assertFalse(is_pdf("image.png"))
        self.assertFalse(is_pdf("scan.jpeg"))

    def test_render_single_page_pdf(self):
        """Test rendering single-page PDF to 300 DPI image."""
        pdf_path = self.test_scratch / "test_single.pdf"
        create_sample_pdf(pdf_path, pages=1)

        self.assertEqual(get_pdf_page_count(pdf_path), 1)

        out_dir = self.test_scratch / "pages_single"
        res = render_pdf_to_images(pdf_path, out_dir, dpi=300)

        self.assertEqual(res.total_pages, 1)
        self.assertEqual(len(res.pages), 1)
        self.assertTrue(res.primary_image_path.exists())
        self.assertGreater(res.pages[0].width, 1000)
        self.assertIn("Boopathy", res.combined_embedded_text)

    def test_render_multi_page_pdf(self):
        """Test rendering 2-page PDF document to multiple page images."""
        pdf_path = self.test_scratch / "test_multi.pdf"
        create_sample_pdf(pdf_path, pages=2)

        self.assertEqual(get_pdf_page_count(pdf_path), 2)

        out_dir = self.test_scratch / "pages_multi"
        res = render_pdf_to_images(pdf_path, out_dir, dpi=300)

        self.assertEqual(res.total_pages, 2)
        self.assertEqual(len(res.pages), 2)
        self.assertTrue(res.pages[0].image_path.exists())
        self.assertTrue(res.pages[1].image_path.exists())
        self.assertIn("Boopathy", res.combined_embedded_text)
        self.assertIn("ATTESTATION", res.combined_embedded_text)

    def test_extract_text_native_pdf(self):
        """Verify that extract_text can process a PDF file directly."""
        pdf_path = self.test_scratch / "test_extract.pdf"
        create_sample_pdf(pdf_path, pages=1)

        extracted = extract_text(pdf_path)
        self.assertIn("Boopathy", extracted)
        self.assertIn("Tiruppur", extracted)

    def test_upload_pdf_integration(self):
        """Test full HTTP upload pipeline with a multi-page PDF certificate."""
        pdf_path = self.test_scratch / "upload_test.pdf"
        create_sample_pdf(pdf_path, pages=2)

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        response = self.client.post(
            "/upload",
            data={"document": (io.BytesIO(pdf_bytes), "community_cert.pdf")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("Module 10: Multi-Page PDF Digitization", html)
        self.assertIn("Page 1", html)
        self.assertIn("Page 2", html)
        self.assertIn("Boopathy", html)

    def test_pdf_duplicate_prevention(self):
        """Test that uploading the exact same PDF twice triggers deduplication."""
        pdf_path = self.test_scratch / "dup_test.pdf"
        create_sample_pdf(pdf_path, pages=1)

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        # First upload - should succeed
        r1 = self.client.post(
            "/upload",
            data={"document": (io.BytesIO(pdf_bytes), "sample.pdf")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(r1.status_code, 200)
        self.assertIn("Saved as Record", r1.data.decode("utf-8"))

        # Second upload of same file - duplicate detection triggers
        r2 = self.client.post(
            "/upload",
            data={"document": (io.BytesIO(pdf_bytes), "sample_copy.pdf")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(r2.status_code, 200)
        self.assertIn("Not Saved (Duplicate)", r2.data.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
