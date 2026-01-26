"""
Review Service: Human-in-the-Loop Review Queue mit Confidence Gates.

Zentrale Logik für:
- Entscheidung ob Dokument NEEDS_REVIEW oder READY (Gate-Check)
- Finalize-Prozess (Rename + AutoSort)
- ML Feedback (Ground Truth speichern)
"""

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


# Status Enum
class DocumentStatus:
    NEW = "NEW"
    EXTRACTED = "EXTRACTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY = "READY"
    FINALIZED = "FINALIZED"
    ERROR = "ERROR"


# Reason Codes
class ReviewReasonCode:
    MISSING_SUPPLIER = "MISSING_SUPPLIER"
    SUPPLIER_CONF_LOW = "SUPPLIER_CONF_LOW"
    MISSING_DATE = "MISSING_DATE"
    DATE_CONF_LOW = "DATE_CONF_LOW"
    DATE_PARSE_FAIL = "DATE_PARSE_FAIL"
    MISSING_DOC_TYPE = "MISSING_DOC_TYPE"
    DOC_TYPE_CONF_LOW = "DOC_TYPE_CONF_LOW"
    MISSING_DOC_NUMBER = "MISSING_DOC_NUMBER"
    DOC_NUMBER_CONF_LOW = "DOC_NUMBER_CONF_LOW"
    EXTRACTION_ERROR = "EXTRACTION_ERROR"


@dataclass
class ReviewDecision:
    """Ergebnis der Gate-Entscheidung."""
    status: str  # NEEDS_REVIEW | READY
    reasons: List[str]  # Reason Codes
    details: Dict[str, any]


@dataclass
class FinalizeResult:
    """Ergebnis der Finalisierung."""
    success: bool
    finalized_path: Optional[Path]
    final_filename: str
    autosort_reason: str
    name_reason: str
    error: Optional[str] = None


@dataclass
class ReviewSettings:
    """Settings für Review Gates."""
    gate_supplier_min: float = 0.80
    gate_date_min: float = 0.80
    gate_doc_type_min: float = 0.70
    gate_doc_number_min: float = 0.80
    auto_finalize_enabled: bool = False
    autosort_enabled: bool = False
    autosort_base_dir: Path = Path(".")


