"""Automated test suite for Module 11: OCR-Aware Smart Verification & Field Correction Interface."""

import json
import shutil
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app
from services.dashboard_service import ensure_dashboard_tables, get_all_documents, get_dashboard_stats
from services.database_service import get_connection, initialize_database, save_document
from services.verification_service import (
    analyze_document_fields,
    apply_field_corrections,
    ensure_verification_schema,
    get_document_verification_details,
    validate_certificate_number,
    validate_person_name,
)


class TestModule11SmartVerification(unittest.TestCase):
    """Test suite for OCR uncertainty detection, verification scoring, and correction workflow."""

    def setUp(self):
        """Set up test environment and isolate test database."""
        self.test_dir = BASE_DIR / "tests" / "scratch" / "test_module11"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test_verification.db"

        initialize_database(self.test_db)
        ensure_dashboard_tables(self.test_db)
        ensure_verification_schema(self.test_db)

        self.app = create_app()
        self.app.config.update({
            "TESTING": True,
            "DATABASE_PATH": self.test_db,
            "UPLOAD_FOLDER": self.test_dir / "uploads",
        })
        self.app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
        self.client = self.app.test_client()

    def tearDown(self):
        """Clean up test artifacts."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_flag_uncertain_characters_in_certificate_number(self):
        """Test user-specified scenario: Certificate number TN18B?56 flagged due to uncertain '?'."""
        raw_ocr = "REVENUE DEPARTMENT COMMUNITY CERTIFICATE rmTr/CertificateNo: TN18B?56 Date: 12-05-2022"
        info = validate_certificate_number("TN18B?56", raw_ocr)

        self.assertTrue(info.is_flagged)
        self.assertLess(info.confidence_score, 0.8)
        self.assertTrue(any("?" in reason for reason in info.issue_reasons))
        self.assertIn("TN18B?56", info.ocr_context)

    def test_clean_document_auto_verified(self):
        """Test that documents with clean syntax and valid fields are marked auto_verified."""
        extracted = {
            "Citizen Name": "Boopathy",
            "Certificate Number": "TN-5201912057677",
            "District": "Tiruppur",
            "Issue Date": "09-12-2019",
        }
        raw_ocr = "COMMUNITY CERTIFICATE CertificateNo:TN-5201912057677 Selvan Boopathy District Tiruppur Date:09-12-2019"

        report = analyze_document_fields(
            doc_id=1,
            document_type="Community Certificate",
            extracted_fields=extracted,
            ocr_text=raw_ocr,
        )

        self.assertEqual(report.overall_status, "auto_verified")
        self.assertEqual(report.flagged_fields_count, 0)
        self.assertFalse(report.fields["Certificate Number"].is_flagged)
        self.assertFalse(report.fields["Citizen Name"].is_flagged)

    def test_save_document_initializes_needs_review_status(self):
        """Test that uploading a document with uncertain OCR creates a record with 'needs_review'."""
        doc_id = save_document(
            self.test_db,
            document_type="Community Certificate",
            extracted_fields={
                "Citizen Name": "Boopathy",
                "Certificate Number": "TN18B?56",  # Uncertain OCR
                "District": "Tiruppur",
            },
            ocr_text="COMMUNITY CERTIFICATE CertificateNo: TN18B?56 Selvan Boopathy",
            file_path="uploads/sample_uncertain.png",
        )

        report = get_document_verification_details(self.test_db, doc_id)
        self.assertIsNotNone(report)
        self.assertEqual(report.overall_status, "needs_review")
        self.assertTrue(report.fields["Certificate Number"].is_flagged)

    def test_apply_field_corrections_and_audit_log(self):
        """Test reviewer manual field correction: changes value, marks manually_verified, logs audit."""
        doc_id = save_document(
            self.test_db,
            document_type="Community Certificate",
            extracted_fields={
                "Citizen Name": "Boopathy",
                "Certificate Number": "TN18B?56",
                "District": "Tiruppur",
            },
            ocr_text="COMMUNITY CERTIFICATE CertificateNo: TN18B?56 Selvan Boopathy",
            file_path="uploads/sample_uncertain.png",
        )

        # Reviewer corrects TN18B?56 to TN-5201912057677
        updated_report = apply_field_corrections(
            self.test_db,
            doc_id=doc_id,
            corrected_fields={
                "Certificate Number": "TN-5201912057677",
                "Citizen Name": "Boopathy",
            },
            reviewer_name="Officer Ramesh",
            notes="Checked against physical revenue stamp; resolved OCR uncertainty '?' to TN-5201912057677",
        )

        self.assertEqual(updated_report.overall_status, "manually_verified")
        self.assertEqual(updated_report.verified_by, "Officer Ramesh")

        # Verify audit logs in database
        with get_connection(self.test_db) as conn:
            row = conn.execute(
                "SELECT certificate_number, verification_status, verified_by FROM government_documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
            self.assertEqual(row["certificate_number"], "TN-5201912057677")
            self.assertEqual(row["verification_status"], "manually_verified")
            self.assertEqual(row["verified_by"], "Officer Ramesh")

            # Check audit log entry
            audit = conn.execute(
                "SELECT * FROM verification_audit_logs WHERE document_id = ? AND field_name = 'Certificate Number'",
                (doc_id,),
            ).fetchone()
            self.assertIsNotNone(audit)
            self.assertEqual(audit["old_value"], "TN18B?56")
            self.assertEqual(audit["new_value"], "TN-5201912057677")
            self.assertEqual(audit["corrected_by"], "Officer Ramesh")

    def test_api_verification_endpoints(self):
        """Test GET and POST API endpoints for verification and human-in-the-loop correction."""
        doc_id = save_document(
            self.test_db,
            document_type="Community Certificate",
            extracted_fields={
                "Citizen Name": "Boopathy",
                "Certificate Number": "TN18B?56",
                "District": "Tiruppur",
            },
            ocr_text="COMMUNITY CERTIFICATE CertificateNo: TN18B?56 Selvan Boopathy",
            file_path="uploads/sample.png",
        )

        # 1. GET /api/document/<id>/verification
        res_get = self.client.get(f"/api/document/{doc_id}/verification")
        self.assertEqual(res_get.status_code, 200)
        data = res_get.get_json()
        self.assertEqual(data["overall_status"], "needs_review")
        self.assertTrue(data["fields"]["Certificate Number"]["is_flagged"])
        self.assertIn("Certificate Number", data["fields"])

        # 2. POST /api/document/<id>/verify
        payload = {
            "corrections": {
                "Certificate Number": "TN-5201912057677",
                "Citizen Name": "Boopathy G",
            },
            "reviewer_name": "Supervisor Priya",
            "notes": "Verified against seal",
        }
        res_post = self.client.post(
            f"/api/document/{doc_id}/verify",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res_post.status_code, 200)
        post_data = res_post.get_json()
        self.assertTrue(post_data["success"])
        self.assertEqual(post_data["overall_status"], "manually_verified")

        # 3. Verify GET returns updated status
        res_get_updated = self.client.get(f"/api/document/{doc_id}/verification")
        updated_data = res_get_updated.get_json()
        self.assertEqual(updated_data["overall_status"], "manually_verified")
        self.assertEqual(updated_data["verified_by"], "Supervisor Priya")
        self.assertEqual(len(updated_data["correction_history"]), 2)  # Cert number + citizen name changed

    def test_dashboard_filtering_by_status(self):
        """Test dashboard query filtering for needs_review and verified status."""
        # Clean document
        save_document(
            self.test_db,
            document_type="Income Certificate",
            extracted_fields={
                "Citizen Name": "Senthil Nathan",
                "Certificate Number": "TN-REV-INC-2026-0814",
                "District": "Salem",
            },
            ocr_text="INCOME CERTIFICATE TN-REV-INC-2026-0814 Senthil Nathan Salem",
            file_path="uploads/clean.jpg",
        )

        # Flagged document
        save_document(
            self.test_db,
            document_type="Community Certificate",
            extracted_fields={
                "Citizen Name": "Boopathy",
                "Certificate Number": "TN18B?56",
                "District": "Tiruppur",
            },
            ocr_text="COMMUNITY CERTIFICATE CertificateNo: TN18B?56",
            file_path="uploads/flagged.jpg",
        )

        stats = get_dashboard_stats(self.test_db)
        self.assertEqual(stats["total_documents"], 2)
        self.assertEqual(stats["pending_verification"], 1)
        self.assertEqual(stats["verified_documents"], 1)

        # Filter by needs_review
        docs_review, count_review = get_all_documents(self.test_db, verification_status="needs_review")
        self.assertEqual(count_review, 1)
        self.assertEqual(docs_review[0]["verification_status"], "needs_review")

        # Filter by verified
        docs_verified, count_verified = get_all_documents(self.test_db, verification_status="verified")
        self.assertEqual(count_verified, 1)
        self.assertEqual(docs_verified[0]["verification_status"], "auto_verified")


if __name__ == "__main__":
    unittest.main()
