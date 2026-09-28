"""Automated verification suite for Module 8: Interactive Dashboard."""

import sys
import unittest
from pathlib import Path
from uuid import uuid4

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app
from services.dashboard_service import (
    ensure_dashboard_tables,
    get_all_documents,
    get_dashboard_stats,
    get_distinct_districts,
    get_distinct_document_types,
    get_document_by_id,
    log_duplicate_attempt,
)
from services.database_service import initialize_database, save_document


class TestModule8Dashboard(unittest.TestCase):
    """Test dashboard service and web routes for Module 8."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = BASE_DIR / "tests" / "scratch"
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        cls.test_db = cls.test_dir / f"test_{uuid4().hex}.db"

        initialize_database(cls.test_db)
        ensure_dashboard_tables(cls.test_db)

        # Seed sample documents
        cls.doc1_id = save_document(
            cls.test_db,
            document_type="Income Certificate",
            extracted_fields={
                "Citizen Name": "Ramesh Kumar",
                "Certificate Number": "INC/2026/001",
                "District": "Salem",
                "Annual Income": "120000",
            },
            ocr_text="GOVERNMENT OF TAMIL NADU REVENUE DEPARTMENT INCOME CERTIFICATE Ramesh Kumar Salem",
            file_path="uploads/test1.jpg",
        )
        cls.doc2_id = save_document(
            cls.test_db,
            document_type="Birth Certificate",
            extracted_fields={
                "Citizen Name": "Kavitha S",
                "Certificate Number": "BC/2026/999",
                "District": "Chennai",
                "Date of Birth": "12-05-2005",
            },
            ocr_text="GREATER CHENNAI CORPORATION BIRTH CERTIFICATE Kavitha S",
            file_path="uploads/test2.jpg",
        )
        cls.doc3_id = save_document(
            cls.test_db,
            document_type="Aadhaar Card",
            extracted_fields={
                "Citizen Name": "Priya Mohan",
                "Aadhaar Number": "1234 5678 9012",
                "District": "Coimbatore",
            },
            ocr_text="GOVERNMENT OF INDIA UNIQUE IDENTIFICATION AUTHORITY OF INDIA Priya Mohan",
            file_path="uploads/test3.jpg",
        )

        # Seed duplicate attempt
        log_duplicate_attempt(
            cls.test_db,
            filename="duplicate_cert.jpg",
            reason="A record with the same certificate number already exists.",
        )

        # Configure test Flask client
        cls.app = create_app()
        cls.app.config.update(
            TESTING=True,
            DATABASE_PATH=cls.test_db,
        )
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.test_db.exists():
                cls.test_db.unlink()
        except Exception:
            pass

    def test_dashboard_stats(self):
        """Verify dashboard statistics computation."""
        stats = get_dashboard_stats(self.test_db)
        self.assertEqual(stats["total_documents"], 3)
        self.assertEqual(stats["duplicates_blocked"], 1)
        self.assertEqual(stats["districts_count"], 3)
        self.assertEqual(stats["type_breakdown"]["Income Certificate"], 1)
        self.assertEqual(stats["type_breakdown"]["Birth Certificate"], 1)
        self.assertEqual(stats["type_breakdown"]["Aadhaar Card"], 1)
        self.assertEqual(len(stats["recent_documents"]), 3)
        self.assertEqual(len(stats["recent_duplicates"]), 1)

    def test_get_all_documents_filtering(self):
        """Verify search and filter capabilities."""
        # 1. No filter
        docs, count = get_all_documents(self.test_db)
        self.assertEqual(count, 3)
        self.assertEqual(len(docs), 3)

        # 2. Search query: Ramesh
        docs, count = get_all_documents(self.test_db, search_query="Ramesh")
        self.assertEqual(count, 1)
        self.assertEqual(docs[0]["citizen_name"], "Ramesh Kumar")

        # 3. Filter by type: Birth Certificate
        docs, count = get_all_documents(self.test_db, document_type="Birth Certificate")
        self.assertEqual(count, 1)
        self.assertEqual(docs[0]["citizen_name"], "Kavitha S")

        # 4. Filter by district: Salem
        docs, count = get_all_documents(self.test_db, district="Salem")
        self.assertEqual(count, 1)
        self.assertEqual(docs[0]["district"], "Salem")

    def test_get_document_by_id(self):
        """Verify single document retrieval and extra_fields parsing."""
        doc = get_document_by_id(self.test_db, self.doc1_id)
        self.assertIsNotNone(doc)
        self.assertEqual(doc["citizen_name"], "Ramesh Kumar")
        self.assertEqual(doc["extra_fields_parsed"].get("Annual Income"), "120000")

    def test_distinct_lists(self):
        """Verify distinct districts and document types."""
        districts = get_distinct_districts(self.test_db)
        self.assertIn("Chennai", districts)
        self.assertIn("Salem", districts)
        self.assertIn("Coimbatore", districts)

        dtypes = get_distinct_document_types(self.test_db)
        self.assertIn("Income Certificate", dtypes)
        self.assertIn("Birth Certificate", dtypes)

    def test_flask_routes(self):
        """Verify HTTP endpoints for Module 8."""
        # 1. Home page
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)

        # 2. Dashboard page
        res = self.client.get("/dashboard")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Document Intelligence Dashboard", res.data)
        self.assertIn(b"Ramesh Kumar", res.data)

        # 3. API stats
        res = self.client.get("/api/dashboard-stats")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["total_documents"], 3)

        # 4. API document detail
        res = self.client.get(f"/api/document/{self.doc1_id}")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["citizen_name"], "Ramesh Kumar")


if __name__ == "__main__":
    unittest.main()
