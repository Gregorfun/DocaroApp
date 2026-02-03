# 🚀 Docaro Modern Pipeline - Quick Start Guide

Dieser Guide hilft dir, die neue Docaro-Pipeline schnell zum Laufen zu bringen.

---

## 📋 Voraussetzungen

### System-Requirements

- **Python**: 3.9 oder höher
- **RAM**: Mindestens 8 GB (16 GB empfohlen für ML-Modelle)
- **Speicherplatz**: 10+ GB für Modelle und Daten
- **Docker** (optional, für Services): Docker Desktop oder Docker Engine

### Windows-Spezifisch

- **Tesseract OCR**: [Download](https://github.com/UB-Mannheim/tesseract/wiki)
- **Poppler**: Bereits in `poppler/` vorhanden

---

## 🔧 Installation

### Schritt 1: Basis-Dependencies installieren

```powershell
# Aktiviere Virtual Environment
.\.venv\Scripts\Activate.ps1

# Installiere Pipeline-Dependencies
pip install -r requirements.txt
pip install -r requirements-pipeline.txt
```

### Schritt 2: Anwendung starten

Verwende das bereitgestellte Start-Skript (konfiguriert Tesseract, Ports und Logging automatisch):

```powershell
.\start_app.ps1
```

Zum Beenden der Anwendung:
```powershell
.\stop_app.ps1
```

### Schritt 3: Services starten (optional)

Für semantische Suche, Label Studio und MLflow:

```powershell
cd docker
docker-compose up -d
```

**Zugriff**:
- Qdrant: http://localhost:6333/dashboard
- Label Studio: http://localhost:8080
- MLflow: http://localhost:5000

---

## 🎯 Erste Schritte

### 1. Einzelnes Dokument verarbeiten

```python
from pathlib import Path
from pipelines import DocumentPipeline

# Initialisiere Pipeline
pipeline = DocumentPipeline(
    quarantine_threshold_supplier=0.85,
    quarantine_threshold_date=0.75,
    use_vector_db=False  # Auf True setzen für semantische Suche
)

# Verarbeite PDF
pdf_path = Path("data/eingang/rechnung.pdf")
result = pipeline.process_document(pdf_path)

# Ergebnis prüfen
print(f"Status: {result.status}")
print(f"Lieferant: {result.supplier} (Conf: {result.supplier_confidence:.2f})")
print(f"Datum: {result.date} (Conf: {result.date_confidence:.2f})")
print(f"Dokumenttyp: {result.document_type}")
```

### 2. OCR auf gescanntem PDF

```python
from pathlib import Path
from pipelines.ocr_processor import process_with_ocr

pdf_path = Path("gescanntes_dokument.pdf")

# Automatische Methodenwahl
result = process_with_ocr(pdf_path, method="auto")

if result.success:
    print(f"✅ OCR erfolgreich mit {result.method}")
    print(f"   Ausgabe: {result.output_path}")
else:
    print(f"❌ OCR fehlgeschlagen: {result.error}")
```

### 3. Docling-Verarbeitung

```python
from pathlib import Path
from pipelines.document_processor import DoclingProcessor

processor = DoclingProcessor()
result = processor.process(
    Path("dokument.pdf"),
    extract_tables=True,
    extract_layout=True,
    chunk_text=True
)

if result.success:
    print(f"📄 Text: {len(result.text)} Zeichen")
    print(f"📊 Tabellen: {len(result.tables)}")
    print(f"🏗️  Layout-Elemente: {len(result.layout_elements)}")
    print(f"✂️  Chunks: {len(result.chunks)}")
    
    # Export
    processor.export_to_markdown(
        result.docling_document,
        Path("output.md")
    )
```

### 4. Semantische Suche

```python
from services.vector_service import VectorService

# Initialisiere (Chroma oder Qdrant)
service = VectorService(backend="chroma")

# Speichere Dokument
service.store_embedding(
    doc_id="invoice_001",
    text="Rechnung von ABC GmbH vom 15.01.2026...",
    metadata={
        'supplier': 'ABC GmbH',
        'date': '2026-01-15',
        'document_type': 'Rechnung'
    }
)

# Suche
results = service.search(
    query_text="Rechnungen von ABC GmbH im Januar",
    top_k=5
)

for r in results:
    print(f"🔍 {r.id}: Score {r.score:.3f}")
    print(f"   Lieferant: {r.metadata.get('supplier')}")
```

### 5. ML-Training mit MLflow

```python
from services.mlflow_service import MLflowService

mlflow_service = MLflowService(experiment_name="docaro_training")

# Starte Training-Run
with mlflow_service.start_run("supplier_classifier_v1"):
    # Trainiere Modell
    model = train_your_model()
    
    # Logge Parameter
    mlflow_service.log_params({
        'n_estimators': 200,
        'max_depth': 20
    })
    
    # Logge Metriken
    mlflow_service.log_metrics({
        'accuracy': 0.92,
        'f1_score': 0.89
    })
    
    # Registriere Modell
    mlflow_service.log_model(
        model,
        artifact_path="model",
        registered_model_name="supplier_classifier"
    )

print("✅ Modell trainiert und registriert")
print("   → MLflow UI: http://localhost:5000")
```

---

## 🧪 Testing

```powershell
# Installiere Test-Dependencies
pip install pytest pytest-cov

# Führe Tests aus
pytest pipelines/tests/ -v

# Mit Coverage
pytest pipelines/tests/ --cov=pipelines --cov-report=html
```

---

## 📊 Label Studio Workflow

### 1. Quarantäne-Dokumente exportieren

```python
from pathlib import Path
from ml.training.label_studio_integration import quarantine_to_label_studio_workflow
from config import Config

config = Config()
quarantine_to_label_studio_workflow(config.QUARANTINE_DIR)
```

### 2. Manuelles Labeling

1. Öffne http://localhost:8080
2. Erstelle Account (beim ersten Mal)
3. Label Dokumente (Lieferant, Datum, Dokumenttyp)

### 3. Gelabelte Daten importieren

```python
from ml.training.label_studio_integration import LabelStudioIntegration
from pathlib import Path

ls = LabelStudioIntegration(project_id=1)

# Importiere Labels
labeled_docs = ls.import_from_label_studio()

# Bereite Training-Daten vor
ls.prepare_training_data(
    labeled_docs,
    output_dir=Path("ml/data/labeled")
)
```

---

## 🔄 Kompletter Workflow

### Batch-Verarbeitung

```python
from pathlib import Path
from pipelines import DocumentPipeline
from config import Config

config = Config()
pipeline = DocumentPipeline()

# Verarbeite alle PDFs in data/eingang/
for pdf_path in config.INBOX_DIR.glob("*.pdf"):
    print(f"\n📄 Verarbeite: {pdf_path.name}")
    
    result = pipeline.process_document(pdf_path)
    
    if result.status == "success":
        print(f"✅ Erfolgreich:")
        print(f"   Lieferant: {result.supplier}")
        print(f"   Datum: {result.date}")
        
        # Hier: Verschiebe nach fertig/, benenne um, etc.
        
    elif result.status == "quarantine":
        print(f"⚠️  Quarantäne: {result.review_reason}")
        
        # Hier: Verschiebe nach quarantaene/
        
    else:
        print(f"❌ Fehler: {result.error}")
```

---

## 🐛 Troubleshooting

### OCRmyPDF nicht gefunden

**Windows**:
```powershell
# Tesseract installieren
choco install tesseract

# Oder manuell: https://github.com/UB-Mannheim/tesseract/wiki
```

### PaddleOCR Fehler

```powershell
# GPU-Version (falls CUDA verfügbar)
pip install paddlepaddle-gpu

# Oder CPU-Version
pip install paddlepaddle
```

### Docling Import-Fehler

```powershell
# Neueste Version installieren
pip install --upgrade docling docling-core
```

### Docker-Services nicht erreichbar

```powershell
# Prüfe Status
docker-compose -f docker/docker-compose.yml ps

# Logs anzeigen
docker-compose -f docker/docker-compose.yml logs -f qdrant

# Neustarten
docker-compose -f docker/docker-compose.yml restart
```

---

## 📚 Weiterführende Dokumentation

- **Pipeline-Architektur**: [PIPELINE.md](PIPELINE.md)
- **Integration-Roadmap**: [INTEGRATION_ROADMAP.md](INTEGRATION_ROADMAP.md)
- **Docling-Integration**: [DOCLING_INTEGRATION.md](DOCLING_INTEGRATION.md)

---

## 💡 Tipps & Best Practices

### Performance-Optimierung

1. **OCR**: Nutze `ocrmypdf` für beste Balance zwischen Speed und Qualität
2. **Docling**: Deaktiviere Tabellen-Extraktion für simple Dokumente
3. **Vector DB**: Nutze Qdrant für >100k Dokumente, Chroma für kleinere Mengen
4. **ML-Modelle**: Starte mit einfachen Scikit-learn Modellen, wechsle zu BERT nur bei Bedarf

### Monitoring

```python
from monitoring import setup_logging, log_pipeline_step

# Structured Logging aktivieren
setup_logging(log_dir=Path("data/logs"))

# In Pipeline nutzen
log_pipeline_step(
    step="ml_analysis",
    pdf_path=pdf_path,
    supplier=result.supplier,
    confidence=result.supplier_confidence
)
```

### Continual Learning

1. Sammle Quarantäne-Fälle
2. Label mit Label Studio
3. Trainiere Modelle mit neuen Daten
4. Evaluiere mit MLflow
5. Deploye beste Modelle

---

## 🎉 Los geht's!

```powershell
# 1. Dependencies installieren
pip install -r requirements-pipeline.txt

# 2. Services starten (optional)
docker-compose -f docker/docker-compose.yml up -d

# 3. Erste Pipeline-Run
python -c "from pipelines import DocumentPipeline; pipeline = DocumentPipeline(); print('✅ Pipeline bereit!')"

# 4. Verarbeite Testdokument
# (Lege PDF in data/eingang/ und führe Pipeline aus)
```

**Viel Erfolg mit der neuen Docaro-Pipeline! 🚀**
