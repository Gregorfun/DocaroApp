# 🚀 Docaro Modern Pipeline - Architektur & Integration

## 📋 Übersicht

Diese Dokumentation beschreibt die moderne, robuste Docaro-Pipeline auf Basis von Open-Source-Tools für lokale, offline-fähige Dokumentenverarbeitung.

## 🏗️ Pipeline-Architektur

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PDF-DOKUMENT EINGANG                         │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SCHRITT 1: QUALITÄTSPRÜFUNG & PRE-PROCESSING                       │
│  ├─ PDF-Analyse (pdfplumber, PyPDF2)                                │
│  ├─ Qualitätsbewertung (Text-Coverage, Bildqualität)                │
│  └─ Routing-Entscheidung: Native PDF vs. Scan-PDF                   │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
         ┌────────────┴────────────┐
         │                         │
         ▼                         ▼
┌────────────────────┐    ┌──────────────────────┐
│  NATIVE PDF        │    │  GESCANNTE PDF       │
│  (hat Text-Layer)  │    │  (nur Bilder)        │
└─────────┬──────────┘    └──────────┬───────────┘
          │                          │
          │                          ▼
          │               ┌─────────────────────────────────────┐
          │               │  SCHRITT 2: OCR-PROCESSING          │
          │               │  ├─ OCRmyPDF (Searchable PDF)       │
          │               │  ├─ PaddleOCR (Text-Extraktion)     │
          │               │  └─ EasyOCR (Fallback, optional)    │
          │               └─────────────┬───────────────────────┘
          │                             │
          └─────────────────┬───────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SCHRITT 3: DOCLING DOCUMENT PROCESSING                             │
│  ├─ Docling: PDF → DoclingDocument (Layout-Analyse)                 │
│  ├─ Docling-Core: Strukturierte Repräsentation                      │
│  │   ├─ Tabellen-Extraktion                                         │
│  │   ├─ Layout-Elemente (Header, Footer, Sections)                  │
│  │   └─ Text-Chunking (HybridChunker)                               │
│  └─ Docling-Serve: API-Service für parallele Verarbeitung (opt)     │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SCHRITT 4: ML-BASIERTE ANALYSE & KLASSIFIKATION                    │
│  ├─ Dokumenttyp-Klassifikation (Rechnung, Lieferschein, etc.)       │
│  ├─ Lieferanten-Erkennung & -Klassifikation (ML-Model)              │
│  ├─ Datums-Extraktion (ML + Regex-Patterns)                         │
│  └─ MLflow: Modell-Tracking & Versionierung                         │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SCHRITT 5: SEMANTISCHE ANALYSE (OPTIONAL)                          │
│  ├─ Embedding-Generierung (Sentence Transformers)                   │
│  ├─ Vektordatenbank-Speicherung (Qdrant/Chroma)                     │
│  └─ Semantische Suche & Ähnlichkeitsvergleiche                      │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SCHRITT 6: HUMAN-IN-THE-LOOP (bei Unsicherheit)                    │
│  ├─ Konfidenz-Schwellenwerte prüfen                                 │
│  ├─ Label Studio: Korrektur & Trainingsdaten-Sammlung               │
│  └─ Quarantäne-Ordner für manuelle Review                           │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SCHRITT 7: FINALISIERUNG & SPEICHERUNG                             │
│  ├─ Dateiumbenennung (Lieferant_Datum_OriginalName)                 │
│  ├─ Verschiebung in fertig/                                         │
│  ├─ Metadaten-Logging (JSON, CSV)                                   │
│  └─ History-Tracking                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

## 🧩 Tool-Integrationen

### 1. 📄 **Docling-Suite** (Dokument-Parsing & Layout)

#### **Docling**
- **Nutzen**: Konvertiert PDFs in strukturierte DoclingDocuments mit Layout-Analyse
- **Features**: Tabellen-Erkennung, Textfluss-Analyse, Section-Detection
- **Integration**: `pipelines/document_processor.py`

