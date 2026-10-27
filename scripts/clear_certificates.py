import sqlite3
import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
db_path = BASE_DIR / "database" / "documents.db"

print(f"Connecting to database: {db_path}")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

tables = ["government_documents", "documents", "duplicate_logs", "verification_audit_logs"]
for t in tables:
    try:
        cur.execute(f"DELETE FROM {t}")
        print(f"Cleared table: {t}")
    except Exception as e:
        print(f"Note on {t}: {e}")

try:
    cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('government_documents', 'documents', 'duplicate_logs', 'verification_audit_logs')")
    print("Reset sqlite_sequence autoincrement counters")
except Exception as e:
    print(f"Note on sqlite_sequence: {e}")

conn.commit()
conn.close()

# Verify row counts
conn = sqlite3.connect(db_path)
cur = conn.cursor()
for t in tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = cur.fetchone()[0]
        print(f"Verification: {t} now has {cnt} records.")
    except Exception as e:
        pass
conn.close()

# Clean uploads directory
uploads_dir = BASE_DIR / "uploads"
if uploads_dir.exists():
    for item in uploads_dir.iterdir():
        if item.is_file():
            item.unlink()
            print(f"Deleted upload file: {item.name}")
        elif item.is_dir() and item.name == "enhanced":
            for sub in item.iterdir():
                if sub.is_file():
                    sub.unlink()
            print("Cleaned uploads/enhanced directory.")
        elif item.is_dir() and item.name == "pdf_pages":
            for sub in item.iterdir():
                if sub.is_dir():
                    shutil.rmtree(sub)
                elif sub.is_file():
                    sub.unlink()
            print("Cleaned uploads/pdf_pages directory.")

# Ensure necessary subdirectories exist
(uploads_dir / "enhanced").mkdir(parents=True, exist_ok=True)
(uploads_dir / "pdf_pages").mkdir(parents=True, exist_ok=True)

print("All certificates in database and uploaded storage successfully cleared.")
