"""
Automatischer Retrain-Scheduler für Docaro ML-Modelle.
"""

import json
import logging
import os
import socket
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
        self.production_meta_path = self.audit_log_path.parent / "ml" / "production_models.json"

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

    def train_supplier_model(self, training_data: list) -> Optional[tuple[Path, dict[str, float]]]:
        """Trainiert Supplier-Klassifikator."""
        if not training_data:
            _LOGGER.info("Keine Supplier-Trainingsdaten")
            return None

        _LOGGER.info(f"Training Supplier-Modell mit {len(training_data)} Samples...")

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import train_test_split
            from sklearn.pipeline import Pipeline
            import joblib
        except ImportError as e:
            _LOGGER.error(f"Missing dependencies for ML training: {e}")
            return None

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
            return None

        # Train model (unabhängig von MLflow)
        model = Pipeline([
            ("tfidf", TfidfVectorizer(max_features=500, ngram_range=(1, 2))),
            ("clf", LogisticRegression(max_iter=1000, random_state=42)),
        ])

        metrics: dict[str, float] = {}
        if len(texts) >= 10:
            X_train, X_test, y_train, y_test = train_test_split(
                texts, labels, test_size=0.2, random_state=42
            )
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            metrics = self._evaluate_classifier(y_test, y_pred)
        else:
            model.fit(texts, labels)
            metrics = {}

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
                for key, value in metrics.items():
                    mlflow.log_metric(key, float(value))

                try:
                    mlflow.log_artifact(str(model_path))
                except Exception as artifact_err:
                    _LOGGER.warning(f"Artifact upload fehlgeschlagen (nicht kritisch): {artifact_err}")

        except ImportError:
            _LOGGER.info("MLflow nicht installiert – überspringe MLflow-Logging")
        except Exception as e:
            _LOGGER.warning(f"MLflow-Logging fehlgeschlagen (nicht kritisch): {e}")

        if metrics:
            _LOGGER.info(
                "Supplier-Modell trainiert (accuracy=%.3f, f1_weighted=%.3f) und gespeichert",
                metrics.get("accuracy", 0.0),
                metrics.get("f1_weighted", 0.0),
            )
        else:
            _LOGGER.info("Supplier-Modell trainiert (ohne Holdout-Evaluation) und gespeichert")
        return model_path, metrics

    def _prepare_text_label_samples(self, training_data: list) -> tuple[list[str], list[str]]:
        texts: list[str] = []
        labels: list[str] = []
        for item in training_data or []:
            text = str(item.get("ocr_text", "") or "").strip()
            label = str(item.get("corrected_value", "") or "").strip()
            if text and label:
                texts.append(text[:1000])
                labels.append(label)
        return texts, labels

    def _evaluate_classifier(self, y_true: list[str], y_pred: list[str]) -> dict[str, float]:
        try:
            from sklearn.metrics import accuracy_score, precision_recall_fscore_support
        except Exception:
            return {}

        metrics: dict[str, float] = {}
        try:
            metrics["accuracy"] = float(accuracy_score(y_true, y_pred))
            p_macro, r_macro, f_macro, _ = precision_recall_fscore_support(
                y_true, y_pred, average="macro", zero_division=0
            )
            p_weighted, r_weighted, f_weighted, _ = precision_recall_fscore_support(
                y_true, y_pred, average="weighted", zero_division=0
            )
            metrics["precision_macro"] = float(p_macro)
            metrics["recall_macro"] = float(r_macro)
            metrics["f1_macro"] = float(f_macro)
            metrics["precision_weighted"] = float(p_weighted)
            metrics["recall_weighted"] = float(r_weighted)
            metrics["f1_weighted"] = float(f_weighted)
        except Exception as exc:
            _LOGGER.warning(f"Konnte Offline-Evaluation nicht berechnen: {exc}")
        return metrics

    def train_text_classifier_model(
        self,
        *,
        model_name: str,
        training_data: list,
        min_samples: int = 10,
    ) -> Optional[tuple[Path, dict[str, float]]]:
        """Trainiert einen einfachen TF-IDF + LogReg Text-Klassifikator.

        Returns:
            Dict mit Evaluationsmetriken (best-effort) oder None bei Skip/Fehler.
        """
        if not training_data:
            _LOGGER.info(f"Keine Trainingsdaten für {model_name}")
            return None

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import train_test_split
            from sklearn.pipeline import Pipeline
            import joblib
        except ImportError as e:
            _LOGGER.error(f"Missing dependencies for ML training ({model_name}): {e}")
            return None

        texts, labels = self._prepare_text_label_samples(training_data)
        if len(texts) < min_samples:
            _LOGGER.warning(f"Zu wenige valide Samples für {model_name}: {len(texts)} < {min_samples}")
            return None

        unique_labels = sorted(set(labels))
        if len(unique_labels) < 2:
            _LOGGER.warning(f"Zu wenige Klassen für {model_name}: {len(unique_labels)}")
            return None

        model = Pipeline(
            [
                ("tfidf", TfidfVectorizer(max_features=500, ngram_range=(1, 2))),
                ("clf", LogisticRegression(max_iter=1000, random_state=42)),
            ]
        )

        metrics: dict[str, float] = {}
        if len(texts) >= 20:
            X_train, X_test, y_train, y_test = train_test_split(
                texts, labels, test_size=0.2, random_state=42, stratify=labels
            )
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            metrics = self._evaluate_classifier(y_test, y_pred)
        else:
            model.fit(texts, labels)
            metrics = {}

        model_path = Path(self.audit_log_path).parent / "ml" / f"{model_name}_model.pkl"
        model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, model_path)
        _LOGGER.info(f"{model_name}-Modell gespeichert: {model_path}")

        # MLflow logging (best-effort)
        try:
            import mlflow

            effective_uri = self._effective_mlflow_tracking_uri()
            if effective_uri:
                mlflow.set_tracking_uri(effective_uri)
            mlflow.set_experiment(self.experiment_name)

            run_name = f"{model_name}_training_{datetime.now():%Y%m%d_%H%M%S}"
            with mlflow.start_run(run_name=run_name):
                mlflow.log_param("model_name", model_name)
                mlflow.log_param("n_samples", len(texts))
                mlflow.log_param("n_labels", len(unique_labels))
                mlflow.log_param("model_type", "tfidf_logreg")
                mlflow.log_param("max_features", 500)
                for key, value in metrics.items():
                    mlflow.log_metric(key, float(value))
                try:
                    mlflow.log_artifact(str(model_path))
                except Exception as artifact_err:
                    _LOGGER.warning(f"Artifact upload fehlgeschlagen ({model_name}): {artifact_err}")
        except ImportError:
            _LOGGER.info("MLflow nicht installiert – überspringe MLflow-Logging")
        except Exception as e:
            _LOGGER.warning(f"MLflow-Logging fehlgeschlagen ({model_name}): {e}")

        if metrics:
            _LOGGER.info(
                "%s-Modell trainiert (accuracy=%.3f, f1_weighted=%.3f)",
                model_name,
                metrics.get("accuracy", 0.0),
                metrics.get("f1_weighted", 0.0),
            )
        else:
            _LOGGER.info("%s-Modell trainiert (ohne Holdout-Evaluation)", model_name)
        return model_path, metrics

    def _load_production_meta(self) -> dict:
        if not self.production_meta_path.exists():
            return {}
        try:
            return json.loads(self.production_meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_production_meta(self, payload: dict) -> None:
        self.production_meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.production_meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _maybe_promote_model(self, model_name: str, model_path: Path, metrics: dict[str, float]) -> bool:
        min_accuracy = float(os.getenv("DOCARO_MODEL_MIN_ACCURACY", "0.0"))
        min_f1_weighted = float(os.getenv("DOCARO_MODEL_MIN_F1_WEIGHTED", "0.0"))
        allow_no_eval = os.getenv("DOCARO_MODEL_ALLOW_NO_EVAL", "1") == "1"

        has_eval = bool(metrics)
        accuracy_ok = float(metrics.get("accuracy", 0.0)) >= min_accuracy if has_eval else allow_no_eval
        f1_ok = float(metrics.get("f1_weighted", 0.0)) >= min_f1_weighted if has_eval else allow_no_eval
        if not (accuracy_ok and f1_ok):
            _LOGGER.warning(
                "Promotion abgelehnt (%s): accuracy_ok=%s f1_ok=%s metrics=%s",
                model_name,
                accuracy_ok,
                f1_ok,
                metrics,
            )
            return False

        meta = self._load_production_meta()
        models = meta.setdefault("models", {})
        models[model_name] = {
            "path": str(model_path),
            "promoted_at": datetime.now().isoformat(timespec="seconds"),
            "metrics": metrics,
        }
        self._save_production_meta(meta)
        _LOGGER.info("Model promoted to production: %s -> %s", model_name, model_path)
        return True

    def run_training_job(self):
        """Führt kompletten Training-Job aus."""
        _LOGGER.info("=== Starte Retrain-Job ===")

        if not self.should_train():
            _LOGGER.info("Kein Training nötig")
            return

        training_data = self.collect_training_data()

        # Trainiere Modelle
        if training_data["supplier"]:
            supplier_out = self.train_supplier_model(training_data["supplier"])
            if supplier_out:
                supplier_model_path, supplier_metrics = supplier_out
                self._maybe_promote_model("supplier", supplier_model_path, supplier_metrics)

        # Doctype-Retraining (jetzt implementiert)
        if training_data["doctype"]:
            doctype_out = self.train_text_classifier_model(
                model_name="doctype",
                training_data=training_data["doctype"],
                min_samples=10,
            )
            if doctype_out:
                doctype_model_path, doctype_metrics = doctype_out
                self._maybe_promote_model("doctype", doctype_model_path, doctype_metrics)

        # Date-Retraining bleibt bewusst separat:
        # Vollständige ISO-Daten als Klassenlabels erzeugen meist zu hohe Klassen-Kardinalität
        # und schlechte Generalisierung. Hier empfiehlt sich ein gezieltes Sequence/Rule-Hybrid-
        # Setup statt einer naiven Klassifikation.
        if training_data["date"]:
            _LOGGER.info(
                "Date-Trainingsdaten vorhanden (%s Samples), Date-Retraining aktuell noch nicht aktiviert.",
                len(training_data["date"]),
            )

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
