"""
Web-UI Review-Endpunkte für Quarantäne & Korrekturen.
"""

import json
import logging
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from pathlib import Path

from config import Config
from core.quarantine_manager import QuarantineManager
from core.audit_logger import AuditLogger

_LOGGER = logging.getLogger(__name__)

review_bp = Blueprint('review', __name__)

config = Config()


@review_bp.route('/review/quarantine')
def quarantine_list():
    """Liste aller Dokumente in Quarantäne."""
    qm = QuarantineManager(
        quarantine_dir=config.QUARANTINE_DIR,
        quarantine_log=config.DATA_DIR / "quarantine.jsonl"
    )
    
    entries = qm.list_quarantine(reviewed=False)
    
    return render_template('quarantine.html', entries=entries)


@review_bp.route('/review/document/<path:doc_path>')
def review_document(doc_path: str):
    """Detailansicht eines Quarantäne-Dokuments."""
    qm = QuarantineManager(
        quarantine_dir=config.QUARANTINE_DIR,
        quarantine_log=config.DATA_DIR / "quarantine.jsonl"
    )
    
    entries = qm.list_quarantine()
    entry = None
    
    for e in entries:
        if e.document_path == doc_path or e.original_name == doc_path:
            entry = e
            break
    
    if not entry:
        return jsonify({"error": "Dokument nicht gefunden"}), 404
    
    # Lade Audit-Details
    audit_logger = AuditLogger(config.DATA_DIR / "audit.jsonl")
    audit_entries = audit_logger.load_audit_entries(document_path=entry.document_path, limit=1)
    
    audit_data = None
    if audit_entries:
        audit_data = audit_entries[0]
    
    return render_template(
        'review_document.html',
        entry=entry,
        audit=audit_data
    )


@review_bp.route('/review/submit', methods=['POST'])
def submit_review():
    """Speichert Korrekturen und gibt Dokument frei."""
    data = request.json
    
    document_path = data.get('document_path')
    reviewed_by = data.get('reviewed_by', 'admin')
    
    corrected_supplier = data.get('supplier')
    corrected_date = data.get('date')
    corrected_doctype = data.get('document_type')
    
    # Validierung
    if not document_path:
        return jsonify({"error": "document_path fehlt"}), 400
    
    # Quarantäne-Manager
    qm = QuarantineManager(
        quarantine_dir=config.QUARANTINE_DIR,
        quarantine_log=config.DATA_DIR / "quarantine.jsonl"
    )
    
    # Markiere als reviewed
    entry = qm.mark_reviewed(
        document_path=document_path,
        reviewed_by=reviewed_by,
        corrected_supplier=corrected_supplier,
        corrected_date=corrected_date,
        corrected_doctype=corrected_doctype
    )
    
    if not entry:
        return jsonify({"error": "Dokument nicht gefunden"}), 404
    
    # Speichere Korrekturen im Audit-Log
    audit_logger = AuditLogger(config.DATA_DIR / "audit.jsonl")
    
    if corrected_supplier:
        audit_logger.add_correction(
            document_path=document_path,
            field_name="supplier",
            corrected_value=corrected_supplier,
            reviewed_by=reviewed_by
        )
    
    if corrected_date:
        audit_logger.add_correction(
            document_path=document_path,
            field_name="date",
            corrected_value=corrected_date,
            reviewed_by=reviewed_by
        )
    
    if corrected_doctype:
        audit_logger.add_correction(
            document_path=document_path,
            field_name="document_type",
            corrected_value=corrected_doctype,
            reviewed_by=reviewed_by
        )
    
    # Gib Dokument frei
    released_path = qm.release_from_quarantine(
        document_path=document_path,
        target_dir=config.OUT_DIR
    )
    
    if not released_path:
        return jsonify({"error": "Freigabe fehlgeschlagen"}), 500
    
    _LOGGER.info(f"Review abgeschlossen: {document_path} → {released_path}")
    
    return jsonify({
        "success": True,
        "released_path": str(released_path),
        "corrections": {
            "supplier": corrected_supplier,
            "date": corrected_date,
            "document_type": corrected_doctype
        }
    })


@review_bp.route('/review/stats')
def review_stats():
    """Statistiken über Quarantäne & Reviews."""
    qm = QuarantineManager(
        quarantine_dir=config.QUARANTINE_DIR,
        quarantine_log=config.DATA_DIR / "quarantine.jsonl"
    )
    
    all_entries = qm.list_quarantine()
    reviewed = [e for e in all_entries if e.reviewed]
    pending = [e for e in all_entries if not e.reviewed]
    
    return jsonify({
        "total": len(all_entries),
        "reviewed": len(reviewed),
        "pending": len(pending),
        "review_rate": len(reviewed) / len(all_entries) if all_entries else 0.0
    })