def _parse_float(value) -> float:
    """Parse float from various formats."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except (ValueError, AttributeError):
        return 0.0


def decide_review_status(
    extraction_result: Dict,
    settings: ReviewSettings
) -> ReviewDecision:
    """
    Entscheidet ob Dokument NEEDS_REVIEW oder READY ist.
    
    Args:
        extraction_result: Result dict von process_pdf() mit allen Feldern
        settings: ReviewSettings mit Gate-Thresholds
    
    Returns:
        ReviewDecision mit status und reasons
    """
    reasons = []
    details = {}
    
    # 1. Supplier Check
    supplier = (extraction_result.get("supplier_canonical") or "").strip()
    supplier_conf = _parse_float(extraction_result.get("supplier_confidence"))
    details["supplier"] = supplier
    details["supplier_confidence"] = supplier_conf
    
    if not supplier or supplier == "Unbekannt":
        reasons.append(ReviewReasonCode.MISSING_SUPPLIER)
    elif supplier_conf < settings.gate_supplier_min:
        reasons.append(ReviewReasonCode.SUPPLIER_CONF_LOW)
    
    # 2. Date Check
    date_iso = (extraction_result.get("date") or "").strip()
    date_conf = _parse_float(extraction_result.get("date_confidence"))
    details["date"] = date_iso
    details["date_confidence"] = date_conf
    
    if not date_iso:
        reasons.append(ReviewReasonCode.MISSING_DATE)
    elif date_conf < settings.gate_date_min:
        reasons.append(ReviewReasonCode.DATE_CONF_LOW)
    
    # 3. DocType Check
    doc_type = (extraction_result.get("doc_type") or "").strip()
    doc_type_conf = _parse_float(extraction_result.get("doc_type_confidence"))
    details["doc_type"] = doc_type
    details["doc_type_confidence"] = doc_type_conf
    
    if not doc_type or doc_type == "SONSTIGES":
        reasons.append(ReviewReasonCode.MISSING_DOC_TYPE)
    elif doc_type_conf < settings.gate_doc_type_min:
        reasons.append(ReviewReasonCode.DOC_TYPE_CONF_LOW)
    
    # 4. DocNumber Check
    doc_number = (extraction_result.get("doc_number") or "").strip()
    doc_number_conf_str = extraction_result.get("doc_number_confidence", "none")
    # Map confidence string to float
    conf_map = {"high": 0.95, "medium": 0.75, "low": 0.50, "none": 0.0}
    doc_number_conf = conf_map.get(doc_number_conf_str, 0.0)
    details["doc_number"] = doc_number
    details["doc_number_confidence"] = doc_number_conf
    
    if not doc_number or doc_number.startswith("ohneNr"):
        reasons.append(ReviewReasonCode.MISSING_DOC_NUMBER)
    elif doc_number_conf < settings.gate_doc_number_min:
        reasons.append(ReviewReasonCode.DOC_NUMBER_CONF_LOW)
    
    # Entscheidung
    if reasons:
        return ReviewDecision(
            status=DocumentStatus.NEEDS_REVIEW,
            reasons=reasons,
            details=details
        )
    else:
        return ReviewDecision(
            status=DocumentStatus.READY,
            reasons=[],
            details=details
        )


def _sanitize_filename_component(value: str) -> str:
    """Bereinigt Komponente für Dateinamen."""
    import re
    if not value:
        return ""
    # Entferne verbotene Zeichen
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", value)
    # Entferne Whitespace-Rauschen
    cleaned = re.sub(r'\s+', " ", cleaned).strip()
    # Entferne "scan", "Scan", "SCAN" Präfixe
    cleaned = re.sub(r'^scan[_\s-]*', "", cleaned, flags=re.IGNORECASE)
    # Entferne Timestamps (yyyy-mm-dd_hh-mm-ss oder ähnlich)
    cleaned = re.sub(r'\d{4}-\d{2}-\d{2}[_\s-]+\d{2}[:-]\d{2}[:-]\d{2}', "", cleaned)
    cleaned = re.sub(r'\d{8}[_\s-]+\d{6}', "", cleaned)  # 20260121_143022
    return cleaned.strip("_- ")


def build_final_filename(
    supplier_canonical: str,
    date_iso: str,
    doc_number: str,
    original_filename: str = ""
) -> str:
    """
    Baut finalen Dateinamen: <Supplier>_<YYYY-MM-DD>_<DocNumber>.pdf
    
    Entfernt "scan" Präfixe und Timestamps komplett.
    """
    supplier_clean = _sanitize_filename_component(supplier_canonical) or "Unbekannt"
    date_clean = date_iso[:10] if date_iso else "0000-00-00"  # YYYY-MM-DD
    
    # DocNumber bereinigen
    doc_number_clean = _sanitize_filename_component(doc_number) or "ohneNr"
    
    # Limit lengths
    supplier_clean = supplier_clean[:60]
    doc_number_clean = doc_number_clean[:80]
    
    return f"{supplier_clean}_{date_clean}_{doc_number_clean}.pdf"


def _make_unique_filename(target_dir: Path, filename: str) -> Path:
    """Macht Dateinamen eindeutig mit _01, _02, etc."""
    target = target_dir / filename
    if not target.exists():
        return target
    
    stem = target.stem
    suffix = target.suffix or ".pdf"
    counter = 1
    while True:
        candidate = target_dir / f"{stem}_{counter:02d}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
        if counter > 99:  # Safety
            raise ValueError(f"Too many duplicates for {filename}")


def finalize_document(
    doc_id: str,
    source_path: Path,
    extraction_result: Dict,
    settings: ReviewSettings,
    mode: str = "move"
) -> FinalizeResult:
    """
    Finalisiert Dokument: Rename + AutoSort.
    
    Args:
        doc_id: Dokument-ID
        source_path: Aktueller PDF-Pfad
        extraction_result: Extraction-Daten (supplier, date, doc_number, etc.)
        settings: ReviewSettings mit autosort_enabled, autosort_base_dir
        mode: "move" oder "copy"
    
    Returns:
        FinalizeResult mit finalized_path
    """
    try:
        # 1. Daten extrahieren
        supplier = extraction_result.get("supplier_canonical", "Unbekannt")
        date_iso = extraction_result.get("date", "")
        doc_number = extraction_result.get("doc_number", "ohneNr")
        
        # 2. Finalen Namen bauen
        final_filename = build_final_filename(supplier, date_iso, doc_number)
        name_reason = f"Renamed to {final_filename}"
        
        # 3. Zielverzeichnis bestimmen
        if settings.autosort_enabled and settings.autosort_base_dir:
            # AutoSort: <Base>/<Supplier>/<YYYY-MM>/
            try:
                date_obj = datetime.fromisoformat(date_iso[:10])
                year_month = date_obj.strftime("%Y-%m")
                supplier_clean = _sanitize_filename_component(supplier)
                target_dir = settings.autosort_base_dir / supplier_clean / year_month
                autosort_reason = f"AutoSorted to {target_dir}"
            except (ValueError, AttributeError):
                # Fallback: kein AutoSort wenn Datum ungültig
                target_dir = source_path.parent
                autosort_reason = "AutoSort failed (invalid date), kept in same dir"
        else:
            # Kein AutoSort: gleiches Verzeichnis
            target_dir = source_path.parent
            autosort_reason = "AutoSort disabled"
        
        # 4. Unique Target
        target_dir.mkdir(parents=True, exist_ok=True)
        final_path = _make_unique_filename(target_dir, final_filename)
        
        # 5. Move/Copy
        if mode == "copy":
            shutil.copy2(source_path, final_path)
        else:
            shutil.move(str(source_path), str(final_path))
        
        _LOGGER.info(f"Finalized doc {doc_id}: {final_path}")
        
        return FinalizeResult(
            success=True,
            finalized_path=final_path,
            final_filename=final_filename,
            autosort_reason=autosort_reason,
            name_reason=name_reason
        )
    
    except Exception as exc:
        _LOGGER.error(f"Finalize failed for doc {doc_id}: {exc}")
        return FinalizeResult(
            success=False,
            finalized_path=None,
            final_filename="",
            autosort_reason="",
            name_reason="",
            error=str(exc)
        )


def save_correction(
    corrections_path: Path,
    doc_id: str,
    user_email: str,
    original: Dict,
    corrected: Dict
) -> None:
    """
    Speichert Korrektur für Audit + ML Training.
    
    Args:
        corrections_path: Path zu corrections.json
        doc_id: Dokument-ID
        user_email: User Email
        original: Original extraction values
        corrected: Korrigierte Werte
    """
    corrections_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing
    if corrections_path.exists():
        corrections = json.loads(corrections_path.read_text(encoding="utf-8"))
    else:
        corrections = []
    
    # Append new correction
    correction = {
        "id": len(corrections) + 1,
        "doc_id": doc_id,
        "user_email": user_email,
        "original_supplier_canonical": original.get("supplier_canonical"),
        "original_doc_type": original.get("doc_type"),
        "original_doc_date_iso": original.get("date"),
        "original_doc_number": original.get("doc_number"),
        "corrected_supplier_canonical": corrected.get("supplier_canonical"),
        "corrected_doc_type": corrected.get("doc_type"),
        "corrected_doc_date_iso": corrected.get("date"),
        "corrected_doc_number": corrected.get("doc_number"),
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    
    corrections.append(correction)
    
    # Save
    corrections_path.write_text(
        json.dumps(corrections, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    
    _LOGGER.info(f"Saved correction for doc {doc_id} by {user_email}")


def save_ground_truth_sample(
    ground_truth_path: Path,
    doc_id: str,
    ocr_text: str,
    corrected_labels: Dict
) -> None:
    """
    Speichert Ground Truth Sample für ML Training (JSONL append).
    
    Args:
        ground_truth_path: Path zu ground_truth.jsonl
        doc_id: Dokument-ID
        ocr_text: OCR Text (Input)
        corrected_labels: Korrigierte Labels (Output)
    """
    ground_truth_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Build sample
    sample = {
        "doc_id": doc_id,
        "text": ocr_text[:5000],  # Limit text length
        "labels": {
            "supplier_canonical": corrected_labels.get("supplier_canonical"),
            "doc_type": corrected_labels.get("doc_type"),
            "doc_date_iso": corrected_labels.get("date"),
            "doc_number": corrected_labels.get("doc_number")
        },
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    
    # Append to JSONL
    with ground_truth_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    
    _LOGGER.info(f"Saved ground truth sample for doc {doc_id}")


def load_review_settings(settings_path: Path) -> ReviewSettings:
    """Lädt Review Settings aus settings.json."""
    if not settings_path.exists():
        return ReviewSettings()
    
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        return ReviewSettings(
            gate_supplier_min=float(data.get("gate_supplier_min", 0.80)),
            gate_date_min=float(data.get("gate_date_min", 0.80)),
            gate_doc_type_min=float(data.get("gate_doc_type_min", 0.70)),
            gate_doc_number_min=float(data.get("gate_doc_number_min", 0.80)),
            auto_finalize_enabled=bool(data.get("auto_finalize_enabled", False)),
            autosort_enabled=bool(data.get("autosort_enabled", False)),
            autosort_base_dir=Path(data.get("autosort_base_dir", "."))
        )
    except Exception as exc:
        _LOGGER.warning(f"Failed to load review settings: {exc}")
        return ReviewSettings()


def save_review_settings(settings_path: Path, settings: ReviewSettings) -> None:
    """Speichert Review Settings in settings.json."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing settings (to merge)
    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        data = {}
    
    # Update review-related settings
    data.update({
        "gate_supplier_min": settings.gate_supplier_min,
        "gate_date_min": settings.gate_date_min,
        "gate_doc_type_min": settings.gate_doc_type_min,
        "gate_doc_number_min": settings.gate_doc_number_min,
        "auto_finalize_enabled": settings.auto_finalize_enabled,
        "autosort_enabled": settings.autosort_enabled,
        "autosort_base_dir": str(settings.autosort_base_dir)
    })
    
    # Save
    settings_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
