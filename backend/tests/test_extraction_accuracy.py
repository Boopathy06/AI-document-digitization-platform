"""Verification tests for OCR extraction accuracy, document classification, and structured field extraction."""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from services.classifier import classify_document
from services.extractors.aadhaar import extract_fields as extract_aadhaar_fields
from services.extractors.income_certificate import extract_fields as extract_income_fields
from services.extractors.community_certificate import extract_fields as extract_community_fields
from services.extractors.birth_certificate import extract_fields as extract_birth_fields


class TestExtractionAccuracy(unittest.TestCase):
    """Test classification and field extraction on realistic, watermarked, and OCR-noised texts."""

    def test_income_certificate_extraction(self):
        """Test Tamil Nadu Income Certificate extraction with realistic OCR noise."""
        ocr_sample = """
        வருமானச் சான்றிதழ்
        Income Ccrtificatc
        'Certificate No: Tn-4202807036380 1 D 11-07-3027
        This I {0 ccruily that Thiru Gopal N :on 0 Thiru Nanjappagoundcr rcsiding j Door No.
        2/209. Thalakkaral or Thandukkarmpalayam Villagc 1 Toivn ot Avinashi Taluk 0f Ticuppur District
        0f thc Statc of Tamil Nadu: Hs /Hcr famlly annual Incomc bascd on dctalls turnishcd by his/hcr In
        the tablc bclow and veritication Is Rs. 78ooo/jnnum (Rupccs Scvcnty Elght Thousand Only)
        Signature Not Verifieg
        Dale: 11/07/2023 14:15:22 IST
        """
        # Classification
        classification = classify_document(ocr_sample)
        self.assertEqual(classification.document_type, "Income Certificate")

        # Field Extraction
        fields = extract_income_fields(ocr_sample)
        self.assertEqual(fields.get("Certificate Number"), "TN-4202807036380")
        self.assertEqual(fields.get("Citizen Name"), "Gopal N")
        self.assertEqual(fields.get("District"), "Tiruppur")
        self.assertIn("78,000", fields.get("Annual Income", ""))
        self.assertEqual(fields.get("Taluk"), "Avinashi")
        self.assertEqual(fields.get("Issue Date"), "11-07-2023")

    def test_aadhaar_card_extraction(self):
        """Test Aadhaar card extraction with UIDAI format."""
        ocr_sample = """
        GOVERNMENT OF INDIA
        Unique Identification Authority of India
        To
        Boopathy
        S/O: Gopal, 2/208, Thalakarai,
        Thandukarampalayam, Avinashi,
        District: Tiruppur, PIN Code: 641655
        Your Aadhaar No. :
        3364 2270 6124
        VID : 9139 2849 7347 5468
        DOB: 28/09/2006
        MALE
        """
        # Classification
        classification = classify_document(ocr_sample)
        self.assertEqual(classification.document_type, "Aadhaar Card")

        # Field Extraction
        fields = extract_aadhaar_fields(ocr_sample)
        self.assertEqual(fields.get("Aadhaar Number"), "3364 2270 6124")
        self.assertEqual(fields.get("Citizen Name"), "Boopathy")
        self.assertEqual(fields.get("Date of Birth"), "28-09-2006")
        self.assertEqual(fields.get("Gender"), "Male")
        self.assertEqual(fields.get("District"), "Tiruppur")
        self.assertEqual(fields.get("PIN Code"), "641655")

    def test_birth_certificate_extraction(self):
        """Test Birth Certificate extraction."""
        ocr_sample = """
        GREATER CHENNAI CORPORATION
        PUBLIC HEALTH DEPARTMENT
        CERTIFICATE OF BIRTH
        Certificate Number: TN-GCC-BC-2026-3391
        Child Name: Ananya R
        Date of Birth: 04-03-2024
        Father's Name: Rajesh Kumar
        Mother's Name: Deepa Rajesh
        District: Chennai
        """
        classification = classify_document(ocr_sample)
        self.assertEqual(classification.document_type, "Birth Certificate")

        fields = extract_birth_fields(ocr_sample)
        self.assertEqual(fields.get("Citizen Name"), "Ananya R")
        self.assertEqual(fields.get("Certificate Number"), "TN-GCC-BC-2026-3391")
        self.assertEqual(fields.get("District"), "Chennai")
    def test_community_certificate_extraction(self):
        """Test Tamil Nadu Community Certificate with Selvan [Applicant] son of Thiru [Father]."""
        ocr_sample = """
        COMMUNITY CERTIFICATE
        /Certificate No:TN-5201912057677 /Date:09-12-2019
        This is to certify that Selvan Boopathy son of Thiru Gopal residing at Door No.2/208
        Thalakarai, of Thandukkarampalayam Village / Town Avinashi Taluk Tiruppur District of the State of
        Tamil Nadu belongs to Kongu Vellalars Community, which is recognized as a Backward Class as per
        Government Order (Ms.) No.85,Backward Classes, Most Backward Classes and Minority Welfare
        Department (BCC).dated 29th July 2008 vide Serial No.56.
        District: Tiruppur
        """
        classification = classify_document(ocr_sample)
        self.assertEqual(classification.document_type, "Community Certificate")

        fields = extract_community_fields(ocr_sample)
        self.assertEqual(fields.get("Certificate Number"), "TN-5201912057677")
        self.assertEqual(fields.get("Citizen Name"), "Boopathy")
        self.assertEqual(fields.get("Father / Guardian"), "Gopal")
        self.assertEqual(fields.get("Community"), "Kongu Vellalars (Backward Class)")
        self.assertEqual(fields.get("District"), "Tiruppur")
        self.assertEqual(fields.get("Issue Date"), "09-12-2019")

    def test_community_certificate_general_class(self):
        """Test Community Certificate with general category format."""
        ocr_sample = """
        GOVERNMENT OF TAMIL NADU
        REVENUE ADMINISTRATION
        COMMUNITY CERTIFICATE
        Certificate No: TN-REV-COMM-2025-5021
        This is to certify that Thiru Vigneshwaran K belongs to Backward Class.
        District: Madurai.
        """
        classification = classify_document(ocr_sample)
        self.assertEqual(classification.document_type, "Community Certificate")

        fields = extract_community_fields(ocr_sample)
        self.assertEqual(fields.get("Certificate Number"), "TN-REV-COMM-2025-5021")
        self.assertEqual(fields.get("Citizen Name"), "Vigneshwaran K")
        self.assertEqual(fields.get("Community"), "Backward Class")
        self.assertEqual(fields.get("District"), "Madurai")


if __name__ == "__main__":
    unittest.main()
