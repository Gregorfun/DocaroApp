# DOCARO – Integration Roadmap & Architektur

## 🎯 Vision
Docaro wird zu einem robusten, ML-gestützten Dokumenten-Verarbeitungssystem mit modularer Pipeline-Architektur, das offline und lokal läuft.

---

## 📊 System-Architektur

```
┌─────────────────────────────────────────────────────────────┐
│                    DOCARO PIPELINE                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Input: PDF/Image                                          │
│         ↓                                                   │
│  ┌──────────────────────────────────────┐                 │
│  │  1. PRE-PROCESSING                   │                 │
│  │  - OCRmyPDF (Scans → searchable)    │                 │
│  │  - PaddleOCR (Fallback OCR)         │                 │
│  │  - EasyOCR (Alternative)             │                 │
│  └──────────────────────────────────────┘                 │
│         ↓                                                   │
│  ┌──────────────────────────────────────┐                 │
│  │  2. DOCUMENT PARSING                 │                 │
│  │  - Docling (Layout + Struktur)      │                 │
│  │  - Docling-Core (Chunking)          │                 │
│  │  - Tabellen-Extraktion              │                 │
│  └──────────────────────────────────────┘                 │
│         ↓                                                   │
│  ┌──────────────────────────────────────┐                 │
│  │  3. INFORMATION EXTRACTION           │                 │
│  │  - Datum (Regex + ML)               │                 │
│  │  - Lieferant (DB + ML-Klassifikator)│                 │
│  │  - Dokumenttyp (ML)                 │                 │
│  └──────────────────────────────────────┘                 │
│         ↓                                                   │
│  ┌──────────────────────────────────────┐                 │
│  │  4. SEMANTIC INDEXING (Optional)     │                 │
│  │  - Embeddings generieren            │                 │
│  │  - Qdrant/Chroma speichern          │                 │
│  └──────────────────────────────────────┘                 │
│         ↓                                                   │
│  ┌──────────────────────────────────────┐                 │
│  │  5. ML INFERENCE                     │                 │
│  │  - Supplier Classifier              │                 │
│  │  - Date Extractor                   │                 │
│  │  - Document Type Classifier         │                 │
│  │  - Confidence Scorer                │                 │
│  └──────────────────────────────────────┘                 │
│         ↓                                                   │
│  ┌──────────────────────────────────────┐                 │
│  │  6. POST-PROCESSING                  │                 │
│  │  - Filename Building                │                 │
│  │  - Quarantine Check                 │                 │
│  │  - Quality Assurance                │                 │
│  └──────────────────────────────────────┘                 │
│         ↓                                                   │
│  Output: Renamed PDF + Metadata                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🧩 Tool-Integration Matrix

| Tool | Zweck | Status | Priorität | Integration |
|------|-------|--------|-----------|-------------|
| **Docling** | PDF Layout-Analyse | ✅ Integriert | Hoch | `core/docling_extractor.py` |
| **Docling-Core** | DoclingDocument, Chunking | ✅ Integriert | Hoch | `core/docling_extractor.py` |
| **Docling-Serve** | API-Service (Optional) | 📋 Geplant | Niedrig | Separater Service |
| **Docling-Agent** | Automation (Optional) | 📋 Geplant | Niedrig | Task-Orchestrierung |
| **PaddleOCR** | OCR Fallback | ⚠️ Optional | Mittel | `core/extractor.py` (bereits vorbereitet) |
| **OCRmyPDF** | Scan → Searchable PDF | 📋 Geplant | Hoch | `core/ocr_preprocessor.py` (neu) |
| **EasyOCR** | Alternative OCR | 📋 Geplant | Niedrig | Fallback zu PaddleOCR |
| **Qdrant** | Vektor-DB für Semantic Search | 📋 Geplant | Mittel | `ml/semantic_search.py` (neu) |
| **Chroma** | Lightweight Vector Store | 📋 Geplant | Mittel | Alternative zu Qdrant |
| **Label Studio** | Training Data Annotation | 📋 Geplant | Hoch | Separater Service |
| **MLflow** | ML Experiment Tracking | ✅ In requirements | Hoch | `ml/training/` (neu) |

---

## 📁 Neue Ordnerstruktur

```
Docaro/
├── app/                          # Flask Web-App
│   ├── app.py
│   ├── static/
│   └── templates/
├── core/                         # Core Processing
│   ├── extractor.py             # Tesseract-basiert (Legacy)
│   ├── docling_extractor.py     # ✅ Docling-basiert (Neu)
│   ├── ocr_preprocessor.py      # 🆕 OCRmyPDF + PaddleOCR
│   ├── pipeline.py              # 🆕 Haupt-Pipeline Orchestrator
│   └── test_*.py
├── ml/                           # 🆕 Machine Learning
│   ├── __init__.py
│   ├── models/                  # Trainierte Modelle
│   │   ├── supplier_classifier.pkl
│   │   ├── date_extractor.pkl
│   │   └── doctype_classifier.pkl
│   ├── training/                # Training Scripts
│   │   ├── train_supplier.py
│   │   ├── train_date.py
│   │   └── train_doctype.py
│   ├── inference/               # Inference Engine
│   │   ├── classifier.py
│   │   └── scorer.py
│   ├── embeddings/              # Semantic Search
│   │   ├── embed_generator.py
│   │   └── vector_store.py
│   └── data/                    # Training Data
│       ├── labeled/
│       └── raw/
├── integrations/                 # 🆕 Tool Integrations
│   ├── docling_serve.py         # Docling-Serve Client
│   ├── qdrant_client.py         # Qdrant Integration
│   ├── chroma_client.py         # Chroma Integration
│   └── label_studio_sync.py     # Label Studio Sync
├── data/
│   ├── eingang/
│   ├── fertig/
│   ├── quarantaene/             # Unsichere Ergebnisse
│   ├── suppliers.json
│   ├── supplier_corrections.json
│   └── logs/
├── config/                       # 🆕 Konfiguration
│   ├── pipeline_config.yaml
│   ├── ml_config.yaml
│   └── ocr_config.yaml
├── tests/                        # 🆕 Strukturierte Tests
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── docker/                       # 🆕 Container Setup
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── services/                # Qdrant, Label Studio etc.
├── requirements.txt
├── requirements-ml.txt           # 🆕 ML-spezifische Deps
├── requirements-dev.txt
└── INTEGRATION_ROADMAP.md        # Dieses Dokument
```

---

## 🔧 Phase 1: OCR Pre-Processing (Woche 1-2)

### 1.1 OCRmyPDF Integration

**Nutzen**: Macht gescannte PDFs durchsuchbar, verbessert Docling-Qualität.

**Installation (Linux)**:
```bash
sudo apt-get install ocrmypdf tesseract-ocr-deu
pip install ocrmypdf
```

**Implementation**: `core/ocr_preprocessor.py`

```python
import logging
from pathlib import Path
from typing import Optional
import ocrmypdf

