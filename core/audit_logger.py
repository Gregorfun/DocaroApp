"""
Audit-Logging für Erklärbarkeit und Training.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


@dataclass
class FieldExtraction:
    """Metadaten für ein extrahiertes Feld."""
    field_name: str
    value: Any
    confidence: float
    page: int
    text_snippet: str
    bbox: Optional[Tuple[int, int, int, int]] = None  # x, y, w, h
    reasons: List[str] = field(default_factory=list)
    extracted_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AuditEntry:
    """Kompletter Audit-Eintrag für ein Dokument."""
    document_path: str
    document_hash: str
    processed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Extraktionen
    extractions: Dict[str, FieldExtraction] = field(default_factory=dict)
    
    # Pipeline-Metadaten
    pipeline_version: str = "1.0"
    ocr_method: Optional[str] = None
    processing_time_sec: float = 0.0
    
    # Status
    status: str = "success"  # success, quarantine, error
    error_message: Optional[str] = None
    
    # Review
    needs_review: bool = False
    review_reason: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    corrections: Dict[str, Any] = field(default_factory=dict)


class AuditLogger:
    """
    Zentraler Audit-Logger für Erklärbarkeit.
    
    Speichert:
    - Was wurde extrahiert
    - Woher (Seite, Text, Position)
    - Warum (Confidence, Gründe)
    - Wer hat korrigiert
    """
    
    def __init__(self, audit_log_path: Path):
        """
        Args:
            audit_log_path: JSONL-Datei für Audit-Einträge
        """
        self.audit_log_path = audit_log_path
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def log_extraction(
        self,
        document_path: Path,
        field_name: str,
        value: Any,
        confidence: float,
        page: int,
        text_snippet: str,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        reasons: Optional[List[str]] = None
    ) -> FieldExtraction:
        """
        Loggt eine Feld-Extraktion.
        
        Returns:
            FieldExtraction-Objekt
        """
        extraction = FieldExtraction(
            field_name=field_name,
            value=value,
            confidence=confidence,
            page=page,
            text_snippet=text_snippet,
            bbox=bbox,
            reasons=reasons or []
        )
        return extraction
    
    def create_audit_entry(
        self,
        document_path: Path,
        extractions: Dict[str, FieldExtraction],
        status: str = "success",
        ocr_method: Optional[str] = None,
        processing_time: float = 0.0,
        error_message: Optional[str] = None,
        needs_review: bool = False,
        review_reason: Optional[str] = None
    ) -> AuditEntry:
        """Erstellt kompletten Audit-Eintrag."""
        import hashlib
        
        # Berechne Dokument-Hash
        with open(document_path, "rb") as f:
            doc_hash = hashlib.sha256(f.read()).hexdigest()[:16]
        
        entry = AuditEntry(
            document_path=str(document_path),
            document_hash=doc_hash,
            extractions=extractions,
            status=status,
            ocr_method=ocr_method,
            processing_time_sec=processing_time,
            error_message=error_message,
            needs_review=needs_review,
            review_reason=review_reason
        )
        
        return entry
    
    def save_audit_entry(self, entry: AuditEntry):
        """Speichert Audit-Eintrag in JSONL."""
        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            # Konvertiere zu Dict (mit nested dataclasses)
            entry_dict = asdict(entry)
            json.dump(entry_dict, f, ensure_ascii=False)
            f.write("\n")
        
        _LOGGER.debug(f"Audit-Eintrag gespeichert: {entry.document_path}")
    
    def load_audit_entries(
        self,
        document_path: Optional[str] = None,
        limit: int = 100
    ) -> List[AuditEntry]:
        """Lädt Audit-Einträge (optional gefiltert)."""
        if not self.audit_log_path.exists():
            return []
        
        entries = []
        with open(self.audit_log_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                
                # Rekonstruiere FieldExtraction-Objekte
                extractions = {}
                for field, extr_data in data.get("extractions", {}).items():
                    extractions[field] = FieldExtraction(**extr_data)
                data["extractions"] = extractions
                
                entry = AuditEntry(**data)
                
                if document_path and entry.document_path != document_path:
                    continue
                
                entries.append(entry)
                
                if len(entries) >= limit:
                    break
        
        return entries
    
    def add_correction(
        self,
        document_path: str,
        field_name: str,
        corrected_value: Any,
        reviewed_by: str
    ):
        """Fügt Korrektur zu Audit-Eintrag hinzu."""
        entries = self.load_audit_entries(document_path=document_path, limit=1)
        if not entries:
            _LOGGER.warning(f"Kein Audit-Eintrag gefunden für: {document_path}")
            return
        
        entry = entries[0]
        entry.corrections[field_name] = corrected_value
        entry.reviewed_by = reviewed_by
        entry.reviewed_at = datetime.now().isoformat()
        
        # Schreibe zurück (append)
        self.save_audit_entry(entry)
        _LOGGER.info(f"Korrektur gespeichert: {field_name} = {corrected_value}")