#### **Docling-Core**
- **Nutzen**: Strukturierte Datentypen (DoclingDocument) + Chunking
- **Features**: HybridChunker für Text-Segmentierung, Serialization (JSON, Markdown)
- **Integration**: `pipelines/document_processor.py`

#### **Docling-Serve**
- **Nutzen**: Docling als REST-API für Microservice-Architektur
- **Features**: Asynchrone Verarbeitung, Skalierbarkeit
- **Integration**: `services/docling_service.py` (optional)

#### **Docling-Agent**
- **Nutzen**: Automatisierte Workflows & Task-Scheduling
- **Features**: Ordner-Überwachung, Batch-Processing
- **Integration**: `pipelines/agent_orchestrator.py` (optional)

---

### 2. 🔍 **OCR-Stack** (für gescannte PDFs)

#### **OCRmyPDF**
- **Nutzen**: Macht gescannte PDFs durchsuchbar (fügt Text-Layer hinzu)
- **Features**: Integriert Tesseract, Optimierung, Deskewing
- **Integration**: `pipelines/ocr_processor.py`
- **Offline**: ✅ Vollständig lokal

#### **PaddleOCR**
- **Nutzen**: Hochpräzise OCR für 100+ Sprachen, auch schwierige Handschrift
- **Features**: Rotation-Korrektur, Multi-Language, GPU-Support
- **Integration**: `pipelines/ocr_processor.py`
- **Offline**: ✅ Modelle lokal downloadbar

#### **EasyOCR** (optional)
- **Nutzen**: Leichtgewichtige OCR-Alternative
- **Features**: Einfache API, 80+ Sprachen
- **Integration**: `pipelines/ocr_processor.py` (Fallback)
- **Offline**: ✅ Vollständig lokal

---

### 3. 🔎 **Semantische Suche** (optional, empfohlen)

#### **Qdrant**
- **Nutzen**: Vektordatenbank für semantische Dokumentensuche
- **Features**: High-Performance, Filter-Support, Clustering
- **Integration**: `services/vector_service.py`
- **Setup**: Docker-Container (lokal) oder Python-Client
- **Offline**: ✅ Self-hosted

#### **Chroma**
- **Nutzen**: Lightweight Embedding-Datenbank
- **Features**: In-Memory oder persistent, einfache API
- **Integration**: `services/vector_service.py`
- **Offline**: ✅ Vollständig lokal

**Anwendungsfälle**:
- "Finde alle Rechnungen von Lieferant X mit Betrag > 1000€"
- "Zeige ähnliche Dokumente zu diesem Lieferschein"
- Duplikaterkennung via Cosine-Similarity

---

### 4. 🤖 **ML-Lifecycle** (Training & Tracking)

#### **Label Studio**
- **Nutzen**: Annotationstool für Trainingsdaten
- **Features**: Web-UI für Labeling, Export zu ML-Formaten
- **Integration**: `ml/training/label_studio_integration.py`
- **Setup**: Docker-Container (lokal)
- **Workflow**:
  1. Quarantäne-Dokumente → Label Studio
  2. Manuelles Labeling (Lieferant, Datum, Dokumenttyp)
  3. Export → Training-Pipeline

#### **MLflow**
- **Nutzen**: Experiment-Tracking, Modell-Registry, Versionierung
- **Features**: Parameter-Logging, Metriken, Artefakte, Model-Serving
- **Integration**: `ml/training/mlflow_tracker.py`
- **Setup**: Lokaler MLflow-Server
- **Workflow**:
  1. Trainiere Modelle (Lieferanten-Klassifikation, Datumserkennung)
  2. Logge Metriken (Accuracy, F1-Score)
  3. Registriere beste Modelle
  4. Deploy in Produktions-Pipeline

---

## 🗂️ Ordnerstruktur