logger = logging.getLogger(__name__)

class OCRPreprocessor:
    """Pre-Processing für gescannte PDFs."""
    
    def __init__(self, language='deu', dpi=300):
        self.language = language
        self.dpi = dpi
    
    def process(self, input_pdf: Path, output_pdf: Optional[Path] = None) -> Path:
        """
        Macht PDF durchsuchbar.
        
        Args:
            input_pdf: Original PDF
            output_pdf: Ziel (oder Temp)
            
        Returns:
            Path zum verarbeiteten PDF
        """
        if output_pdf is None:
            output_pdf = input_pdf.parent / f"{input_pdf.stem}_ocr.pdf"
        
        try:
            ocrmypdf.ocr(
                input_file=str(input_pdf),
                output_file=str(output_pdf),
                language=self.language,
                deskew=True,
                rotate_pages=True,
                remove_background=False,
                optimize=1,
                skip_text=True,  # Nur fehlenden Text OCRen
                redo_ocr=False,
                force_ocr=False,
                tesseract_timeout=180
            )
            logger.info(f"OCRmyPDF erfolgreich: {output_pdf}")
            return output_pdf
        except ocrmypdf.exceptions.PriorOcrFoundError:
            # PDF hat bereits Text
            logger.info(f"PDF bereits durchsuchbar: {input_pdf}")
            return input_pdf
        except Exception as e:
            logger.error(f"OCRmyPDF Fehler: {e}")
            return input_pdf  # Fallback auf Original
