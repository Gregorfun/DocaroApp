# Docaro - Moderne Dokumenten-Pipeline 🚀

**Intelligentes Tool für automatisierte PDF-Verarbeitung mit KI-Unterstützung**

Docaro verarbeitet Lieferscheine, Rechnungen und andere Dokumente vollautomatisch: OCR, Layout-Analyse, ML-basierte Extraktion von Lieferant, Datum und Dokumenttyp.

---

## 🎯 Features

### ✅ **Robuste OCR-Pipeline**
- Multi-Layer OCR: OCRmyPDF → PaddleOCR → EasyOCR
- Automatische Qualitätserkennung
- Optimiert für deutsche Dokumente

### 🤖 **ML-basierte Extraktion**
- Lieferanten-Klassifikation (Fuzzy-Matching + ML)
- Datums-Extraktion (Hybrid: Regex + ML)
- Dokumenttyp-Erkennung (Rechnung, Lieferschein, etc.)

### 📊 **Docling-Integration**
- Strukturierte Layout-Analyse
- Automatische Tabellen-Extraktion
- Header/Footer/Section-Detection

### 🔍 **Semantische Suche**
- Vektordatenbank (Qdrant/Chroma)
- "Finde ähnliche Dokumente"
- Duplikaterkennung

### 🔄 **Continual Learning**
- Label Studio für manuelles Labeling
- MLflow für Experiment-Tracking
- Automatisches Re-Training mit neuen Daten

---

## 📦 Quick Start

### Installation

```powershell
# Virtual Environment aktivieren
.\.venv\Scripts\Activate.ps1

# Dependencies installieren
pip install -r requirements.txt
pip install -r requirements-pipeline.txt
```

### Start

```powershell
# Anwendung Starten (Hintergrund-Prozess)
.\start_app.ps1

# Anwendung Stoppen
.\stop_app.ps1
```

### Basis-Setup (Windows)

