"""
Automatischer Retrain-Scheduler für Docaro ML-Modelle.
"""

import json
import logging
import os
import socket
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
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

    def _effective_mlflow_tracking_uri(self) -> str:
        """Ermittelt eine funktionierende MLflow Tracking URI.

        Priorität:
        1) Env `DOCARO_MLFLOW_TRACKING_URI` / `MLFLOW_TRACKING_URI`
        2) `self.mlflow_tracking_uri`

        Falls eine http(s)-URI nicht erreichbar ist, wird auf lokalen File-Store
        unter `<DATA_DIR>/mlflow` ausgewichen.
        """

        env_uri = os.getenv("DOCARO_MLFLOW_TRACKING_URI") or os.getenv("MLFLOW_TRACKING_URI")
        candidate = (env_uri or self.mlflow_tracking_uri or "").strip()

        if not candidate:
            fallback_dir = (self.audit_log_path.parent / "mlflow")
            fallback_dir.mkdir(parents=True, exist_ok=True)
            return f"file:{fallback_dir}"

        parsed = urlparse(candidate)

        if parsed.scheme in ("http", "https"):
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if not host:
                _LOGGER.warning(f"Ungültige MLflow Tracking URI: {candidate}. Nutze lokalen File-Store.")
            else:
                try:
                    with socket.create_connection((host, port), timeout=1.0):
                        return candidate
                except OSError:
                    _LOGGER.warning(
                        f"MLflow Tracking Server nicht erreichbar ({candidate}). Nutze lokalen File-Store."
                    )

            fallback_dir = (self.audit_log_path.parent / "mlflow")
            fallback_dir.mkdir(parents=True, exist_ok=True)
            return f"file:{fallback_dir}"

        if parsed.scheme == "file":
            local_path = Path(unquote(parsed.path))
            try:
                local_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                _LOGGER.warning(f"Konnte MLflow File-Store Verzeichnis nicht anlegen ({local_path}): {e}")
            return candidate

        # Andere Schemes (z.B. sqlite) unverändert nutzen
        return candidate
    
    def collect_training_data(self) -> dict:
        """
        Sammelt Trainingsdaten aus Audit-Log und Ground Truth.
        
        Returns:
            Dict mit Korrekturen pro Feld
        """
        # Try ground_truth.jsonl as fallback
        ground_truth_path = self.audit_log_path.parent / "ml" / "ground_truth.jsonl"
        
        data_path = self.audit_log_path if self.audit_log_path.exists() else ground_truth_path
        
        if not data_path.exists():
            _LOGGER.warning(f"Keine Trainingsdaten gefunden: {self.audit_log_path} oder {ground_truth_path}")
            return {}
        
        training_data = {
            "supplier": [],
            "date": [],
            "doctype": []
        }
        
        _LOGGER.info(f"Lade Trainingsdaten von: {data_path}")
        
        with open(data_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Ground Truth Format: {"doc_id", "text", "labels": {...}}
                # Audit Format: {"corrections": {...}, "extractions": {...}}
                
                if "labels" in entry:
                    # Ground Truth Format
                    text = entry.get("text", "")
                    labels = entry.get("labels", {})
                    
                    if labels.get("supplier_canonical"):
                        training_data["supplier"].append({
                            "ocr_text": text,
                            "corrected_value": labels["supplier_canonical"]
                        })
                    if labels.get("doc_type"):
                        training_data["doctype"].append({
                            "ocr_text": text,
                            "corrected_value": labels["doc_type"]
                        })
                    if labels.get("doc_date_iso"):
                        training_data["date"].append({
                            "ocr_text": text,
                            "corrected_value": labels["doc_date_iso"]
                        })
                
                else:
                    # Audit Format (mit Korrekturen)
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
                                "ocr_text": text,
                                "corrected_value": label
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
        
        _LOGGER.info(f"Training Supplier-Modell mit {len(training_data)} Samples...")
        
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import train_test_split
            from sklearn.pipeline import Pipeline
            import joblib
        except ImportError as e:
            _LOGGER.error(f"Missing dependencies for ML training: {e}")
            return

        # Prepare training data
        texts: list[str] = []
        labels: list[str] = []
        for item in training_data:
            text = item.get("ocr_text", "")
            label = item.get("corrected_value", "")
            if text and label:
                texts.append(text[:1000])  # First 1000 chars
                labels.append(label)

        if len(texts) < 5:
            _LOGGER.warning(f"Zu wenige valide Samples: {len(texts)}")
            return

        # Train model (unabhängig von MLflow)
        model = Pipeline([
            ("tfidf", TfidfVectorizer(max_features=500, ngram_range=(1, 2))),
            ("clf", LogisticRegression(max_iter=1000, random_state=42)),
        ])

        if len(texts) >= 10:
            X_train, X_test, y_train, y_test = train_test_split(
                texts, labels, test_size=0.2, random_state=42
            )
            model.fit(X_train, y_train)
            accuracy = float(model.score(X_test, y_test))
        else:
            model.fit(texts, labels)
            accuracy = 0.0  # No test set

        # Save model locally (immer)
        model_path = Path(self.audit_log_path).parent / "ml" / "supplier_model.pkl"
        model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, model_path)
        _LOGGER.info(f"Modell gespeichert: {model_path}")

        # MLflow logging (best-effort)
        try:
            import mlflow

            effective_uri = self._effective_mlflow_tracking_uri()
            if effective_uri:
                mlflow.set_tracking_uri(effective_uri)
            mlflow.set_experiment(self.experiment_name)

            with mlflow.start_run(run_name=f"supplier_training_{datetime.now():%Y%m%d_%H%M%S}"):
                mlflow.log_param("n_samples", len(texts))
                mlflow.log_param("model_type", "tfidf_logreg")
                mlflow.log_param("max_features", 500)
                if accuracy > 0:
                    mlflow.log_metric("test_accuracy", accuracy)

                try:
                    mlflow.log_artifact(str(model_path))
                except Exception as artifact_err:
                    _LOGGER.warning(f"Artifact upload fehlgeschlagen (nicht kritisch): {artifact_err}")

        except ImportError:
            _LOGGER.info("MLflow nicht installiert – überspringe MLflow-Logging")
        except Exception as e:
            _LOGGER.warning(f"MLflow-Logging fehlgeschlagen (nicht kritisch): {e}")

        _LOGGER.info(f"Supplier-Modell trainiert (Acc: {accuracy:.3f}) und gespeichert")
    
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
        
        # IMPLEMENTATION NEEDED: Weitere Modelle trainieren
        # - Date Extractor: ML-basierte Datumserkennung (ergänzend zu regex-basierten Patterns)
        # - Document Type Classifier: Erkennung von Rechnung/Lieferschein/etc.
        # 
        # Hinweis: Date-Extraktion nutzt aktuell optimierte DATE_REGEX_PATTERNS aus constants.py
        # Doctype-Klassifikation erfolgt durch core/doctype_classifier.py
        
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