```
Docaro/
├── pipelines/                    # 🔄 Haupt-Pipeline-Module
│   ├── __init__.py
│   ├── document_pipeline.py      # Haupt-Orchestrator
│   ├── ocr_processor.py          # OCR-Logik (OCRmyPDF, Paddle, Easy)
│   ├── document_processor.py     # Docling + Docling-Core Integration
│   ├── ml_analyzer.py            # ML-Klassifikation & Extraktion
│   ├── quality_checker.py        # PDF-Qualitätsprüfung
│   ├── agent_orchestrator.py     # Docling-Agent Integration (optional)
│   └── tests/
│       ├── test_ocr_processor.py
│       ├── test_document_processor.py
│       └── test_ml_analyzer.py
│
├── ml/                           # 🤖 Machine Learning Komponenten
│   ├── __init__.py
│   ├── models/                   # Trainierte Modelle
│   │   ├── supplier_classifier/
│   │   ├── date_extractor/
│   │   └── doctype_classifier/
│   ├── training/                 # Training-Scripts
│   │   ├── train_supplier_classifier.py
│   │   ├── train_date_extractor.py
│   │   ├── train_doctype_classifier.py
│   │   ├── mlflow_tracker.py
│   │   └── label_studio_integration.py
│   ├── inference/                # Inference-Wrapper
│   │   ├── supplier_predictor.py
│   │   ├── date_predictor.py
│   │   └── doctype_predictor.py
│   └── data/                     # Trainingsdaten
│       ├── labeled/
│       ├── unlabeled/
│       └── validation/
│
├── services/                     # 🛠️ Externe Services & APIs
│   ├── __init__.py
│   ├── docling_service.py        # Docling-Serve Client
│   ├── vector_service.py         # Qdrant/Chroma Integration
│   ├── ocr_service.py            # OCR-Service-Wrapper
│   └── mlflow_service.py         # MLflow-Client
│
├── config/                       # ⚙️ Konfiguration
│   ├── __init__.py
│   ├── pipeline_config.py        # Pipeline-Settings
│   ├── ml_config.py              # ML-Hyperparameter
│   └── service_config.py         # Service-Endpoints
│
├── monitoring/                   # 📊 Monitoring & Logging
│   ├── __init__.py
│   ├── pipeline_logger.py
│   ├── metrics_tracker.py
│   └── alerts.py
│
├── docker/                       # 🐳 Docker-Setups
│   ├── docker-compose.yml        # Qdrant, Label Studio, MLflow
│   ├── qdrant/
│   ├── label-studio/
│   └── mlflow/
│
├── requirements-pipeline.txt     # Pipeline-Dependencies
├── requirements-ml.txt           # ML-Dependencies (bereits vorhanden)
└── PIPELINE.md                   # Diese Dokumentation
```

---

## 🚦 ML-Pipeline: Lieferanten-Klassifikation

### **Problem**: Lieferantennamen variieren stark (OCR-Fehler, Formatierung)

### **Lösung**: ML-Klassifikator mit Feature-Engineering

```python
# ml/training/train_supplier_classifier.py

from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
import mlflow

# Features:
# - TF-IDF von Text
# - Fuzzy-Match-Score zu bekannten Lieferanten
# - Position im Dokument
# - Regex-Patterns (z.B. "GmbH", "AG")

X_train = extract_features(training_docs)
y_train = [doc.supplier_label for doc in training_docs]

with mlflow.start_run(run_name="supplier_classifier_v1"):
    model = RandomForestClassifier(n_estimators=200)
    model.fit(X_train, y_train)
    
    mlflow.log_params(model.get_params())
    mlflow.log_metric("accuracy", accuracy)
    mlflow.sklearn.log_model(model, "model")
```

---

## 🗓️ ML-Pipeline: Datumserkennung

### **Problem**: Verschiedene Datumsformate, OCR-Fehler (0→O, 1→I)

### **Lösung**: Hybrid-Ansatz (Regex + ML)