```

### 1.2 PaddleOCR Integration (erweitert)

**Implementation**: Erweitere `core/extractor.py`

```python
def ocr_with_paddle_advanced(image_path: Path) -> str:
    """Erweiterte PaddleOCR mit Pre-Processing."""
    ocr = _get_paddle_ocr()
    if not ocr:
        return ""
    
    # Bild vorverarbeiten
    img = Image.open(image_path)
    
    # Kontrast erhöhen
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.5)
    
    # Schärfen
    img = img.filter(ImageFilter.SHARPEN)
    
    # OCR durchführen
    result = ocr.ocr(np.array(img), cls=True)
    
    # Text extrahieren
    text_lines = []
    for line in result[0]:
        text_lines.append(line[1][0])
    
    return '\n'.join(text_lines)
```

---

## 🤖 Phase 2: ML-Pipeline Aufbau (Woche 3-6)

### 2.1 Ordnerstruktur für ML

```bash
mkdir -p ml/{models,training,inference,embeddings,data/{labeled,raw}}
```

### 2.2 Supplier Classifier

**File**: `ml/training/train_supplier.py`

```python
import joblib
import pandas as pd
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import mlflow
import mlflow.sklearn

class SupplierClassifier:
    """Lieferanten-Klassifikator."""
    
    def __init__(self, model_path: Path = None):
        self.vectorizer = TfidfVectorizer(max_features=5000)
        self.classifier = LogisticRegression(max_iter=1000)
        self.model_path = model_path or Path("ml/models/supplier_classifier.pkl")
    
    def train(self, texts: list, labels: list):
        """
        Trainiert Klassifikator.
        
        Args:
            texts: Liste von Dokumententexten
            labels: Liste von Lieferanten-Labels
        """
        mlflow.start_run()
        
        # Train/Test Split
        X_train, X_test, y_train, y_test = train_test_split(
            texts, labels, test_size=0.2, random_state=42
        )
        
        # Vektorisierung
        X_train_vec = self.vectorizer.fit_transform(X_train)
        X_test_vec = self.vectorizer.transform(X_test)
        
        # Training
        self.classifier.fit(X_train_vec, y_train)
        
        # Evaluation
        y_pred = self.classifier.predict(X_test_vec)
        report = classification_report(y_test, y_pred, output_dict=True)
        
        # MLflow Logging
        mlflow.log_param("max_features", 5000)
        mlflow.log_param("n_samples", len(texts))
        mlflow.log_metric("accuracy", report['accuracy'])
        mlflow.sklearn.log_model(self.classifier, "model")
        
        # Speichern
        self.save()
        
        mlflow.end_run()
        
        return report
    
    def predict(self, text: str) -> tuple[str, float]:
        """
        Klassifiziert Dokument.
        
        Returns:
            (lieferant, confidence)
        """
        X = self.vectorizer.transform([text])
        proba = self.classifier.predict_proba(X)[0]
        best_idx = proba.argmax()
        
        return (
            self.classifier.classes_[best_idx],
            float(proba[best_idx])
        )
    
    def save(self):
        """Speichert Modell."""
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            'vectorizer': self.vectorizer,
            'classifier': self.classifier
        }, self.model_path)
    
    def load(self):
        """Lädt Modell."""
        if self.model_path.exists():
            data = joblib.load(self.model_path)
            self.vectorizer = data['vectorizer']
            self.classifier = data['classifier']
            return True
        return False
```

### 2.3 Date Extractor (ML-basiert)

**File**: `ml/training/train_date.py`

```python
import re
from datetime import datetime
from typing import Optional
from sklearn.ensemble import RandomForestClassifier
import numpy as np

