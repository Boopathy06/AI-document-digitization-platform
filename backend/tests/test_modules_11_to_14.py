"""Comprehensive test suite for Modules 11 to 14:
- Module 11: Explainable OCR Validation & Human Review
- Module 12: Advanced Duplicate Detection
- Module 13: Document Consistency Verification
- Module 14: Document Quality and Completeness Score
"""

import json
import shutil
import sys
import unittest
from pathlib import Path
from uuid import uuid4

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app
from quality_service import QualityAssessment
from services.consistency_service import (
    REQUIRED_FIELDS_BY_TYPE,
    verify_document_consistency,
)
from services.dashboard_service import get_all_documents, get_dashboard_stats
from services.database_service import get_connection, initialize_database, save_document
from services.duplicate_checker import check_advanced_duplicates
from services.quality_score_service import calculate_document_quality_score
from services.verification_service import (
    analyze_document_fields,
    apply_field_corrections,
    get_document_verification_details,
    validate_certificate_number,
)


class TestModules11To14(unittest.TestCase):
    """Test suite covering the 10 required verification scenarios for Modules 11–14."""

    def setUp(self):
        """Set up isolated test database and test Flask client."""
        self.test_dir = BASE_DIR / "tests" / "scratch" / f"test_suite_{uuid4().hex[:8]}"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test_platform.db"

        initialize_database(self.test_db)

        self.app = create_app()
        self.app.config.update({
            "TESTING": True,
            "DATABASE_PATH": self.test_db,
            "UPLOAD_FOLDER": self.test_dir / "uploads",
        })
        self.app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
        self.client = self.app.test_client()

    def tearDown(self):
        """Clean up scratch directory."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_clear_document_with_all_required_fields(self):
        """Test 1: Clear document with all required fields (Passes consistency and scores high)."""
        fields = {
            "Citizen Name": "Senthil Nathan",
            "Certificate Number": "TN-4202807036380",
            "Annual Income": "Rs. 78,000",
            "District": "Tiruppur",
            "Taluk": "Avinashi",
            "Issue Date": "11-07-2023",
        }
        # Module 13 Consistency
        c_report = verify_document_consistency(0, "Income Certificate", fields, database_path=self.test_db)
        self.assertEqual(c_report.overall_status, "Passed")
        self.assertEqual(c_report.failed_count, 0)

        # Module 14 Quality Score with high quality & clear image
        quality_mock = QualityAssessment(
            blur_score=145.0,
            blur_status="Clear",
            brightness_score=130.0,
            brightness_status="Good",
            skew_angle=0.4,
            rotation_status="Good",
        )
        q_report = calculate_document_quality_score(
            "Income Certificate",
            fields,
            quality_assessment=quality_mock,
            ocr_confidence=0.96,
        )
        self.assertGreaterEqual(q_report.overall_score, 85.0)
        self.assertEqual(q_report.category, "Good quality and completeness")
        self.assertEqual(len(q_report.missing_required_fields), 0)

    def test_02_blurry_document_with_low_ocr_confidence(self):
        """Test 2: Blurry document with low OCR confidence reduces score and flags review."""
        fields = {
            "Citizen Name": "Gopal N",
            "Certificate Number": "TN-4202807036380",
            "Annual Income": "Rs. 78,000",
            "District": "Tiruppur",
        }
        blurry_mock = QualityAssessment(
            blur_score=25.0,  # Below threshold 80
            blur_status="Blurry",
            brightness_score=45.0,  # Too dark
            brightness_status="Too dark",
            skew_angle=6.2,  # Skewed
            rotation_status="Skewed",
        )
        q_report = calculate_document_quality_score(
            "Income Certificate",
            fields,
            quality_assessment=blurry_mock,
            ocr_confidence=0.42,  # Low OCR confidence
        )
        self.assertLess(q_report.overall_score, 65.0)
        self.assertEqual(q_report.category, "Manual review strongly recommended")
        self.assertTrue(any("blur" in factor.lower() for factor in q_report.score_reduction_factors))
        self.assertTrue(any("confidence is low" in factor.lower() for factor in q_report.score_reduction_factors))

    def test_03_document_with_missing_required_fields(self):
        """Test 3: Missing required fields triggers Failed consistency and lists missing fields."""
        incomplete_fields = {
            "Citizen Name": "Boopathy",
            # Missing Certificate Number and District
        }
        c_report = verify_document_consistency(0, "Community Certificate", incomplete_fields)
        self.assertEqual(c_report.overall_status, "Failed")
        self.assertTrue(c_report.failed_count >= 1)
        self.assertIn("Certificate Number", c_report.field_results)
        self.assertEqual(c_report.field_results["Certificate Number"].validation_status, "Failed")

        # Module 14 score reduction
        q_report = calculate_document_quality_score("Community Certificate", incomplete_fields)
        self.assertIn("Certificate Number", q_report.missing_required_fields)
        self.assertLess(q_report.field_completeness_score, 50.0)

    def test_04_document_with_invalid_date_or_identifier_format(self):
        """Test 4: Invalid date format and corrupt certificate number are flagged."""
        corrupt_fields = {
            "Citizen Name": "Ramesh",
            "Certificate Number": "TN18B?56",  # Uncertain character ?
            "Date of Birth": "35-14-2022",  # Invalid calendar day/month
            "PAN Number": "INVALID_PAN",  # Bad format
        }
        c_report = verify_document_consistency(0, "PAN Card", corrupt_fields)
        self.assertIn("Date of Birth", c_report.field_results)
        self.assertEqual(c_report.field_results["Date of Birth"].validation_status, "Failed")

        # Module 11 check on uncertain character
        cert_info = validate_certificate_number("TN18B?56", "REVENUE TN18B?56")
        self.assertTrue(cert_info.is_flagged)
        self.assertTrue(any("?" in r for r in cert_info.issue_reasons))

    def test_05_possible_duplicate_detection(self):
        """Test 5: Fuzzy matching detects possible duplicate when name and date/district match."""
        # 1. Seed existing record
        save_document(
            self.test_db,
            document_type="Community Certificate",
            extracted_fields={
                "Citizen Name": "Boopathy G",
                "Certificate Number": "TN-5201912057677",
                "District": "Tiruppur",
                "Issue Date": "09-12-2019",
            },
            ocr_text="COMMUNITY CERTIFICATE Selvan Boopathy G son of Thiru Gopal",
            file_path="uploads/seed1.png",
        )

        # 2. Upload candidate with slight name difference (honorific title, same date and district)
        candidate_fields = {
            "Citizen Name": "Selvan Boopathy",
            "Certificate Number": "TN-DIFF-CERT-8899",
            "District": "Tiruppur",
            "Issue Date": "09-12-2019",
        }
        report = check_advanced_duplicates(candidate_fields, self.test_db)
        self.assertEqual(report.status, "Possible Duplicate")
        self.assertEqual(len(report.matches), 1)
        self.assertGreaterEqual(report.matches[0].similarity_score, 85.0)
        self.assertTrue(any("name" in m.lower() for m in report.matches[0].matched_fields))

    def test_06_no_likely_duplicate_found(self):
        """Test 6: Distinct record returns No Likely Duplicate Found."""
        save_document(
            self.test_db,
            document_type="Aadhaar Card",
            extracted_fields={
                "Citizen Name": "Kavitha Sundaram",
                "Aadhaar Number": "9988 7766 5544",
                "District": "Chennai",
            },
            ocr_text="Aadhaar Kavitha Sundaram",
            file_path="uploads/seed2.png",
        )

        candidate_fields = {
            "Citizen Name": "Anand Prakash",
            "Certificate Number": "TN-NEW-9999",
            "District": "Madurai",
            "Issue Date": "15-05-2023",
        }
        report = check_advanced_duplicates(candidate_fields, self.test_db)
        self.assertEqual(report.status, "No Likely Duplicate Found")
        self.assertEqual(len(report.matches), 0)

    def test_07_human_review_and_corrections_workflow(self):
        """Test 7: Extracted values corrected by reviewer are saved in audit history."""
        doc_id = save_document(
            self.test_db,
            document_type="Community Certificate",
            extracted_fields={
                "Citizen Name": "Boopathy",
                "Certificate Number": "TN18B?56",
                "District": "Tiruppur",
            },
            ocr_text="COMMUNITY CERTIFICATE CertificateNo: TN18B?56",
            file_path="uploads/sample_review.png",
        )

        # Apply correction via service
        updated_report = apply_field_corrections(
            self.test_db,
            doc_id=doc_id,
            corrected_fields={"Certificate Number": "TN-5201912057677"},
            reviewer_name="Inspector Anitha",
            notes="Corrected '?' to standard digit '0'",
        )
        self.assertEqual(updated_report.overall_status, "manually_verified")
        self.assertEqual(updated_report.verified_by, "Inspector Anitha")

        # Verify audit history is logged
        details = get_document_verification_details(self.test_db, doc_id)
        self.assertEqual(len(details.correction_history), 1)
        audit_entry = details.correction_history[0]
        self.assertEqual(audit_entry["field_name"], "Certificate Number")
        self.assertEqual(audit_entry["old_value"], "TN18B?56")
        self.assertEqual(audit_entry["new_value"], "TN-5201912057677")
        self.assertEqual(audit_entry["corrected_by"], "Inspector Anitha")

    def test_08_unavailable_ocr_confidence_and_image_quality(self):
        """Test 8: Gracefully normalizes weights when image quality and OCR confidence are unavailable."""
        fields = {
            "Citizen Name": "Boopathy",
            "Certificate Number": "TN-4202807036380",
            "Annual Income": "Rs. 78,000",
            "District": "Tiruppur",
        }
        # Pass None for quality assessment and OCR confidence
        q_report = calculate_document_quality_score(
            "Income Certificate",
            fields,
            quality_assessment=None,
            ocr_confidence=None,
        )
        self.assertIsNone(q_report.image_quality_score)
        self.assertIsNone(q_report.ocr_confidence_score)
        # Weight should be normalized 100% to completeness
        self.assertEqual(q_report.weights_used["field_completeness"], 1.0)
        self.assertEqual(q_report.overall_score, 100.0)

    def test_09_api_endpoints_and_error_handling(self):
        """Test 9: Invalid requests and verification endpoints return proper HTTP statuses."""
        doc_id = save_document(
            self.test_db,
            document_type="Birth Certificate",
            extracted_fields={
                "Citizen Name": "Baby Kavya",
                "Certificate Number": "BC-2024-001",
                "Date of Birth": "10-01-2024",
                "Father's Name": "Suresh",
            },
            ocr_text="BIRTH CERTIFICATE Baby Kavya Suresh",
            file_path="uploads/birth.jpg",
        )

        # Consistency GET endpoint
        res_c = self.client.get(f"/api/document/{doc_id}/consistency")
        self.assertEqual(res_c.status_code, 200)
        self.assertEqual(res_c.get_json()["overall_status"], "Passed")

        # Duplicates GET endpoint
        res_d = self.client.get(f"/api/document/{doc_id}/duplicates")
        self.assertEqual(res_d.status_code, 200)

        # Quality Score GET endpoint
        res_q = self.client.get(f"/api/document/{doc_id}/quality-score")
        self.assertEqual(res_q.status_code, 200)

        # Non-existent document 404 test
        res_404 = self.client.get("/api/document/99999/verification")
        self.assertEqual(res_404.status_code, 404)

        # Mark reviewed POST endpoint
        res_mr = self.client.post(
            f"/api/document/{doc_id}/mark-reviewed",
            data=json.dumps({"reviewer_name": "Supervisor Nathan"}),
            content_type="application/json",
        )
        self.assertEqual(res_mr.status_code, 200)
        self.assertEqual(res_mr.get_json()["overall_status"], "reviewed")

    def test_10_revalidation_after_corrections(self):
        """Test 10: Revalidating after correction recalculates status without errors."""
        doc_id = save_document(
            self.test_db,
            document_type="Community Certificate",
            extracted_fields={
                "Citizen Name": "Boopathy",
                "Certificate Number": "TN18B?56",
                "District": "Tiruppur",
            },
            ocr_text="COMMUNITY CERTIFICATE TN18B?56",
            file_path="uploads/reval.jpg",
        )
        res_reval = self.client.post(f"/api/document/{doc_id}/revalidate")
        self.assertEqual(res_reval.status_code, 200)
        data = res_reval.get_json()
        self.assertTrue(data["success"])
        self.assertIn("consistency", data)
        self.assertIn("verification", data)
        self.assertIn("quality", data)


if __name__ == "__main__":
    unittest.main()
