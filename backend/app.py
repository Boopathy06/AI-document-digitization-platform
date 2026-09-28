"""Flask application for Smart Government Document Digitization Platform."""

from pathlib import Path
from uuid import uuid4

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

from enhancement_service import ImageEnhancementError, enhance_image
from ocr_service import OCRProcessingError, extract_text
from pdf_service import PDFProcessingError, is_pdf, render_pdf_to_images
from quality_service import QualityAssessmentError, assess_image
from services.ai_assistant_service import process_assistant_query
from services.classifier import classify_document
from services.dashboard_service import (
    ensure_dashboard_tables,
    get_all_documents,
    get_dashboard_stats,
    get_distinct_districts,
    get_distinct_document_types,
    get_document_by_id,
    log_duplicate_attempt,
)
from services.database_service import (
    fetch_duplicate_records,
    initialize_database,
    save_document,
)
from services.duplicate_checker import (
    DuplicateCheckResult,
    check_file_duplicate,
    check_identifier_duplicate,
)
from services.extraction_dispatcher import extract_document_fields


BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
ENHANCED_FOLDER = UPLOAD_FOLDER / "enhanced"
PDF_PAGES_FOLDER = UPLOAD_FOLDER / "pdf_pages"
DATABASE_PATH = BASE_DIR / "database" / "documents.db"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="change-this-secret-key-before-deployment",
        UPLOAD_FOLDER=UPLOAD_FOLDER,
        ENHANCED_FOLDER=ENHANCED_FOLDER,
        PDF_PAGES_FOLDER=PDF_PAGES_FOLDER,
        DATABASE_PATH=DATABASE_PATH,
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    )
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    ENHANCED_FOLDER.mkdir(parents=True, exist_ok=True)
    PDF_PAGES_FOLDER.mkdir(parents=True, exist_ok=True)
    initialize_database(app.config["DATABASE_PATH"])
    ensure_dashboard_tables(app.config["DATABASE_PATH"])

    @app.route("/")
    def home():
        """Render the document upload and digitization intake page."""
        return render_template("index.html")

    @app.route("/dashboard")
    def dashboard_view():
        """Render the government document intelligence dashboard."""
        search_query = request.args.get("search", "").strip()
        selected_type = request.args.get("type", "All").strip()
        selected_district = request.args.get("district", "All").strip()

        stats = get_dashboard_stats(app.config["DATABASE_PATH"])
        documents, total_count = get_all_documents(
            app.config["DATABASE_PATH"],
            search_query=search_query,
            document_type=selected_type,
            district=selected_district,
            limit=50,
            offset=0,
        )
        all_districts = get_distinct_districts(app.config["DATABASE_PATH"])
        all_types = get_distinct_document_types(app.config["DATABASE_PATH"])

        return render_template(
            "dashboard.html",
            stats=stats,
            documents=documents,
            total_count=total_count,
            all_districts=all_districts,
            all_types=all_types,
            search_query=search_query,
            selected_type=selected_type,
            selected_district=selected_district,
        )

    @app.route("/assistant")
    def assistant_view():
        """Render the AI Government Record Assistant conversational interface."""
        initial_query = request.args.get("q", "").strip()
        return render_template("assistant.html", initial_query=initial_query)

    @app.route("/api/assistant/chat", methods=["POST"])
    def api_assistant_chat():
        """Process natural language queries into safe SQL and return conversational answers."""
        data = request.get_json(silent=True) or {}
        user_query = data.get("query", "").strip()
        response = process_assistant_query(app.config["DATABASE_PATH"], user_query)
        return jsonify({
            "success": True,
            "query": response.query,
            "intent": response.intent,
            "generated_sql": response.generated_sql,
            "answer": response.answer,
            "count": response.count,
            "records": response.records,
            "suggestions": response.suggestions,
            "is_count_query": response.is_count_query,
        })

    @app.route("/api/assistant/suggestions")
    def api_assistant_suggestions():
        """Return dynamic query suggestions for the user interface."""
        response = process_assistant_query(app.config["DATABASE_PATH"], "")
        return jsonify({"suggestions": response.suggestions})

    @app.route("/api/document/<int:doc_id>")
    def api_document_detail(doc_id: int):
        """Return detailed JSON representation of a document for modal inspection."""
        document = get_document_by_id(app.config["DATABASE_PATH"], doc_id)
        if not document:
            return jsonify({"error": "Document not found"}), 404
        return jsonify(document)

    @app.route("/api/dashboard-stats")
    def api_dashboard_stats():
        """Return JSON overview statistics for the dashboard."""
        stats = get_dashboard_stats(app.config["DATABASE_PATH"])
        return jsonify(stats)

    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename: str):
        """Serve uploaded original documents for inspection previews."""
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

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
        saved_file_path = app.config["UPLOAD_FOLDER"] / saved_name
        file.save(saved_file_path)

        pdf_result = None
        target_visual_path = saved_file_path

        # Module 10: Multi-Page PDF Document Handling
        if extension == "pdf":
            try:
                pdf_out_dir = app.config["PDF_PAGES_FOLDER"] / saved_file_path.stem
                pdf_result = render_pdf_to_images(saved_file_path, pdf_out_dir, dpi=300)
                if pdf_result.primary_image_path:
                    target_visual_path = pdf_result.primary_image_path
            except PDFProcessingError as error:
                flash(f"PDF Processing Warning: {error}", "error")
                pdf_result = None

        # 1. Quality Assessment (Run on primary visual image)
        try:
            quality_report = assess_image(target_visual_path)
        except QualityAssessmentError as error:
            flash(str(error), "error")
            quality_report = None

        # 2. Image Enhancement
        try:
            enhancement = enhance_image(
                target_visual_path,
                app.config["ENHANCED_FOLDER"],
                quality_report.skew_angle if quality_report else None,
            )
        except ImageEnhancementError as error:
            flash(str(error), "error")
            enhancement = None

        # 3. Text Extraction (PaddleOCR / EasyOCR with Multi-Page PDF Support)
        ocr_text = None
        try:
            if pdf_result and pdf_result.pages:
                page_texts = []
                for idx, page in enumerate(pdf_result.pages):
                    img_to_ocr = enhancement.output_path if (idx == 0 and enhancement) else page.image_path
                    pt = extract_text(img_to_ocr)
                    if not pt and page.embedded_text:
                        pt = page.embedded_text
                    if pt:
                        page_texts.append(pt)

                if not page_texts and pdf_result.combined_embedded_text:
                    ocr_text = pdf_result.combined_embedded_text
                else:
                    ocr_text = "\n\n".join(page_texts)
            else:
                ocr_text = extract_text(enhancement.output_path if enhancement else saved_file_path)
        except OCRProcessingError as error:
            flash(str(error), "error")
            ocr_text = None

        # 4. Classification & Structured Field Extraction
        classification = classify_document(ocr_text or "")
        extraction = extract_document_fields(classification.document_type, ocr_text or "")

        # Enrich extra_fields with PDF metadata if applicable
        if pdf_result:
            extraction.fields["Document Format"] = "PDF Document"
            extraction.fields["Page Count"] = str(pdf_result.total_pages)
            if pdf_result.relative_primary_image_path:
                extraction.fields["Preview Image"] = pdf_result.relative_primary_image_path
            if len(pdf_result.pages) > 1:
                extraction.fields["PDF Pages"] = [p.relative_image_path for p in pdf_result.pages]

        # 5. Duplicate Detection (File Hash & Identifier)
        file_duplicate_check = check_file_duplicate(saved_file_path, app.config["UPLOAD_FOLDER"])
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
        # 6. Database Persistence
        if not duplicate_check.is_duplicate:
            saved_document_id = save_document(
                app.config["DATABASE_PATH"],
                classification.document_type,
                extraction.fields,
                ocr_text or "",
                str(saved_file_path.relative_to(BASE_DIR)),
            )
        else:
            # Audit log the blocked duplicate attempt
            log_duplicate_attempt(
                app.config["DATABASE_PATH"],
                original_name,
                duplicate_check.reason,
            )

        return render_template(
            "index.html",
            uploaded_filename=original_name,
            saved_name=saved_name,
            ocr_text=ocr_text,
            quality_report=quality_report,
            enhancement=enhancement,
            classification=classification,
            extraction=extraction,
            duplicate_check=duplicate_check,
            saved_document_id=saved_document_id,
            pdf_result=pdf_result,
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
