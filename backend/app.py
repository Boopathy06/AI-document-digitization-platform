"""Flask application for Smart Government Document Digitization Platform."""

import json
from datetime import datetime, timezone
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

from dataclasses import asdict

from enhancement_service import ImageEnhancementError, enhance_image
from ocr_service import OCRProcessingError, extract_text, extract_text_and_confidence
from pdf_service import PDFProcessingError, is_pdf, render_pdf_to_images
from quality_service import QualityAssessmentError, assess_image
from services.ai_assistant_service import process_assistant_query
from services.classifier import classify_document
from services.consistency_service import verify_document_consistency
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
    check_advanced_duplicates,
    check_file_duplicate,
    check_identifier_duplicate,
)
from services.extraction_dispatcher import extract_document_fields
from services.quality_score_service import calculate_document_quality_score
from services.verification_service import (
    analyze_document_fields,
    apply_field_corrections,
    ensure_verification_schema,
    get_document_verification_details,
)




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
    ensure_verification_schema(app.config["DATABASE_PATH"])

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
        selected_status = request.args.get("status", "All").strip()

        stats = get_dashboard_stats(app.config["DATABASE_PATH"])
        documents, total_count = get_all_documents(
            app.config["DATABASE_PATH"],
            search_query=search_query,
            document_type=selected_type,
            district=selected_district,
            verification_status=selected_status if selected_status != "All" else None,
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
            selected_status=selected_status,
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

    @app.route("/api/document/<int:doc_id>/verification")
    def api_document_verification(doc_id: int):
        """Return explainable verification analysis and field flags for Module 11."""
        report = get_document_verification_details(app.config["DATABASE_PATH"], doc_id)
        if not report:
            return jsonify({"error": "Document not found"}), 404
        return jsonify(asdict(report))

    @app.route("/api/document/<int:doc_id>/verify", methods=["POST"])
    def api_document_verify(doc_id: int):
        """Save human-in-the-loop field corrections and update verification status."""
        data = request.get_json(silent=True) or {}
        corrections = data.get("corrections", {})
        reviewer_name = data.get("reviewer_name", "Authorized Reviewer")
        notes = data.get("notes")
        try:
            report = apply_field_corrections(
                app.config["DATABASE_PATH"],
                doc_id,
                corrections,
                reviewer_name=reviewer_name,
                notes=notes,
            )
            return jsonify({
                "success": True,
                "overall_status": report.overall_status,
                "report": asdict(report),
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    @app.route("/api/document/<int:doc_id>/consistency")
    def api_document_consistency(doc_id: int):
        """Return field completeness, formatting, and date relationship validation for Module 13."""
        doc = get_document_by_id(app.config["DATABASE_PATH"], doc_id)
        if not doc:
            return jsonify({"error": "Document not found"}), 404
        report = verify_document_consistency(
            doc_id,
            doc["document_type"],
            doc.get("extra_fields_parsed") or {},
            ocr_text=doc.get("ocr_text") or "",
            database_path=app.config["DATABASE_PATH"],
        )
        return jsonify(asdict(report))

    @app.route("/api/document/<int:doc_id>/duplicates")
    def api_document_duplicates(doc_id: int):
        """Return potential duplicate documents found in the database for Module 12."""
        doc = get_document_by_id(app.config["DATABASE_PATH"], doc_id)
        if not doc:
            return jsonify({"error": "Document not found"}), 404
        report = check_advanced_duplicates(
            doc.get("extra_fields_parsed") or {},
            app.config["DATABASE_PATH"],
            exclude_doc_id=doc_id,
        )
        return jsonify(asdict(report))

    @app.route("/api/document/<int:doc_id>/quality-score")
    def api_document_quality_score(doc_id: int):
        """Return technical image quality, OCR confidence, and completeness score for Module 14."""
        doc = get_document_by_id(app.config["DATABASE_PATH"], doc_id)
        if not doc:
            return jsonify({"error": "Document not found"}), 404
        parsed_report = doc.get("quality_report_parsed") or {}
        if parsed_report and "overall_score" in parsed_report:
            return jsonify(parsed_report)
        report = calculate_document_quality_score(
            doc["document_type"],
            doc.get("extra_fields_parsed") or {},
        )
        return jsonify(asdict(report))

    @app.route("/api/document/<int:doc_id>/revalidate", methods=["POST"])
    def api_document_revalidate(doc_id: int):
        """Revalidate consistency, verification, and quality rules after user edits."""
        doc = get_document_by_id(app.config["DATABASE_PATH"], doc_id)
        if not doc:
            return jsonify({"error": "Document not found"}), 404
        c_report = verify_document_consistency(
            doc_id,
            doc["document_type"],
            doc.get("extra_fields_parsed") or {},
            ocr_text=doc.get("ocr_text") or "",
            database_path=app.config["DATABASE_PATH"],
        )
        v_report = get_document_verification_details(app.config["DATABASE_PATH"], doc_id)
        q_report = calculate_document_quality_score(
            doc["document_type"],
            doc.get("extra_fields_parsed") or {},
        )
        return jsonify({
            "success": True,
            "consistency": asdict(c_report),
            "verification": asdict(v_report) if v_report else {},
            "quality": asdict(q_report),
        })

    @app.route("/api/document/<int:doc_id>/mark-reviewed", methods=["POST"])
    def api_document_mark_reviewed(doc_id: int):
        """Mark document as reviewed after human inspection."""
        data = request.get_json(silent=True) or {}
        reviewer_name = data.get("reviewer_name", "Authorized Officer")
        notes = data.get("notes", "Human review completed.")
        from services.database_service import get_connection
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with get_connection(app.config["DATABASE_PATH"]) as conn:
            conn.execute(
                """
                UPDATE government_documents
                SET verification_status = 'reviewed',
                    verified_by = ?,
                    verified_at = ?
                WHERE id = ?
                """,
                (reviewer_name, now_iso, doc_id),
            )
        return jsonify({
            "success": True,
            "overall_status": "reviewed",
            "verified_by": reviewer_name,
            "verified_at": now_iso,
        })

    @app.route("/api/duplicates/check", methods=["POST"])
    def api_duplicates_check():
        """Ad-hoc duplicate detection check against database records."""
        data = request.get_json(silent=True) or {}
        fields = data.get("fields", {})
        doc_id = data.get("exclude_doc_id")
        report = check_advanced_duplicates(
            fields,
            app.config["DATABASE_PATH"],
            exclude_doc_id=doc_id,
        )
        return jsonify(asdict(report))

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
        ocr_confidence = None
        try:
            if pdf_result and pdf_result.pages:
                page_texts = []
                page_confs = []
                CERT_KEYWORDS = (
                    "certificate", "certify", "income", "community", "birth", "death",
                    "aadhaar", "unique identification", "pan card", "driving licence", "license",
                    "son of", "daughter of", "wife of", "residing", "resident", "tahsildar",
                    "government", "revenue", "department"
                )
                for idx, page in enumerate(pdf_result.pages):
                    raw_emb = (page.embedded_text or "").strip()
                    has_substantive = (
                        len(raw_emb) >= 150
                        and sum(1 for kw in CERT_KEYWORDS if kw in raw_emb.lower()) >= 2
                    )
                    if has_substantive:
                        pt = raw_emb
                        pconf = 0.95
                    else:
                        img_to_ocr = enhancement.output_path if (idx == 0 and enhancement) else page.image_path
                        pt, pconf = extract_text_and_confidence(img_to_ocr)
                        if raw_emb and pt and raw_emb not in pt:
                            pt = pt + "\n" + raw_emb
                        elif not pt and raw_emb:
                            pt = raw_emb

                    if pt:
                        page_texts.append(pt)
                    if pconf is not None:
                        page_confs.append(pconf)

                if not page_texts and pdf_result.combined_embedded_text:
                    ocr_text = pdf_result.combined_embedded_text
                else:
                    ocr_text = "\n\n".join(page_texts)
                ocr_confidence = (sum(page_confs) / len(page_confs)) if page_confs else 0.90
            else:
                img_path = enhancement.output_path if enhancement else saved_file_path
                ocr_text, ocr_confidence = extract_text_and_confidence(img_path)
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

        # Module 13: Consistency Verification
        consistency_report = verify_document_consistency(
            0,
            classification.document_type,
            extraction.fields,
            ocr_text or "",
            app.config["DATABASE_PATH"],
        )

        # Module 12: Advanced Duplicate Detection
        advanced_duplicate_report = check_advanced_duplicates(
            extraction.fields,
            app.config["DATABASE_PATH"],
        )

        # Module 14: Quality & Completeness Score
        quality_score_report = calculate_document_quality_score(
            classification.document_type,
            extraction.fields,
            quality_assessment=quality_report,
            ocr_confidence=ocr_confidence,
        )

        # Module 11: Explainable Field Validation
        verification_report = analyze_document_fields(
            0,
            classification.document_type,
            extraction.fields,
            ocr_text or "",
        )

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
            init_status = "auto_verified"
            if consistency_report.overall_status == "Failed" or verification_report.flagged_fields_count > 0:
                init_status = "needs_review"

            saved_document_id = save_document(
                app.config["DATABASE_PATH"],
                classification.document_type,
                extraction.fields,
                ocr_text or "",
                str(saved_file_path.relative_to(BASE_DIR)),
                verification_status=init_status,
                quality_score=quality_score_report.overall_score,
                quality_report=json.dumps(asdict(quality_score_report), ensure_ascii=False),
            )

            # Persist consistency results in database
            try:
                from services.database_service import get_connection
                with get_connection(app.config["DATABASE_PATH"]) as conn:
                    conn.execute(
                        "UPDATE government_documents SET consistency_results = ? WHERE id = ?",
                        (json.dumps(asdict(consistency_report), ensure_ascii=False), saved_document_id),
                    )
            except Exception:
                pass
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
            consistency_report=consistency_report,
            advanced_duplicate_report=advanced_duplicate_report,
            quality_score_report=quality_score_report,
            verification_report=verification_report,
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