- **Python**: 3.9+
- **Tesseract OCR**: [Download](https://github.com/UB-Mannheim/tesseract/wiki)
- **Poppler**: Bereits in `poppler/` vorhanden

### Docker-Services (Optional)

```powershell
# Starte Qdrant, Label Studio, MLflow
docker-compose -f docker/docker-compose.yml up -d
```

### Start der Web-App

```powershell
./start_app.ps1
```

→ Öffne http://127.0.0.1:5001

---

## 🔐 Login (Registrierung deaktiviert)

Docaro ist nur für registrierte Benutzer nutzbar. Eine Registrierung über das UI ist deaktiviert.

### Seed-User

- `DOCARO_SEED_EMAIL` (Default): `g.machuletz@bracht-autokrane.de`
- `DOCARO_SEED_PASSWORD`: muss in deiner Shell gesetzt werden (wird **nicht** gespeichert/committed)

PowerShell (nur für aktuelle Session):

```powershell
$env:DOCARO_SEED_PASSWORD = "<DEIN_PASSWORT>"
./start_app.ps1
```

Alternativ per Script (Passwort via ENV oder interaktiv):

```powershell
D:/Docaro/.venv/Scripts/python.exe -m scripts.seed_user --email g.machuletz@bracht-autokrane.de
```

---

## ♻️ Stateless Mode (Runtime-Reset)

Beim Start werden alle Dashboard-/Dokument-Runtime-Daten gelöscht, damit nach einem Neustart keine alten Dokumente erscheinen.

Gelöscht/geleert (best-effort):

- `data/tmp/`, `data/eingang/`, `data/fertig/`, `data/quarantaene/`
- `data/settings.json`, `data/session_files.json`, `data/supplier_corrections.json`, `data/history.jsonl`
- `data/logs/` (Logfiles)

Nicht gelöscht:

- `ml/` (Modelle/ML-Daten)
- `data/auth/` (User-DB)

---

## 🚀 Neue Pipeline nutzen

### Einzelnes Dokument verarbeiten

```python
from pipelines import DocumentPipeline
from pathlib import Path

pipeline = DocumentPipeline()
result = pipeline.process_document(Path("dokument.pdf"))

print(f"Lieferant: {result.supplier} (Conf: {result.supplier_confidence:.2f})")
print(f"Datum: {result.date} (Conf: {result.date_confidence:.2f})")
print(f"Dokumenttyp: {result.document_type}")
```

### OCR auf gescanntem PDF

```python
from pipelines.ocr_processor import process_with_ocr

result = process_with_ocr(pdf_path, method="auto")
# Automatische Wahl: OCRmyPDF → PaddleOCR → EasyOCR
```

### Semantische Suche

```python
from services.vector_service import VectorService

service = VectorService(backend="chroma")
results = service.search("Rechnungen von ABC GmbH Januar 2026")
```

---

## 📚 Dokumentation

- **[PIPELINE.md](PIPELINE.md)** - Vollständige Architektur-Dokumentation
- **[QUICKSTART.md](QUICKSTART.md)** - Schnelleinstieg mit Beispielen
- **[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)** - Schrittweise Integration
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Übersicht aller Komponenten

---

## 🛠️ Technologie-Stack

### Dokumenten-Verarbeitung
- **Docling** - PDF Layout-Analyse & Tabellen-Extraktion
- **Docling-Core** - Strukturierte Dokumenten-Typen
- **OCRmyPDF** - Searchable PDFs
- **PaddleOCR** - Hochpräzise OCR (100+ Sprachen)
- **EasyOCR** - Leichtgewichtige Alternative

### Machine Learning
- **Scikit-learn** - Klassifikation & Feature-Engineering
- **Transformers** - BERT-basierte Modelle (optional)
- **Sentence-Transformers** - Embeddings für semantische Suche

### MLOps
- **MLflow** - Experiment-Tracking & Model Registry
- **Label Studio** - Annotations & Trainingsdaten

### Vektordatenbanken
- **Chroma** - Lightweight, einfaches Setup
- **Qdrant** - High-Performance, production-ready

---

## 🗂️ Projekt-Struktur

```
Docaro/
├── pipelines/              # 🔄 Haupt-Pipeline-Module
│   ├── document_pipeline.py
│   ├── ocr_processor.py
│   ├── document_processor.py
│   └── ml_analyzer.py
│
├── ml/                     # 🤖 ML-Komponenten
│   ├── models/            # Trainierte Modelle
│   ├── training/          # Training-Scripts
│   ├── inference/         # Inference-Wrapper
│   └── data/              # Trainingsdaten
│
├── services/              # 🛠️ Externe Services
│   ├── vector_service.py  # Qdrant/Chroma
│   └── mlflow_service.py  # MLflow
│
├── app/                   # 🌐 Web-Interface
│   └── app.py
│
├── core/                  # 📄 Alte Extraktoren (Legacy)
│   ├── extractor.py
│   └── docling_extractor.py
│
└── docker/                # 🐳 Docker-Compose
    └── docker-compose.yml
```

---

## 🎓 Wichtige Konzepte

### Pipeline-Workflow

```
PDF → Qualitätsprüfung → OCR (falls nötig) → Docling (Layout) 
    → ML-Analyse (Supplier/Date/Type) → Quarantäne-Check 
    → Finalisierung (Umbenennung & Verschiebung)
```

### Quarantäne-System

Dokumente mit niedriger Konfidenz landen in `data/quarantaene/` zur manuellen Review:
- Lieferant-Confidence < 85%
- Datum-Confidence < 75%

### Continual Learning

1. Quarantäne-Dokumente → Label Studio
2. Manuelles Labeling
3. Export → Training-Daten
4. Re-Training mit MLflow
5. Deployment bestes Modell

---

## 🔧 Konfiguration

### Umgebungsvariablen

**Tesseract & Poppler**:
- `DOCARO_TESSERACT_CMD` – Pfad zur `tesseract.exe`
- `DOCARO_POPPLER_BIN` – Pfad zum Poppler `bin`-Ordner

**OCR-Einstellungen**:
- `DOCARO_OCR_PAGES` – Anzahl Seiten für OCR (Default: 2)
- `DOCARO_OCR_TIMEOUT` – OCR Timeout in Sekunden (Default: 8)
- `DOCARO_USE_PADDLEOCR=1` – PaddleOCR aktivieren (wenn installiert)
- `DOCARO_PADDLEOCR_LANG=german` – PaddleOCR Sprache

**Pipeline-Einstellungen**:
- `DOCARO_QUAR_SUPPLIER_MIN` – Min. Confidence für Lieferant (Default: 0.85)
- `DOCARO_QUAR_DATE_MIN` – Min. Confidence für Datum (Default: 0.75)

---

## 🛠️ Tools & Scripts

### Batch-Report für Ordner

```powershell
# Report ohne Dateien zu verschieben
python tools/report_incoming.py "data/eingang"
```

### Pipeline-Test

```powershell
# Teste neue Pipeline mit Testdokument
python -c "from pipelines import DocumentPipeline; pipeline = DocumentPipeline(); print(pipeline.process_document(Path('test.pdf')))"
```

### Docker-Services verwalten

```powershell
# Starten
docker-compose -f docker/docker-compose.yml up -d

# Stoppen
docker-compose -f docker/docker-compose.yml down

# Logs
docker-compose -f docker/docker-compose.yml logs -f
```

---

## 🧪 Testing

```powershell
# Tests ausführen
pytest pipelines/tests/ -v

# Mit Coverage
pytest pipelines/tests/ --cov=pipelines --cov-report=html
```

---

## 📖 Weitere Dokumentation

- **Docling**: https://github.com/docling-project/docling
- **PaddleOCR**: https://github.com/PaddlePaddle/PaddleOCR
- **MLflow**: https://mlflow.org/docs/latest/
- **Label Studio**: https://labelstud.io/guide/
- **Qdrant**: https://qdrant.tech/documentation/

---

## 🤝 Contributing

Pull Requests willkommen! Siehe [CONTRIBUTING.md](CONTRIBUTING.md)

---

## 📝 Lizenz

Siehe [LICENSE](LICENSE)

---

## 🎉 Los geht's!

```powershell
# 1. Installation
pip install -r requirements-pipeline.txt

# 2. Services starten (optional)
docker-compose -f docker/docker-compose.yml up -d

# 3. Web-App starten
./start_app.ps1

# 4. Öffne http://localhost:5000
```

**Viel Erfolg mit Docaro! 🚀**

Einzel-PDF Diagnose (Rotation/ROI OCR):

```powershell
D:/Docaro/.venv/Scripts/python.exe tools/inspect_pdf.py "D:\Docaro\Daten eingang\scan_20251120054226.pdf"
```

## Repo-Hinweis

Eingangsordner/Scans und generierte Reports/Logs werden per `.gitignore` bewusst nicht mitversioniert.
