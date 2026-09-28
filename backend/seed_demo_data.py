"""Utility script to seed demo government records into documents.db for testing the dashboard."""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from services.dashboard_service import ensure_dashboard_tables, log_duplicate_attempt
from services.database_service import initialize_database, save_document

DATABASE_PATH = BASE_DIR.parent / "database" / "documents.db"


def seed_demo_data():
    initialize_database(DATABASE_PATH)
    ensure_dashboard_tables(DATABASE_PATH)

    sample_docs = [
        {
            "type": "Income Certificate",
            "fields": {
                "Citizen Name": "Senthil Nathan",
                "Certificate Number": "TN-REV-INC-2026-0814",
                "District": "Salem",
                "Date of Birth": "14-07-1992",
                "Issue Date": "10-02-2026",
                "Annual Income": "₹ 1,40,000",
                "Father / Husband Name": "M. Ramasamy",
            },
            "ocr": "GOVERNMENT OF TAMIL NADU REVENUE DEPARTMENT\nINCOME CERTIFICATE\nCertificate No: TN-REV-INC-2026-0814\nThis is to certify that Thiru Senthil Nathan son of M. Ramasamy residing at Salem District has an annual income of Rs. 1,40,000/- only.\nIssued by Tahsildar Salem.",
            "path": "uploads/income_cert_sample.jpg",
        },
        {
            "type": "Birth Certificate",
            "fields": {
                "Citizen Name": "Ananya R",
                "Certificate Number": "TN-GCC-BC-2026-3391",
                "District": "Chennai",
                "Date of Birth": "04-03-2024",
                "Issue Date": "15-03-2024",
                "Father's Name": "Rajesh Kumar",
                "Mother's Name": "Deepa Rajesh",
            },
            "ocr": "GREATER CHENNAI CORPORATION\nPUBLIC HEALTH DEPARTMENT\nCERTIFICATE OF BIRTH\nCertificate Number: TN-GCC-BC-2026-3391\nChild Name: Ananya R\nDate of Birth: 04-03-2024\nFather: Rajesh Kumar, Mother: Deepa Rajesh\nPlace of Birth: Government Hospital Chennai",
            "path": "uploads/birth_cert_sample.jpg",
        },
        {
            "type": "Community Certificate",
            "fields": {
                "Citizen Name": "Vigneshwaran K",
                "Certificate Number": "TN-REV-COMM-2025-5021",
                "District": "Madurai",
                "Date of Birth": "22-11-1998",
                "Issue Date": "05-08-2025",
                "Community": "BC - Backward Class",
            },
            "ocr": "GOVERNMENT OF TAMIL NADU\nREVENUE ADMINISTRATION\nCOMMUNITY CERTIFICATE\nCertificate No: TN-REV-COMM-2025-5021\nThis is to certify that Thiru Vigneshwaran K belongs to Backward Class.\nDistrict: Madurai. Issued under e-Sevai portal.",
            "path": "uploads/community_cert_sample.jpg",
        },
        {
            "type": "Aadhaar Card",
            "fields": {
                "Citizen Name": "Meenakshi Sundaram",
                "Aadhaar Number": "5489 1029 3847",
                "District": "Coimbatore",
                "Date of Birth": "19-09-1988",
                "Gender": "Male",
            },
            "ocr": "GOVERNMENT OF INDIA\nUNIQUE IDENTIFICATION AUTHORITY OF INDIA\nMeenakshi Sundaram\nDOB: 19/09/1988\nGender: Male\n5489 1029 3847\nMera Aadhaar, Meri Pehchan",
            "path": "uploads/aadhaar_sample.jpg",
        },
    ]

    for doc in sample_docs:
        doc_id = save_document(
            DATABASE_PATH,
            document_type=doc["type"],
            extracted_fields=doc["fields"],
            ocr_text=doc["ocr"],
            file_path=doc["path"],
        )
        print(f"Seeded document #{doc_id}: {doc['type']} for {doc['fields']['Citizen Name']}")

    # Seed sample duplicate interceptions
    sample_dups = [
        ("scan_income_copy.jpg", "A record with the same certificate number already exists."),
        ("aadhaar_reupload.png", "A record with the same Aadhaar number already exists."),
    ]
    for fname, reason in sample_dups:
        log_duplicate_attempt(DATABASE_PATH, fname, reason)
        print(f"Logged duplicate interception: {fname} -> {reason}")

    print("Demo seeding complete!")


if __name__ == "__main__":
    seed_demo_data()
