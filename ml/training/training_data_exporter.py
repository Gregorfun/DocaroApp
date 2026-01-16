"""
Trainingsdaten-Export für MLflow & Label Studio Integration.
"""

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_LOGGER = logging.getLogger(__name__)


class TrainingDataExporter:
    """
    Exportiert Korrekturen für ML-Training.
    
    Formate:
    - JSON für scikit-learn
    - Label Studio Tasks
    - MLflow Datasets
    """
    
    def __init__(self, audit_log_path: Path):
        self.audit_log_path = audit_log_path
    
    def export_for_sklearn(
        self,
        output_path: Path,
        field: str = "supplier",
        min_corrections: int = 5
    ):
        """
        Exportiert Trainingsdaten für sklearn.
        
        Args:
            output_path: Ausgabepfad (JSON)
            field: Feld (supplier, date, doctype)
            min_corrections: Min. Anzahl Korrekturen
        """
        training_samples = []
        
        if not self.audit_log_path.exists():
            _LOGGER.warning("Audit-Log nicht gefunden")
            return
        
        with open(self.audit_log_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                corrections = entry.get("corrections", {})
                if field not in corrections:
                    continue
                
                extractions = entry.get("extractions", {})
                if field not in extractions:
                    continue
                
                text = extractions[field].get("text_snippet", "")
                label = corrections[field]
                
                training_samples.append({
                    "text": text,
                    "label": label,
                    "document": entry.get("document_path"),
                    "corrected_at": entry.get("reviewed_at")
                })
        
        if len(training_samples) < min_corrections:
            _LOGGER.warning(
                f"Zu wenige Trainingsdaten: {len(training_samples)} < {min_corrections}"
            )
            return
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(training_samples, f, ensure_ascii=False, indent=2)
        
        _LOGGER.info(f"Exportiert: {len(training_samples)} Samples → {output_path}")
    
    def export_for_label_studio(
        self,
        output_path: Path,
        include_pdf_urls: bool = False
    ):
        """
        Exportiert Tasks für Label Studio.
        
        Args:
            output_path: Ausgabepfad (JSON)
            include_pdf_urls: PDFs als URLs einbinden
        """
        tasks = []
        
        if not self.audit_log_path.exists():
            return
        
        with open(self.audit_log_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Nur quarantänierte Dokumente ohne Review
                if not entry.get("needs_review") or entry.get("reviewed_at"):
                    continue
                
                task = {
                    "data": {
                        "document": entry.get("document_path"),
                        "text": entry.get("extractions", {}).get("supplier", {}).get("text_snippet", "")
                    },
                    "predictions": [{
                        "result": [
                            {
                                "value": {
                                    "text": [entry.get("extractions", {}).get("supplier", {}).get("value")]
                                },
                                "from_name": "supplier",
                                "to_name": "text",
                                "type": "labels"
                            }
                        ]
                    }]
                }
                
                if include_pdf_urls:
                    task["data"]["pdf_url"] = f"file://{entry.get('document_path')}"
                
                tasks.append(task)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        
        _LOGGER.info(f"Label Studio Tasks: {len(tasks)} → {output_path}")


if __name__ == "__main__":
    from config import Config
    config = Config()
    
    exporter = TrainingDataExporter(config.DATA_DIR / "audit.jsonl")
    
    # Export für sklearn
    exporter.export_for_sklearn(
        output_path=config.BASE_DIR / "ml" / "training" / "supplier_training.json",
        field="supplier"
    )
    
    # Export für Label Studio
    exporter.export_for_label_studio(
        output_path=config.BASE_DIR / "ml" / "training" / "label_studio_tasks.json"
    )
