import sqlite3
from datetime import datetime
DATABASE_NAME = "../database/documents.db"


def create_database():

    connection = sqlite3.connect(DATABASE_NAME)

    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            filename TEXT,

            ocr_text TEXT,

            upload_date TEXT

        )
    """)

    connection.commit()

    connection.close()

def save_document(filename, ocr_text):

    connection = sqlite3.connect(DATABASE_NAME)

    cursor = connection.cursor()

    upload_date = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

    cursor.execute("""

        INSERT INTO documents(

            filename,

            ocr_text,

            upload_date

        )

        VALUES(?,?,?)

    """,(filename,ocr_text,upload_date))

    connection.commit()

    connection.close()  