class MLDateExtractor:
    """ML-gestützter Datumsextraktor."""
    
    def __init__(self):
        self.date_patterns = [
            r'\d{2}\.\d{2}\.\d{4}',
            r'\d{4}-\d{2}-\d{2}',
            r'\d{2}/\d{2}/\d{4}',
        ]
        self.classifier = RandomForestClassifier(n_estimators=100)
    
    def extract_date_candidates(self, text: str) -> list:
        """Findet alle Datumskanditaten."""
        candidates = []
        
        for pattern in self.date_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                candidates.append({
                    'text': match.group(),
                    'position': match.start(),
                    'pattern': pattern
                })
        
        return candidates
    
    def score_candidate(self, candidate: dict, context: str) -> float:
        """
        Bewertet Datumskandidat.
        
        Features:
        - Position im Dokument (oben = besser)
        - Kontext-Keywords (Datum, Lieferdatum, etc.)
        - Format-Validität
        """
        score = 0.0
        
        # Position (normalisiert)
        pos_score = 1.0 - (candidate['position'] / len(context))
        score += pos_score * 0.4
        
        # Kontext
        context_window = context[
            max(0, candidate['position']-50):
            candidate['position']+50
        ]
        keywords = ['datum', 'lieferdatum', 'rechnungsdatum', 'date']
        if any(kw in context_window.lower() for kw in keywords):
            score += 0.6
        
        return score
    
    def extract(self, text: str) -> Optional[datetime]:
        """Extrahiert bestes Datum."""
        candidates = self.extract_date_candidates(text)
        
        if not candidates:
            return None
        
        # Score alle Kandidaten
        scored = [
            (c, self.score_candidate(c, text))
            for c in candidates
        ]
        
        # Bester Kandidat
        best = max(scored, key=lambda x: x[1])
        
        # Parse
        try:
            date_str = best[0]['text']
            # Verschiedene Formate probieren
            for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y']:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
        except Exception:
            pass
        
        return None
```

### 2.4 Document Type Classifier

**File**: `ml/training/train_doctype.py`

```python
from enum import Enum

class DocumentType(Enum):
    LIEFERSCHEIN = "lieferschein"
    RECHNUNG = "rechnung"
    GUTSCHRIFT = "gutschrift"
    AUFTRAG = "auftrag"
    UNKNOWN = "unknown"

class DocumentTypeClassifier:
    """Klassifiziert Dokumenttyp."""
    
    def __init__(self):
        self.keywords = {
            DocumentType.LIEFERSCHEIN: [
                'lieferschein', 'delivery note', 'packzettel'
            ],
            DocumentType.RECHNUNG: [
                'rechnung', 'invoice', 'rechnungsnummer'
            ],
            DocumentType.GUTSCHRIFT: [
                'gutschrift', 'credit note', 'storno'
            ],
            DocumentType.AUFTRAG: [
                'auftrag', 'order', 'bestellung'
            ]
        }
    
    def classify(self, text: str) -> tuple[DocumentType, float]:
        """
        Klassifiziert Dokument.
        
        Returns:
            (typ, confidence)
        """
        text_lower = text.lower()
        
        scores = {}
        for doc_type, keywords in self.keywords.items():
            score = sum(
                text_lower.count(kw) for kw in keywords
            )
            scores[doc_type] = score
        
        if not any(scores.values()):
            return (DocumentType.UNKNOWN, 0.0)
        
        best_type = max(scores, key=scores.get)
        max_score = scores[best_type]
        total_score = sum(scores.values())
        
        confidence = max_score / total_score if total_score > 0 else 0.0
        
        return (best_type, confidence)
```

---

## 🔗 Phase 3: Pipeline Integration (Woche 7-8)

### 3.1 Haupt-Pipeline Orchestrator

**File**: `core/pipeline.py`

```python
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import logging

from core.ocr_preprocessor import OCRPreprocessor
from core.docling_extractor import get_extractor
from ml.inference.classifier import SupplierClassifier
from ml.training.train_date import MLDateExtractor
from ml.training.train_doctype import DocumentTypeClassifier

logger = logging.getLogger(__name__)

