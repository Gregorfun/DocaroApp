"""
Automatischer Retrain-Scheduler für Docaro ML-Modelle.
"""

import json
import logging
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Optional

_LOGGER = logging.getLogger(__name__)


class RetrainScheduler:
    """
    Nachtjob für automatisches Model-Retraining.
    
    Workflow:
    1. Sammle Korrekturen seit letztem Training
    2. Trainiere neues Modell
    3. Validiere mit MLflow
    4. Aktiviere bestes Modell
    """
    
    def __init__(
        self,
        audit_log_path: Path,
        mlflow_tracking_uri: str,
        experiment_name: str = "docaro_training",
        min_corrections: int = 10,
        schedule_time: time = time(2, 0)  # 02:00 Uhr
    ):
        """
        Args:
            audit_log_path: Pfad zu Audit-Log (JSONL)
            mlflow_tracking_uri: MLflow Tracking Server
            experiment_name: MLflow Experiment Name
            min_corrections: Min. Anzahl Korrekturen für Training
            schedule_time: Uhrzeit für Training
        """
        self.audit_log_path = audit_log_path
        self.mlflow_tracking_uri = mlflow_tracking_uri
        self.experiment_name = experiment_name
        self.min_corrections = min_corrections
        self.schedule_time = schedule_time
        self.last_train_date: Optional[datetime] = None
    
    def collect_training_data(self) -> dict:
        """
        Sammelt Trainingsdaten aus Audit-Log.
        
        Returns:
            Dict mit Korrekturen pro Feld
        """
        if not self.audit_log_path.exists():
            _LOGGER.warning("Audit-Log nicht gefunden")
            return {}
        
        training_data = {
            "supplier": [],
            "date": [],
            "doctype": []
        }
        
        with open(self.audit_log_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Nur Einträge mit Korrekturen
                corrections = entry.get("corrections", {})
                if not corrections:
                    continue
                
                # Prüfe ob nach letztem Training
                if self.last_train_date:
                    reviewed_at = entry.get("reviewed_at")
                    if reviewed_at:
                        review_dt = datetime.fromisoformat(reviewed_at)
                        if review_dt < self.last_train_date:
                            continue
                
                # Extrahiere Features & Labels
                extractions = entry.get("extractions", {})
                
                for field in ["supplier", "date", "doctype"]:
                    if field in corrections:
                        text = extractions.get(field, {}).get("text_snippet", "")
                        label = corrections[field]
                        training_data[field].append({
                            "text": text,
                            "label": label,
                            "document": entry.get("document_path")
                        })
        
        _LOGGER.info(
            f"Trainingsdaten: "
            f"supplier={len(training_data['supplier'])}, "
            f"date={len(training_data['date'])}, "
            f"doctype={len(training_data['doctype'])}"
        )
        
        return training_data
    
    def should_train(self) -> bool:
        """Prüft ob Training durchgeführt werden soll."""
        training_data = self.collect_training_data()
        total_corrections = sum(len(v) for v in training_data.values())
        
        if total_corrections < self.min_corrections:
            _LOGGER.info(f"Zu wenige Korrekturen: {total_corrections} < {self.min_corrections}")
            return False
        
        return True
    
    def train_supplier_model(self, training_data: list):
        """Trainiert Supplier-Klassifikator."""
        if not training_data:
            _LOGGER.info("Keine Supplier-Trainingsdaten")
            return
        
        # Hier würde ML-Training-Code stehen
        # Beispiel: sklearn + MLflow
        _LOGGER.info(f"Training Supplier-Modell mit {len(training_data)} Samples...")
        
        try:
            import mlflow
            mlflow.set_tracking_uri(self.mlflow_tracking_uri)
            mlflow.set_experiment(self.experiment_name)
            
            with mlflow.start_run(run_name=f"supplier_training_{datetime.now():%Y%m%d_%H%M%S}"):
                # TODO: Implementiere Training-Logik
                # z.B. sklearn TfidfVectorizer + LogisticRegression
                # oder sentence-transformers Embeddings + Cosine-Similarity
                
                mlflow.log_param("n_samples", len(training_data))
                mlflow.log_param("model_type", "supplier_classifier")
                
                # Placeholder: Log Dummy-Metrik
                mlflow.log_metric("accuracy", 0.95)
                
                _LOGGER.info("Supplier-Modell trainiert und in MLflow geloggt")
        
        except Exception as e:
            _LOGGER.error(f"Fehler beim Supplier-Training: {e}")
    
    def run_training_job(self):
        """Führt kompletten Training-Job aus."""
        _LOGGER.info("=== Starte Retrain-Job ===")
        
        if not self.should_train():
            _LOGGER.info("Kein Training nötig")
            return
        
        training_data = self.collect_training_data()
        
        # Trainiere Modelle
        if training_data["supplier"]:
            self.train_supplier_model(training_data["supplier"])
        
        # TODO: Weitere Modelle trainieren (Date, Doctype)
        
        # Aktualisiere letztes Training-Datum
        self.last_train_date = datetime.now()
        
        _LOGGER.info("=== Retrain-Job abgeschlossen ===")
    
    def run_scheduled(self):
        """Wartet auf Schedule-Zeit und führt Training aus."""
        import time as time_module
        
        while True:
            now = datetime.now()
            target = datetime.combine(now.date(), self.schedule_time)
            
            if now > target:
                # Nächster Tag
                target = datetime.combine(now.date(), self.schedule_time)
                from datetime import timedelta
                target += timedelta(days=1)
            
            wait_seconds = (target - now).total_seconds()
            _LOGGER.info(f"Nächstes Training: {target} (in {wait_seconds/3600:.1f}h)")
            
            time_module.sleep(wait_seconds)
            
            # Führe Training aus
            self.run_training_job()


if __name__ == "__main__":
    from config import Config
    config = Config()
    
    scheduler = RetrainScheduler(
        audit_log_path=config.DATA_DIR / "audit.jsonl",
        mlflow_tracking_uri="http://localhost:5000",
        experiment_name="docaro_retrain"
    )
    
    # Test-Run
    scheduler.run_training_job()
