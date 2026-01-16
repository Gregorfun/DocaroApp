"""
Quarantäne-Manager für unsichere Dokumente.
"""

import json
import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_LOGGER = logging.getLogger(__name__)


@dataclass
class QuarantineEntry:
    """Eintrag für quarantäniertes Dokument."""
    document_path: str
    original_name: str
    quarantine_reason: str
    quarantined_at: str
    
    # Extrahierte Daten (unsicher)
    supplier: Optional[str] = None
    supplier_confidence: float = 0.0
    date: Optional[str] = None
    date_confidence: float = 0.0
    document_type: Optional[str] = None
    doctype_confidence: float = 0.0
    
    # Status
    reviewed: bool = False
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    
    # Korrekturen
    corrected_supplier: Optional[str] = None
    corrected_date: Optional[str] = None
    corrected_doctype: Optional[str] = None


class QuarantineManager:
    """
    Verwaltet Dokumente in Quarantäne.
    
    Workflow:
    1. Dokument → Quarantäne-Ordner
    2. Metadaten → quarantine.jsonl
    3. Review über Web-UI
    4. Nach Korrektur → reguläre Pipeline
    """
    
    def __init__(self, quarantine_dir: Path, quarantine_log: Path):
        """
        Args:
            quarantine_dir: Ordner für Quarantäne-PDFs
            quarantine_log: JSONL-Log für Metadaten
        """
        self.quarantine_dir = quarantine_dir
        self.quarantine_log = quarantine_log
        
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_log.parent.mkdir(parents=True, exist_ok=True)
    
    def add_to_quarantine(
        self,
        pdf_path: Path,
        reason: str,
        supplier: Optional[str] = None,
        supplier_confidence: float = 0.0,
        date: Optional[str] = None,
        date_confidence: float = 0.0,
        document_type: Optional[str] = None,
        doctype_confidence: float = 0.0
    ) -> QuarantineEntry:
        """
        Verschiebt Dokument in Quarantäne.
        
        Returns:
            QuarantineEntry
        """
        # Verschiebe PDF
        quarantine_path = self.quarantine_dir / pdf_path.name
        
        try:
            shutil.move(str(pdf_path), str(quarantine_path))
        except Exception as e:
            _LOGGER.error(f"Fehler beim Verschieben in Quarantäne: {e}")
            # Fallback: Kopieren
            shutil.copy2(str(pdf_path), str(quarantine_path))
        
        # Erstelle Eintrag
        entry = QuarantineEntry(
            document_path=str(quarantine_path),
            original_name=pdf_path.name,
            quarantine_reason=reason,
            quarantined_at=datetime.now().isoformat(),
            supplier=supplier,
            supplier_confidence=supplier_confidence,
            date=date,
            date_confidence=date_confidence,
            document_type=document_type,
            doctype_confidence=doctype_confidence
        )
        
        # Speichere in Log
        with open(self.quarantine_log, "a", encoding="utf-8") as f:
            json.dump(asdict(entry), f, ensure_ascii=False)
            f.write("\n")
        
        _LOGGER.info(f"Dokument in Quarantäne: {pdf_path.name} (Grund: {reason})")
        
        return entry
    
    def list_quarantine(self, reviewed: Optional[bool] = None) -> List[QuarantineEntry]:
        """
        Listet Quarantäne-Einträge.
        
        Args:
            reviewed: Filter nach reviewed-Status (None = alle)
        
        Returns:
            Liste von QuarantineEntry
        """
        if not self.quarantine_log.exists():
            return []
        
        entries = []
        
        with open(self.quarantine_log, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                
                data = json.loads(line)
                entry = QuarantineEntry(**data)
                
                if reviewed is not None and entry.reviewed != reviewed:
                    continue
                
                entries.append(entry)
        
        return entries
    
    def mark_reviewed(
        self,
        document_path: str,
        reviewed_by: str,
        corrected_supplier: Optional[str] = None,
        corrected_date: Optional[str] = None,
        corrected_doctype: Optional[str] = None
    ):
        """
        Markiert Dokument als reviewed und speichert Korrekturen.
        
        Args:
            document_path: Pfad zum Dokument
            reviewed_by: Username/Email des Reviewers
            corrected_supplier: Korrigierter Lieferant (falls geändert)
            corrected_date: Korrigiertes Datum
            corrected_doctype: Korrigierter Dokumenttyp
        """
        entries = self.list_quarantine()
        
        for entry in entries:
            if entry.document_path == document_path:
                entry.reviewed = True
                entry.reviewed_at = datetime.now().isoformat()
                entry.reviewed_by = reviewed_by
                entry.corrected_supplier = corrected_supplier
                entry.corrected_date = corrected_date
                entry.corrected_doctype = corrected_doctype
                
                # Append zu Log
                with open(self.quarantine_log, "a", encoding="utf-8") as f:
                    json.dump(asdict(entry), f, ensure_ascii=False)
                    f.write("\n")
                
                _LOGGER.info(f"Dokument reviewed: {document_path} (von {reviewed_by})")
                
                return entry
        
        _LOGGER.warning(f"Dokument nicht in Quarantäne gefunden: {document_path}")
        return None
    
    def release_from_quarantine(
        self,
        document_path: str,
        target_dir: Path
    ) -> Optional[Path]:
        """
        Entfernt Dokument aus Quarantäne und verschiebt zu target_dir.
        
        Returns:
            Neuer Pfad oder None bei Fehler
        """
        src = Path(document_path)
        
        if not src.exists():
            _LOGGER.error(f"Dokument existiert nicht: {document_path}")
            return None
        
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / src.name
        
        try:
            shutil.move(str(src), str(target_path))
            _LOGGER.info(f"Dokument freigegeben: {src.name} → {target_dir}")
            return target_path
        except Exception as e:
            _LOGGER.error(f"Fehler beim Freigeben aus Quarantäne: {e}")
            return None