class DocaroPipeline:
    """Haupt-Verarbeitungs-Pipeline."""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        
        # Components
        self.ocr_preprocessor = OCRPreprocessor()
        self.docling_extractor = get_extractor()
        self.supplier_classifier = SupplierClassifier()
        self.date_extractor = MLDateExtractor()
        self.doctype_classifier = DocumentTypeClassifier()
        
        # Lade ML-Modelle
        self.supplier_classifier.load()
    
    def process(self, pdf_path: Path) -> Dict[str, Any]:
        """
        Verarbeitet PDF durch komplette Pipeline.
        
        Returns:
            {
                'supplier': str,
                'supplier_confidence': float,
                'date': datetime,
                'date_confidence': float,
                'doctype': DocumentType,
                'doctype_confidence': float,
                'text': str,
                'metadata': dict,
                'quarantine': bool
            }
        """
        logger.info(f"Pipeline Start: {pdf_path}")
        result = {}
        
        try:
            # 1. OCR Pre-Processing (wenn nötig)
            processed_pdf = self._preprocess_ocr(pdf_path)
            
            # 2. Docling Extraction
            text, metadata = self._extract_with_docling(processed_pdf)
            result['text'] = text
            result['metadata'] = metadata
            
            # 3. ML Inference
            supplier, supplier_conf = self._classify_supplier(text)
            result['supplier'] = supplier
            result['supplier_confidence'] = supplier_conf
            
            date = self._extract_date(text)
            result['date'] = date
            result['date_confidence'] = 0.9 if date else 0.0  # Simple scoring
            
            doctype, doctype_conf = self._classify_doctype(text)
            result['doctype'] = doctype
            result['doctype_confidence'] = doctype_conf
            
            # 4. Quality Check
            result['quarantine'] = self._should_quarantine(result)
            
            logger.info(f"Pipeline Erfolg: {pdf_path} -> {supplier}")
            
        except Exception as e:
            logger.error(f"Pipeline Fehler: {e}")
            result['error'] = str(e)
            result['quarantine'] = True
        
        return result
    
    def _preprocess_ocr(self, pdf_path: Path) -> Path:
        """OCR Pre-Processing wenn nötig."""
        if self.config.get('force_ocr', False):
            return self.ocr_preprocessor.process(pdf_path)
        return pdf_path
    
    def _extract_with_docling(self, pdf_path: Path) -> tuple[str, dict]:
        """Docling Extraction."""
        text = self.docling_extractor.extract_text(pdf_path)
        metadata = self.docling_extractor.extract_metadata(pdf_path)
        return text, metadata
    
    def _classify_supplier(self, text: str) -> tuple[str, float]:
        """Lieferant klassifizieren."""
        try:
            return self.supplier_classifier.predict(text)
        except Exception as e:
            logger.warning(f"Supplier ML failed: {e}")
            return ("Unknown", 0.0)
    
    def _extract_date(self, text: str) -> Optional[datetime]:
        """Datum extrahieren."""
        return self.date_extractor.extract(text)
    
    def _classify_doctype(self, text: str) -> tuple:
        """Dokumenttyp klassifizieren."""
        return self.doctype_classifier.classify(text)
    
    def _should_quarantine(self, result: dict) -> bool:
        """Prüft ob Dokument in Quarantäne muss."""
        return (
            result['supplier_confidence'] < 0.7 or
            result.get('date') is None or
            result['doctype_confidence'] < 0.5
        )
```

---

## 📊 Phase 4: Semantic Search (Optional, Woche 9-10)

### 4.1 Qdrant Integration

**File**: `integrations/qdrant_client.py`

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
from pathlib import Path
from typing import List, Dict, Any

class DocaroVectorStore:
    """Semantic Search mit Qdrant."""
    
    def __init__(self, collection_name: str = "docaro_documents"):
        self.client = QdrantClient(path="./data/qdrant")
        self.collection_name = collection_name
        self.encoder = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        
        self._init_collection()
    
    def _init_collection(self):
        """Erstellt Collection wenn nicht vorhanden."""
        try:
            self.client.get_collection(self.collection_name)
        except:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=384,  # MiniLM embedding size
                    distance=Distance.COSINE
                )
            )
    
    def index_document(self, doc_id: str, text: str, metadata: dict):
        """Indexiert Dokument."""
        # Generiere Embedding
        embedding = self.encoder.encode(text).tolist()
        
        # Speichere in Qdrant
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=doc_id,
                    vector=embedding,
                    payload={
                        'text': text[:1000],  # Gekürzt
                        **metadata
                    }
                )
            ]
        )
    
    def search_similar(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Sucht ähnliche Dokumente."""
        query_vector = self.encoder.encode(query).tolist()
        
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit
        )
        
        return [
            {
                'id': hit.id,
                'score': hit.score,
                'metadata': hit.payload
            }
            for hit in results
        ]
```

---

## 🧪 Phase 5: Testing & CI/CD (Woche 11-12)

### 5.1 Test-Struktur

**File**: `tests/integration/test_pipeline.py`

```python
import pytest
from pathlib import Path
from core.pipeline import DocaroPipeline

@pytest.fixture
def pipeline():
    return DocaroPipeline()

@pytest.fixture
def sample_pdf():
    return Path("tests/fixtures/sample_lieferschein.pdf")

def test_pipeline_end_to_end(pipeline, sample_pdf):
    """Test komplette Pipeline."""
    result = pipeline.process(sample_pdf)
    
    assert 'supplier' in result
    assert 'date' in result
    assert 'doctype' in result
    assert result['supplier_confidence'] > 0.0

def test_pipeline_with_scan(pipeline):
    """Test mit gescanntem PDF."""
    scan_pdf = Path("tests/fixtures/scanned_invoice.pdf")
    result = pipeline.process(scan_pdf)
    
    assert result['text']  # Text wurde extrahiert
    assert not result.get('error')
```

