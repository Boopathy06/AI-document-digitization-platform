"""Maintenance script to clear all uploaded documents and reset the database."""

import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "database" / "documents.db"
UPLOAD_DIR = BASE_DIR / "uploads"
ENHANCED_DIR = UPLOAD_DIR / "enhanced"


def reset_database():
    """Clear all records from all tables and reset autoincrement sequence."""
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return

    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"Tables found: {tables}")

    for table in tables:
        cursor.execute(f"DELETE FROM {table}")
        print(f"  - Cleared table: {table}")

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'")
    if cursor.fetchone():
        cursor.execute("DELETE FROM sqlite_sequence")
        print("  - Reset autoincrement sequence counters")

    connection.commit()
    connection.close()
    print("Database cleared successfully.")


def reset_uploads():
    """Delete all files in uploads and uploads/enhanced, keeping the folders."""
    if not UPLOAD_DIR.exists():
        print(f"Upload directory not found at {UPLOAD_DIR}")
        return

    deleted_count = 0
    for item in UPLOAD_DIR.rglob("*"):
        if item.is_file():
            try:
                item.unlink()
                deleted_count += 1
            except Exception as error:
                print(f"  - Could not delete {item}: {error}")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ENHANCED_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Deleted {deleted_count} files from {UPLOAD_DIR}.")


if __name__ == "__main__":
    print("Starting system reset...")
    reset_database()
    reset_uploads()
    print("Reset completed successfully.")
