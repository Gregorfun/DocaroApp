"""
Review Routes: Human-in-the-Loop Review Queue UI und API.
"""

import json
import logging
import sys
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, session

# Fix import path
APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import Config
from core.review_service import (
    DocumentStatus,
    ReviewSettings,
    decide_review_status,
    finalize_document,
    load_review_settings,
    save_correction,
    save_ground_truth_sample,
    save_review_settings
)

config = Config()
_LOGGER = logging.getLogger(__name__)

review_bp = Blueprint("review", __name__, url_prefix="/review")


def _results_path_for_user() -> Path:
    user_id = session.get("user_id")
    user_email = (session.get("user_email") or "").strip().lower()
    if user_id is not None and str(user_id).strip():
        scope = f"user_{user_id}"
    elif user_email:
        scope = f"user_{user_email}"
    else:
        scope = "system"
    safe_scope = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in scope).strip("_") or "system"
    user_tmp = config.DATA_DIR / "users" / safe_scope / "tmp"
    user_tmp.mkdir(parents=True, exist_ok=True)
    return user_tmp / "last_results.json"


def _load_session_files() -> dict:
    """Lädt user-spezifische Verarbeitungsergebnisse."""
    results_path = _results_path_for_user()
    if not results_path.exists():
        return {"results": []}
    try:
        data = json.loads(results_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return {"results": []}
        return {"results": data}
    except Exception:
        return {"results": []}


def _save_session_files(data: dict) -> None:
    """Speichert user-spezifische Verarbeitungsergebnisse."""
    results = data.get("results", []) if isinstance(data, dict) else []
    if not isinstance(results, list):
        results = []
    results_path = _results_path_for_user()
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def _get_document_by_id(doc_id: str) -> dict:
    """Holt Dokument aus session_files."""
    session_files = _load_session_files()
    for doc in session_files.get("results", []):
        if doc.get("file_id") == doc_id:
            return doc
    return None


def _update_document(doc_id: str, updates: dict) -> None:
    """Aktualisiert Dokument in session_files."""
    session_files = _load_session_files()
    for doc in session_files.get("results", []):
        if doc.get("file_id") == doc_id:
            doc.update(updates)
            break
    _save_session_files(session_files)


@review_bp.route("/")
def review_queue_page():
    """Review Queue UI - Liste aller NEEDS_REVIEW und READY Dokumente."""
    session_files = _load_session_files()
    results = session_files.get("results", [])
    
    # Filter: nur NEEDS_REVIEW oder READY
    review_docs = [
        doc for doc in results
        if doc.get("review_status") in [DocumentStatus.NEEDS_REVIEW, DocumentStatus.READY]
    ]
    
    # Load settings für Ampel-Farben
    settings = load_review_settings(config.DATA_DIR / "settings.json")
    
    return render_template(
        "review_queue.html",
        documents=review_docs,
        settings=settings
    )


@review_bp.route("/<file_id>")
def review_detail_page(file_id: str):
    """Review Detail UI - Einzeldokument mit Korrekturformular."""
    doc = _get_document_by_id(file_id)
    if not doc:
        return "Document not found", 404
    
    # Load settings
    settings = load_review_settings(config.DATA_DIR / "settings.json")
    
    # Get canonical suppliers for dropdown
    try:
        from core.supplier_canonicalizer import get_supplier_canonicalizer
        canonicalizer = get_supplier_canonicalizer()
        canonical_suppliers = canonicalizer.list_all_canonical_names()
    except Exception:
        canonical_suppliers = []
    
    return render_template(
        "review_detail.html",
        doc=doc,
        settings=settings,
        canonical_suppliers=canonical_suppliers
    )


@review_bp.route("/api/queue", methods=["GET"])
def api_review_queue():
    """API: Review Queue - Liste aller NEEDS_REVIEW oder READY Dokumente."""
    status_filter = request.args.get("status", "")
    
    session_files = _load_session_files()
    results = session_files.get("results", [])
    
    # Filter
    if status_filter:
        review_docs = [doc for doc in results if doc.get("review_status") == status_filter]
    else:
        review_docs = [
            doc for doc in results
            if doc.get("review_status") in [DocumentStatus.NEEDS_REVIEW, DocumentStatus.READY]
        ]
    
    return jsonify({
        "ok": True,
        "count": len(review_docs),
        "documents": review_docs
    })


@review_bp.route("/api/<file_id>", methods=["GET"])
def api_review_detail(file_id: str):
    """API: Einzeldokument Details."""
    doc = _get_document_by_id(file_id)
    if not doc:
        return jsonify({"ok": False, "error": "not_found"}), 404
    
    return jsonify({"ok": True, "document": doc})


@review_bp.route("/api/<file_id>/correct", methods=["POST"])
def api_correct_document(file_id: str):
    """
    API: Dokument korrigieren und optional finalisieren.
    
    Body:
        supplier_canonical: str
        doc_type: str
        doc_date_iso: str (YYYY-MM-DD)
        doc_number: str
        finalize: bool (default false)
    """
    doc = _get_document_by_id(file_id)
    if not doc:
        return jsonify({"ok": False, "error": "not_found"}), 404
    
    # Parse request
    data = request.get_json() or {}
    corrected = {
        "supplier_canonical": data.get("supplier_canonical", "").strip(),
        "doc_type": data.get("doc_type", "").strip(),
        "date": data.get("doc_date_iso", "").strip(),
        "doc_number": data.get("doc_number", "").strip()
    }
    should_finalize = data.get("finalize", False)
    
    # Save correction (Audit + ML)
    user_email = session.get("user_email", "unknown")
    original = {
        "supplier_canonical": doc.get("supplier_canonical"),
        "doc_type": doc.get("doc_type"),
        "date": doc.get("date"),
        "doc_number": doc.get("doc_number")
    }
    
    try:
        corrections_path = config.DATA_DIR / "corrections.json"
        save_correction(corrections_path, file_id, user_email, original, corrected)
    except Exception as exc:
        _LOGGER.warning(f"Failed to save correction: {exc}")
    
    # Save ground truth (ML training sample)
    try:
        ground_truth_path = config.DATA_DIR / "ml" / "ground_truth.jsonl"
        # Get OCR text from doc (if available)
        ocr_text = doc.get("ocr_text", doc.get("textlayer_text", ""))
        save_ground_truth_sample(ground_truth_path, file_id, ocr_text, corrected)
    except Exception as exc:
        _LOGGER.warning(f"Failed to save ground truth: {exc}")
    
    # Update document with corrected values
    doc.update({
        "supplier_canonical": corrected["supplier_canonical"],
        "doc_type": corrected["doc_type"],
        "date": corrected["date"],
        "doc_number": corrected["doc_number"],
        "review_status": DocumentStatus.READY,  # Nach Korrektur -> READY
        "review_reasons": []
    })
    _update_document(file_id, doc)
    
    # Finalize if requested
    finalize_result = None
    if should_finalize:
        try:
            source_path = Path(doc.get("path", ""))
            if not source_path.exists():
                source_path = Path(doc.get("original_path", ""))
            
            settings = load_review_settings(config.DATA_DIR / "settings.json")
            finalize_result = finalize_document(
                doc_id=file_id,
                source_path=source_path,
                extraction_result=doc,
                settings=settings,
                mode="move"
            )
            
            if finalize_result.success:
                # Update document status
                doc.update({
                    "review_status": DocumentStatus.FINALIZED,
                    "finalized_path": str(finalize_result.finalized_path),
                    "path": str(finalize_result.finalized_path)
                })
                _update_document(file_id, doc)
        except Exception as exc:
            _LOGGER.error(f"Finalize failed: {exc}")
            finalize_result = None
    
    return jsonify({
        "ok": True,
        "document": doc,
        "finalized": finalize_result.success if finalize_result else False,
        "finalized_path": str(finalize_result.finalized_path) if finalize_result and finalize_result.success else None
    })


@review_bp.route("/api/<file_id>/finalize", methods=["POST"])
def api_finalize_document(file_id: str):
    """API: Dokument finalisieren (Rename + AutoSort)."""
    doc = _get_document_by_id(file_id)
    if not doc:
        return jsonify({"ok": False, "error": "not_found"}), 404
    
    # Check if READY
    if doc.get("review_status") != DocumentStatus.READY:
        return jsonify({
            "ok": False,
            "error": "not_ready",
            "message": "Document must be READY status to finalize"
        }), 400
    
    # Finalize
    try:
        source_path = Path(doc.get("path", ""))
        if not source_path.exists():
            source_path = Path(doc.get("original_path", ""))
        
        settings = load_review_settings(config.DATA_DIR / "settings.json")
        finalize_result = finalize_document(
            doc_id=file_id,
            source_path=source_path,
            extraction_result=doc,
            settings=settings,
            mode="move"
        )
        
        if finalize_result.success:
            # Update document
            doc.update({
                "review_status": DocumentStatus.FINALIZED,
                "finalized_path": str(finalize_result.finalized_path),
                "path": str(finalize_result.finalized_path)
            })
            _update_document(file_id, doc)
            
            return jsonify({
                "ok": True,
                "finalized_path": str(finalize_result.finalized_path),
                "final_filename": finalize_result.final_filename,
                "autosort_reason": finalize_result.autosort_reason
            })
        else:
            return jsonify({
                "ok": False,
                "error": "finalize_failed",
                "message": finalize_result.error
            }), 500
    except Exception as exc:
        _LOGGER.error(f"Finalize failed: {exc}")
        return jsonify({
            "ok": False,
            "error": "finalize_exception",
            "message": str(exc)
        }), 500


@review_bp.route("/api/settings", methods=["GET"])
def api_get_settings():
    """API: Review Settings abrufen."""
    settings = load_review_settings(config.DATA_DIR / "settings.json")
    return jsonify({
        "ok": True,
        "settings": {
            "gate_supplier_min": settings.gate_supplier_min,
            "gate_date_min": settings.gate_date_min,
            "gate_doc_type_min": settings.gate_doc_type_min,
            "gate_doc_number_min": settings.gate_doc_number_min,
            "auto_finalize_enabled": settings.auto_finalize_enabled,
            "autosort_enabled": settings.autosort_enabled,
            "autosort_base_dir": str(settings.autosort_base_dir)
        }
    })


@review_bp.route("/api/settings", methods=["POST"])
def api_update_settings():
    """API: Review Settings aktualisieren."""
    data = request.get_json() or {}
    
    settings = ReviewSettings(
        gate_supplier_min=float(data.get("gate_supplier_min", 0.80)),
        gate_date_min=float(data.get("gate_date_min", 0.80)),
        gate_doc_type_min=float(data.get("gate_doc_type_min", 0.70)),
        gate_doc_number_min=float(data.get("gate_doc_number_min", 0.80)),
        auto_finalize_enabled=bool(data.get("auto_finalize_enabled", False)),
        autosort_enabled=bool(data.get("autosort_enabled", False)),
        autosort_base_dir=Path(data.get("autosort_base_dir", "."))
    )
    
    save_review_settings(config.DATA_DIR / "settings.json", settings)
    
    return jsonify({"ok": True})