---

## 📦 Phase 6: Deployment (Woche 13-14)

### 6.1 Docker Setup

**File**: `docker/docker-compose.yml`

```yaml
version: '3.8'

services:
  docaro-app:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    ports:
      - "5001:5001"
    volumes:
      - ../data:/app/data
      - ../ml/models:/app/ml/models
    environment:
      - FLASK_APP=app.app
      - DOCARO_USE_PADDLEOCR=0
    depends_on:
      - qdrant
      - mlflow
  
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage
  
  mlflow:
    image: ghcr.io/mlflow/mlflow:latest
    ports:
      - "5000:5000"
    volumes:
      - mlflow_data:/mlflow
    command: mlflow server --host 0.0.0.0 --backend-store-uri /mlflow
  
  label-studio:
    image: heartexlabs/label-studio:latest
    ports:
      - "8080:8080"
    volumes:
      - label_studio_data:/label-studio/data
    environment:
      - LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true

volumes:
  qdrant_data:
  mlflow_data:
  label_studio_data:
```

**File**: `docker/Dockerfile`

```dockerfile
FROM python:3.11-slim

# System Dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-deu \
    poppler-utils \
    ocrmypdf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python Dependencies
COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements-ml.txt

# App Code
COPY . .

EXPOSE 5001

CMD ["python", "app/app.py"]
```

---

## 🎯 Implementierungs-Timeline

### Sprint 1 (Wochen 1-2): OCR Foundation
- [ ] OCRmyPDF Integration
- [ ] PaddleOCR erweitert
- [ ] OCR-Preprocessor Modul
- [ ] Tests

### Sprint 2 (Wochen 3-4): ML Grundlagen
- [ ] ML-Ordnerstruktur
- [ ] Supplier Classifier Training
- [ ] Date Extractor ML
- [ ] DocType Classifier

### Sprint 3 (Wochen 5-6): Pipeline Integration
- [ ] Pipeline Orchestrator
- [ ] Komponenten verbinden
- [ ] Config-Management
- [ ] Error Handling

### Sprint 4 (Wochen 7-8): Semantic Search
- [ ] Qdrant Integration
- [ ] Embedding Generator
- [ ] Search API
- [ ] Web-UI Integration

### Sprint 5 (Wochen 9-10): MLOps
- [ ] MLflow Setup
- [ ] Experiment Tracking
- [ ] Model Registry
- [ ] Label Studio

### Sprint 6 (Wochen 11-12): Testing
- [ ] Unit Tests
- [ ] Integration Tests
- [ ] E2E Tests
- [ ] Performance Tests

### Sprint 7 (Wochen 13-14): Deployment
- [ ] Docker Setup
- [ ] CI/CD Pipeline
- [ ] Monitoring
- [ ] Documentation

---

## 📊 KPIs & Monitoring

### Qualitäts-Metriken
- **Supplier Recognition Rate**: > 95%
- **Date Extraction Accuracy**: > 90%
- **Quarantine Rate**: < 10%
- **Processing Time**: < 5s pro PDF

### ML-Metriken (MLflow)
- Precision, Recall, F1 pro Modell
- Confusion Matrix
- Feature Importance
- Model Drift Detection

---

## 🔐 Security & Privacy

- **Lokale Ausführung**: Keine Cloud-Dependencies
- **Daten-Isolation**: Jeder Mandant eigene Instanz
- **Audit Logging**: Alle Entscheidungen nachvollziehbar
- **GDPR-Compliant**: Datenlöschung implementiert

---

## 📚 Weitere Ressourcen

- [Docling Docs](https://docling-project.github.io/docling/)
- [OCRmyPDF Docs](https://ocrmypdf.readthedocs.io/)
- [PaddleOCR Docs](https://github.com/PaddlePaddle/PaddleOCR)
- [Qdrant Docs](https://qdrant.tech/documentation/)
- [MLflow Docs](https://mlflow.org/docs/latest/index.html)
