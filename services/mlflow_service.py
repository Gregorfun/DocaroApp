"""
MLflow-Integration für Modell-Tracking und Experiment-Management.

Funktionen:
- Training-Runs loggen
- Modelle registrieren & versionieren
- Metriken & Parameter tracken
- Modelle aus Registry laden
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

_LOGGER = logging.getLogger(__name__)


class MLflowService:
    """
    Service für MLflow-Integration.
    
    **Setup**:
    ```bash
    # Starte MLflow UI lokal
    mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5000
    ```
    
    **Nutzen**:
    - Experiment-Tracking: Vergleiche Training-Runs
    - Model Registry: Versioniere und deploye Modelle
    - Artifact Storage: Speichere Trainingsartefakte
    - Reproducibility: Nachvollziehbare Experimente
    """
    
    def __init__(
        self,
        tracking_uri: str = None,
        experiment_name: str = "docaro_ml"
    ):
        """
        Args:
            tracking_uri: MLflow Tracking Server URI (default: lokal)
            experiment_name: Name des Experiments
        """
        self.tracking_uri = tracking_uri or "sqlite:///mlflow.db"
        self.experiment_name = experiment_name
        
        self._mlflow = None
    
    def _get_mlflow(self):
        """Lazy-Loading von MLflow."""
        if self._mlflow is not None:
            return self._mlflow
        
        try:
            import mlflow
        except ImportError:
            raise ImportError(
                "MLflow ist nicht installiert. "
                "Installiere mit: pip install mlflow"
            )
        
        # Konfiguriere MLflow
        mlflow.set_tracking_uri(self.tracking_uri)
        mlflow.set_experiment(self.experiment_name)
        
        self._mlflow = mlflow
        
        _LOGGER.info(f"MLflow konfiguriert: {self.tracking_uri}")
        
        return mlflow
    
    def start_run(self, run_name: str, tags: Optional[Dict] = None):
        """
        Startet einen neuen MLflow Run.
        
        Args:
            run_name: Name des Runs
            tags: Optional tags (z.B. {'model': 'supplier_classifier'})
        
        Returns:
            MLflow Run Context
        
        **Beispiel**:
        ```python
        with mlflow_service.start_run("train_supplier_v1") as run:
            # Training code
            mlflow.log_param("n_estimators", 200)
            mlflow.log_metric("accuracy", 0.92)
        ```
        """
        mlflow = self._get_mlflow()
        
        return mlflow.start_run(run_name=run_name, tags=tags or {})
    
    def log_params(self, params: Dict[str, Any]):
        """Loggt Hyperparameter."""
        mlflow = self._get_mlflow()
        mlflow.log_params(params)
    
    def log_metrics(self, metrics: Dict[str, float], step: Optional[int] = None):
        """
        Loggt Metriken.
        
        Args:
            metrics: Dict mit Metriken (z.B. {'accuracy': 0.92, 'f1': 0.89})
            step: Optional Trainings-Step (für Kurven)
        """
        mlflow = self._get_mlflow()
        
        for key, value in metrics.items():
            mlflow.log_metric(key, value, step=step)
    
    def log_model(
        self,
        model,
        artifact_path: str,
        registered_model_name: Optional[str] = None
    ):
        """
        Loggt und registriert ML-Modell.
        
        Args:
            model: Scikit-learn, PyTorch, TensorFlow, etc. Modell
            artifact_path: Pfad im Artifact-Store
            registered_model_name: Name für Model Registry
        
        **Beispiel**:
        ```python
        mlflow_service.log_model(
            model=trained_classifier,
            artifact_path="model",
            registered_model_name="supplier_classifier"
        )
        ```
        """
        mlflow = self._get_mlflow()
        
        # Auto-detect Modell-Typ
        if hasattr(model, 'fit') and hasattr(model, 'predict'):
            # Scikit-learn
            mlflow.sklearn.log_model(
                model,
                artifact_path,
                registered_model_name=registered_model_name
            )
        else:
            # Generisches Modell (Pickle)
            mlflow.pyfunc.log_model(
                artifact_path,
                python_model=model,
                registered_model_name=registered_model_name
            )
    
    def load_model(
        self,
        model_name: str,
        version: Optional[str] = "latest"
    ):
        """
        Lädt Modell aus Registry.
        
        Args:
            model_name: Registrierter Modellname
            version: Modell-Version ("1", "2", "latest", "production")
        
        Returns:
            Geladenes Modell
        
        **Beispiel**:
        ```python
        model = mlflow_service.load_model("supplier_classifier", version="production")
        predictions = model.predict(X_test)
        ```
        """
        mlflow = self._get_mlflow()
        
        if version == "latest":
            model_uri = f"models:/{model_name}/latest"
        elif version == "production":
            model_uri = f"models:/{model_name}/Production"
        else:
            model_uri = f"models:/{model_name}/{version}"
        
        _LOGGER.info(f"Lade Modell: {model_uri}")
        
        return mlflow.pyfunc.load_model(model_uri)
    
    def transition_model_stage(
        self,
        model_name: str,
        version: str,
        stage: str
    ):
        """
        Ändert Modell-Stage in Registry.
        
        Args:
            model_name: Modellname
            version: Version (z.B. "1", "2")
            stage: "Staging", "Production", "Archived"
        
        **Beispiel**:
        ```python
        # Promote Model zu Production
        mlflow_service.transition_model_stage(
            "supplier_classifier",
            version="3",
            stage="Production"
        )
        ```
        """
        mlflow = self._get_mlflow()
        client = mlflow.tracking.MlflowClient()
        
        client.transition_model_version_stage(
            name=model_name,
            version=version,
            stage=stage
        )
        
        _LOGGER.info(f"Modell {model_name} v{version} → {stage}")
    
    def log_artifact(self, local_path: Path, artifact_path: Optional[str] = None):
        """
        Loggt Artifact (z.B. Plots, Konfusions-Matrix).
        
        Args:
            local_path: Lokaler Pfad zur Datei
            artifact_path: Pfad im Artifact-Store
        """
        mlflow = self._get_mlflow()
        mlflow.log_artifact(str(local_path), artifact_path)
    
    def search_runs(
        self,
        filter_string: Optional[str] = None,
        order_by: Optional[str] = None,
        max_results: int = 100
    ):
        """
        Sucht nach Runs im Experiment.
        
        Args:
            filter_string: MLflow Filter (z.B. "metrics.accuracy > 0.9")
            order_by: Sortierung (z.B. "metrics.accuracy DESC")
            max_results: Max. Anzahl Ergebnisse
        
        Returns:
            Liste von Runs
        
        **Beispiel**:
        ```python
        # Finde beste Runs
        best_runs = mlflow_service.search_runs(
            filter_string="metrics.f1_score > 0.85",
            order_by="metrics.f1_score DESC",
            max_results=10
        )
        ```
        """
        mlflow = self._get_mlflow()
        
        experiment = mlflow.get_experiment_by_name(self.experiment_name)
        
        runs = mlflow.search_runs(
            experiment_ids=[experiment.experiment_id],
            filter_string=filter_string,
            order_by=order_by or ["start_time DESC"],
            max_results=max_results
        )
        
        return runs


# Training-Beispiel mit MLflow
def train_supplier_classifier_example():
    """
    Beispiel: Lieferanten-Klassifikator mit MLflow-Tracking.
    """
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, f1_score, classification_report
    
    # Initialisiere MLflow
    mlflow_service = MLflowService(experiment_name="supplier_classification")
    
    # Dummy-Daten (ersetze mit echten Trainingsdaten)
    X = np.random.rand(1000, 50)  # 1000 Dokumente, 50 Features
    y = np.random.randint(0, 10, 1000)  # 10 Lieferanten
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
    
    # Hyperparameter
    params = {
        'n_estimators': 200,
        'max_depth': 20,
        'min_samples_split': 5,
        'random_state': 42
    }
    
    # Starte MLflow Run
    with mlflow_service.start_run("supplier_rf_v1", tags={'algorithm': 'random_forest'}):
        # Logge Parameter
        mlflow_service.log_params(params)
        
        # Trainiere Modell
        model = RandomForestClassifier(**params)
        model.fit(X_train, y_train)
        
        # Evaluiere
        y_pred = model.predict(X_test)
        
        accuracy = accuracy_score(y_test, y_pred)
        f1 = f1_score(y_test, y_pred, average='weighted')
        
        # Logge Metriken
        mlflow_service.log_metrics({
            'accuracy': accuracy,
            'f1_score': f1,
            'train_samples': len(X_train),
            'test_samples': len(X_test)
        })
        
        # Logge Modell
        mlflow_service.log_model(
            model,
            artifact_path="model",
            registered_model_name="supplier_classifier"
        )
        
        print(f"✅ Training abgeschlossen:")
        print(f"   Accuracy: {accuracy:.3f}")
        print(f"   F1-Score: {f1:.3f}")
        print(f"   Modell registriert: supplier_classifier")


# Inference-Beispiel
def inference_with_mlflow_example():
    """Beispiel: Lade Modell aus MLflow und mache Predictions."""
    mlflow_service = MLflowService(experiment_name="supplier_classification")
    
    # Lade Production-Modell
    model = mlflow_service.load_model("supplier_classifier", version="production")
    
    # Dummy-Daten
    X_new = np.random.rand(10, 50)
    
    # Predictions
    predictions = model.predict(X_new)
    
    print(f"Predictions: {predictions}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Trainings-Beispiel
    train_supplier_classifier_example()
    
    # Inference-Beispiel
    # inference_with_mlflow_example()
