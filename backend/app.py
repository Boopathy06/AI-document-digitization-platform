"""Flask entry point for Module 1: document upload."""

from pathlib import Path
from uuid import uuid4

from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from enhancement_service import ImageEnhancementError, enhance_image
from ocr_service import OCRProcessingError, extract_text
from quality_service import QualityAssessmentError, assess_image
from services.classifier import classify_document
from services.database_service import fetch_duplicate_records, initialize_database, save_document
from services.duplicate_checker import DuplicateCheckResult, check_file_duplicate, check_identifier_duplicate
from services.extraction_dispatcher import extract_document_fields


BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
ENHANCED_FOLDER = UPLOAD_FOLDER / "enhanced"
DATABASE_PATH = BASE_DIR / "database" / "documents.db"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="change-this-secret-key-before-deployment",
        UPLOAD_FOLDER=UPLOAD_FOLDER,
        ENHANCED_FOLDER=ENHANCED_FOLDER,
        DATABASE_PATH=DATABASE_PATH,
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    )
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    initialize_database(app.config["DATABASE_PATH"])

    @app.route("/")
    def home():
        return render_template("index.html")

    @app.route("/enhanced/<path:filename>")
    def enhanced_document(filename: str):
        """Serve an enhanced image preview generated for this local application."""
        return send_from_directory(app.config["ENHANCED_FOLDER"], filename)

    @app.route("/upload", methods=["POST"])
    def upload_document():
        file = request.files.get("document")
        if file is None or not file.filename:
            flash("Please choose a document to upload.", "error")
            return redirect(url_for("home"))
        if not allowed_file(file.filename):
            flash("Only PNG, JPG, JPEG, and PDF files are allowed.", "error")
            return redirect(url_for("home"))

        original_name = secure_filename(file.filename)
        extension = original_name.rsplit(".", 1)[1].lower()
        saved_name = f"{uuid4().hex}.{extension}"
        file.save(app.config["UPLOAD_FOLDER"] / saved_name)

        document_path = app.config["UPLOAD_FOLDER"] / saved_name
        try:
            quality_report = assess_image(document_path)
        except QualityAssessmentError as error:
            flash(str(error), "error")
            quality_report = None

        try:
            enhancement = enhance_image(
                document_path,
                app.config["ENHANCED_FOLDER"],
                quality_report.skew_angle if quality_report else None,
            )
        except ImageEnhancementError as error:
            flash(str(error), "error")
            enhancement = None

        try:
            ocr_text = extract_text(enhancement.output_path if enhancement else document_path)
        except OCRProcessingError as error:
            flash(str(error), "error")
            ocr_text = None

        classification = classify_document(ocr_text or "")
        extraction = extract_document_fields(classification.document_type, ocr_text or "")
        file_duplicate_check = check_file_duplicate(document_path, app.config["UPLOAD_FOLDER"])
        identifier_duplicate_check = check_identifier_duplicate(
            extraction.fields,
            fetch_duplicate_records(app.config["DATABASE_PATH"]),
        )
        duplicate_check = next(
            (
                check
                for check in (file_duplicate_check, identifier_duplicate_check)
                if check.is_duplicate
            ),
            DuplicateCheckResult(False, "No duplicate file or stored identifier was found."),
        )

        saved_document_id = None
        if not duplicate_check.is_duplicate:
            saved_document_id = save_document(
                app.config["DATABASE_PATH"],
                classification.document_type,
                extraction.fields,
                ocr_text or "",
                str(document_path.relative_to(BASE_DIR)),
            )
        return render_template(
            "index.html",
            uploaded_filename=original_name,
            ocr_text=ocr_text,
            quality_report=quality_report,
            enhancement=enhancement,
            classification=classification,
            extraction=extraction,
            duplicate_check=duplicate_check,
            saved_document_id=saved_document_id,
        )

    @app.errorhandler(413)
    def file_too_large(_error):
        flash("The document is too large. Maximum upload size is 16 MB.", "error")
        return redirect(url_for("home"))

    return app


def allowed_file(filename: str) -> bool:
    """Return whether a filename has an accepted extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