```python
# ml/inference/date_predictor.py

def extract_date_ml(text: str, docling_doc: DoclingDocument) -> Dict:
    # 1. Regex-Kandidaten finden
    candidates = find_date_candidates(text)
    
    # 2. ML-Features für jeden Kandidaten
    features = [
        extract_date_features(c, docling_doc)  # Position, Kontext, Format
        for c in candidates
    ]
    
    # 3. ML-Modell rankt Kandidaten
    scores = date_model.predict_proba(features)
    
    best_idx = np.argmax(scores[:, 1])  # Klasse "korrektes Datum"
    
    return {
        "date": candidates[best_idx],
        "confidence": scores[best_idx, 1]
    }
```

---

## 📑 ML-Pipeline: Dokumenttyp-Klassifikation

### **Typen**: Rechnung, Lieferschein, Bestellung, Gutschrift, Sonstige

### **Ansatz**: Text-Klassifikation + Layout-Features

```python
# ml/training/train_doctype_classifier.py

from transformers import AutoModelForSequenceClassification

# Fine-tune German BERT für Dokumentklassifikation
model = AutoModelForSequenceClassification.from_pretrained(
    "deepset/gbert-base",
    num_labels=5  # 5 Dokumenttypen
)

# Features:
# - BERT-Embeddings vom Text
# - Layout-Features von Docling (Tabellenanzahl, Sections)
# - Keywords (Schlüsselwörter wie "Rechnung", "Lieferschein")

# Training mit MLflow-Tracking
with mlflow.start_run():
    trainer.train()
    mlflow.log_metric("f1_score", f1)
```

---

## 🔄 End-to-End Pipeline-Beispiel

```python
# pipelines/document_pipeline.py

from pipelines.quality_checker import assess_pdf_quality
from pipelines.ocr_processor import process_with_ocr
from pipelines.document_processor import extract_with_docling
from pipelines.ml_analyzer import analyze_with_ml
from services.vector_service import store_embeddings

def process_document(pdf_path: Path) -> Dict:
    """Vollständige Pipeline für ein Dokument."""
    
    # Schritt 1: Qualitätsprüfung
    quality = assess_pdf_quality(pdf_path)
    
    # Schritt 2: OCR falls nötig
    if quality.needs_ocr:
        pdf_path = process_with_ocr(
            pdf_path,
            method="ocrmypdf",  # oder "paddleocr"
            confidence_threshold=quality.ocr_confidence
        )
    
    # Schritt 3: Docling-Verarbeitung
    docling_result = extract_with_docling(pdf_path)
    
    # Schritt 4: ML-Analyse
    ml_result = analyze_with_ml(docling_result)
    
    # Schritt 5: Semantische Embeddings (optional)
    if config.USE_VECTOR_DB:
        embedding_id = store_embeddings(
            text=docling_result.text,
            metadata=ml_result
        )
    
    # Schritt 6: Konfidenz-Check → Quarantäne?
    if ml_result.confidence < config.QUARANTINE_THRESHOLD:
        move_to_quarantine(pdf_path, ml_result)
        return {"status": "quarantine", "result": ml_result}
    
    # Schritt 7: Finalisierung
    new_filename = build_filename(ml_result)
    final_path = move_to_output(pdf_path, new_filename)
    
    return {
        "status": "success",
        "path": final_path,
        "result": ml_result
    }
```

---

## 🐳 Docker-Setup (Services)

```yaml
# docker/docker-compose.yml

version: '3.8'

services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - ./qdrant_storage:/qdrant/storage

  label-studio:
    image: heartexlabs/label-studio:latest
    ports:
      - "8080:8080"
    volumes:
      - ./label_studio_data:/label-studio/data

  mlflow:
    image: ghcr.io/mlflow/mlflow:latest
    ports:
      - "5000:5000"
    command: mlflow server --host 0.0.0.0 --backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlruns
    volumes:
      - ./mlflow_data:/mlflow
```

