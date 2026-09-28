"""Unit tests for Module 9: AI Government Record Assistant & Natural Language Search."""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app
from services.ai_assistant_service import (
    SQLSafetyError,
    build_sql_from_query,
    extract_entities,
    generate_natural_answer,
    process_assistant_query,
    validate_safe_sql,
)


class TestModule9AIAssistant(unittest.TestCase):
    """Test suite for AI natural language query translation and conversational assistant."""

    def setUp(self):
        """Set up an isolated temporary database for testing."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_documents.db"

        # Initialize schema
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE government_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_type TEXT NOT NULL,
                citizen_name TEXT,
                certificate_number TEXT,
                aadhaar_number TEXT,
                dob TEXT,
                district TEXT,
                issue_date TEXT,
                upload_date TEXT NOT NULL,
                ocr_text TEXT,
                file_path TEXT NOT NULL,
                extra_fields TEXT NOT NULL DEFAULT '{}'
            )
        """)
        cur.execute("""
            CREATE TABLE duplicate_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                reason TEXT NOT NULL,
                detected_at TEXT NOT NULL
            )
        """)

        # Insert sample test documents
        cur.execute("""
            INSERT INTO government_documents 
            (document_type, citizen_name, certificate_number, aadhaar_number, dob, district, issue_date, upload_date, ocr_text, file_path, extra_fields)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "Income Certificate", "Gopal N", "TN-4202807036380", None, None, "Tiruppur", "11-07-2023",
            "2026-09-24 10:00:00", "Income Certificate Gopal N Tiruppur 78000", "uploads/test1.png",
            json.dumps({"Annual Income": "Rs. 78,000", "District": "Tiruppur"})
        ))

        cur.execute("""
            INSERT INTO government_documents 
            (document_type, citizen_name, certificate_number, aadhaar_number, dob, district, issue_date, upload_date, ocr_text, file_path, extra_fields)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "Student Permission Form", "BOOPATHY.G", "24CSRO44", None, None, "Erode", "16-11-2024",
            "2026-09-24 11:00:00", "KONGU ENGINEERING COLLEGE BOOPATHY 24CSRO44", "uploads/test2.jpg",
            json.dumps({"Roll Number": "24CSRO44", "Department": "Computer Science"})
        ))

        cur.execute("""
            INSERT INTO government_documents 
            (document_type, citizen_name, certificate_number, aadhaar_number, dob, district, issue_date, upload_date, ocr_text, file_path, extra_fields)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "Birth Certificate", "Ananya R", "TN-GCC-BC-2026-3391", None, "14-05-2026", "Chennai", "15-05-2026",
            "2026-09-24 12:00:00", "Birth Certificate Ananya Chennai", "uploads/test3.jpg",
            json.dumps({"Gender": "Female"})
        ))

        # Insert sample duplicate log
        cur.execute("""
            INSERT INTO duplicate_logs (filename, reason, detected_at)
            VALUES ('duplicate.png', 'File SHA-256 Hash duplicate', '2026-09-24 13:00:00')
        """)

        con.commit()
        con.close()

        # Set up Flask test client
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            DATABASE_PATH=self.db_path,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        """Clean up the temporary directory."""
        self.temp_dir.cleanup()

    def test_entity_extraction_types_and_districts(self):
        """Test extraction of document type and Tamil Nadu district."""
        entities = extract_entities("Show me income certificates from Tiruppur")
        self.assertEqual(entities.get("document_type"), "Income Certificate")
        self.assertEqual(entities.get("district"), "Tiruppur")

    def test_entity_extraction_identifiers(self):
        """Test extraction of certificate numbers and student roll numbers."""
        entities = extract_entities("Find certificate TN-4202807036380")
        self.assertEqual(entities.get("certificate_number"), "TN-4202807036380")

        entities2 = extract_entities("Search roll number 24CSRO44")
        self.assertEqual(entities2.get("roll_number"), "24CSRO44")

    def test_sql_safety_validator_blocks_unsafe_statements(self):
        """Test that destructive SQL commands are strictly forbidden."""
        with self.assertRaises(SQLSafetyError):
            validate_safe_sql("DROP TABLE government_documents")

        with self.assertRaises(SQLSafetyError):
            validate_safe_sql("DELETE FROM duplicate_logs WHERE id = 1")

        with self.assertRaises(SQLSafetyError):
            validate_safe_sql("SELECT * FROM government_documents; DROP TABLE users;")

    def test_query_count_intent(self):
        """Test general and specific count queries."""
        resp = process_assistant_query(self.db_path, "How many documents are there?")
        self.assertEqual(resp.intent, "count_records")
        self.assertTrue(resp.is_count_query)
        self.assertEqual(resp.count, 3)
        self.assertIn("3", resp.answer)

    def test_query_duplicate_audit(self):
        """Test queries regarding duplicate attempts."""
        resp = process_assistant_query(self.db_path, "How many duplicates were blocked?")
        self.assertEqual(resp.intent, "count_duplicates")
        self.assertEqual(resp.count, 1)
        self.assertIn("1", resp.answer)

    def test_query_filter_by_district_and_type(self):
        """Test combined filter query for type and district."""
        resp = process_assistant_query(self.db_path, "Show income certificates in Tiruppur")
        self.assertEqual(resp.intent, "search_records")
        self.assertEqual(resp.count, 1)
        self.assertEqual(resp.records[0]["citizen_name"], "Gopal N")
        self.assertEqual(resp.records[0]["certificate_number"], "TN-4202807036380")

    def test_query_filter_by_student_roll_number(self):
        """Test searching for student permission form by roll number."""
        resp = process_assistant_query(self.db_path, "Find record with roll number 24CSRO44")
        self.assertEqual(resp.count, 1)
        self.assertEqual(resp.records[0]["citizen_name"], "BOOPATHY.G")
        self.assertEqual(resp.records[0]["document_type"], "Student Permission Form")

    def test_query_not_found_graceful_answer(self):
        """Test answer formatting when no matching records exist."""
        resp = process_assistant_query(self.db_path, "Find records in Madurai")
        self.assertEqual(resp.count, 0)
        self.assertIn("No digitized records found", resp.answer)

    def test_api_assistant_chat_endpoint(self):
        """Test POST /api/assistant/chat HTTP endpoint."""
        response = self.client.post(
            "/api/assistant/chat",
            data=json.dumps({"query": "Show records for Gopal"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 1)
        self.assertIn("Gopal N", data["answer"])
        self.assertTrue(len(data["records"]) == 1)

    def test_assistant_html_view(self):
        """Test GET /assistant renders the conversational UI page."""
        response = self.client.get("/assistant")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("AI Government Record Assistant", html)
        self.assertIn("GovDoc AI Copilot", html)
        self.assertIn("chatMessages", html)


if __name__ == "__main__":
    unittest.main()