**Start**: `docker-compose -f docker/docker-compose.yml up -d`

---

## 📊 Logging & Monitoring

```python
# monitoring/pipeline_logger.py

import structlog
from pathlib import Path

logger = structlog.get_logger()

def log_pipeline_step(step: str, pdf_path: Path, **kwargs):
    logger.info(
        "pipeline_step",
        step=step,
        pdf=pdf_path.name,
        **kwargs
    )

# Beispiel:
log_pipeline_step(
    step="ml_analysis",
    pdf_path=pdf_path,
    supplier=result.supplier,
    supplier_confidence=result.supplier_confidence,
    date=result.date,
    date_confidence=result.date_confidence
)
```

**Structured Logging** ermöglicht einfaches Filtern und Dashboards.

---

## 🧪 Testing-Strategie

```python
# pipelines/tests/test_document_pipeline.py

import pytest
from pipelines.document_pipeline import process_document

@pytest.fixture
def sample_pdf():
    return Path("test_data/sample_invoice.pdf")

def test_pipeline_native_pdf(sample_pdf):
    """Test Pipeline mit nativem PDF (ohne OCR)."""
    result = process_document(sample_pdf)
    
    assert result["status"] == "success"
    assert result["result"]["supplier"] == "Testlieferant GmbH"
    assert result["result"]["date"] == "2026-01-15"

def test_pipeline_scanned_pdf(scanned_pdf):
    """Test Pipeline mit gescanntem PDF (mit OCR)."""
    result = process_document(scanned_pdf)
    
    assert result["status"] in ["success", "quarantine"]
    assert "ocr_method" in result["result"]
```

---

## 🔮 Spätere Erweiterungen

### **1. Multi-Dokument-Verarbeitung**
- **Batch-Processing** mit Docling-Agent
- **Parallelverarbeitung** via Docling-Serve API
- **Priorisierung** nach Dokumenttyp/Wichtigkeit

### **2. Erweiterte KI-Features**
- **LLM-Integration** (z.B. Ollama lokal) für komplexe Extraktion
- **Zero-Shot-Klassifikation** für neue Dokumenttypen
- **Automatic Summarization** von Dokumenten

### **3. Advanced ML**
- **Active Learning**: Modell schlägt unsichere Fälle für Labeling vor
- **Continual Learning**: Modell lernt aus Korrekturen weiter
- **Ensemble-Modelle**: Kombination mehrerer OCR/ML-Ansätze

### **4. Workflow-Automatisierung**
- **Docling-Agent**: Überwacht Ordner, triggert Pipeline automatisch
- **Webhooks**: Benachrichtigungen bei Quarantäne-Fällen
- **API-Integration**: REST-API für externe Systeme

### **5. Erweiterte Semantische Suche**
- **Hybrid-Search**: Kombination aus Keyword + Vektor-Suche
- **Graph-Datenbank** (Neo4j): Beziehungen zwischen Lieferanten/Dokumenten
- **Anomalie-Detektion**: Ungewöhnliche Beträge/Muster erkennen

---

## 🎯 Zusammenfassung

Die moderne Docaro-Pipeline bietet:

✅ **Robustheit**: Multi-Layer OCR-Fallbacks (Tesseract → Paddle → Easy)  
✅ **Intelligenz**: ML-Modelle für Klassifikation + Extraktion  
✅ **Skalierbarkeit**: Microservices (Docling-Serve, Qdrant)  
✅ **Lernfähigkeit**: Label Studio + MLflow für kontinuierliche Verbesserung  
✅ **Offline-First**: Alle Tools lokal lauffähig, keine Cloud-Abhängigkeit  
✅ **Erweiterbar**: Modulare Architektur für neue Features  

**Nächste Schritte**: Siehe [INTEGRATION_ROADMAP.md](INTEGRATION_ROADMAP.md)
