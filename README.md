# Docaro - Dokumenten-OCR & Extraktion

Docaro ist eine Flask-Web-App (Gunicorn) mit RQ-Worker (Redis), die PDF-Dokumente verarbeitet: Text-Layer nutzen, OCR-Fallback (Tesseract), Extraktion (Lieferant/Datum/Dokumenttyp/Dokumentnummer) und Review/Quarantäne.

## 🐧 Linux/VPS Deployment

Für einen produktiven Linux-Server (Installation nach `git pull`, systemd-Services, Nginx/Reverse-Proxy, System-Abhängigkeiten, Daten-Migration) siehe:

- [DEPLOYMENT_LINUX.md](DEPLOYMENT_LINUX.md)
- [DEPENDENCIES.md](DEPENDENCIES.md)

Wenn das ursprüngliche Git-Remote nicht mehr existiert:

- [NEW_GITHUB_REPO_SETUP.md](NEW_GITHUB_REPO_SETUP.md)

---

## 🎯 Features

### ✅ **Robuste Verarbeitung**
- Text-Layer zuerst, OCR-Fallback via Tesseract
- PDF → Images via `pdf2image` (Poppler: `pdfinfo`/`pdftoppm`)
- Timeouts + Quarantäne/Review bei Fehlern

### 🧾 **Extraktion & Review**
- Lieferant/Datum/Dokumenttyp/Dokumentnummer inkl. Confidence
- Review-Queue zum manuellen Korrigieren und Finalisieren

### 🧩 **Optional: Extras/ML**
- Zusätzliche Stacks sind bewusst getrennt (siehe `requirements-*.txt`), damit Server-Updates stabil bleiben.

Typische Files:
- Runtime (minimal): `requirements.txt`
- ML light: `requirements-ml.txt`
- Docling: `requirements-docling.txt`
- PaddleOCR: `requirements-paddleocr.txt`
- Große Komplett-Stacks: `requirements-ml-full.txt`, `requirements-pipeline.txt`

---

## 📦 Quick Start

### Linux (lokal/dev)

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python app/app.py
```

→ Öffne http://127.0.0.1:5001

Für Produktion unter systemd: [DEPLOYMENT_LINUX.md](DEPLOYMENT_LINUX.md)

### Windows

```powershell
\.\start_app.ps1
\.\stop_app.ps1
```

Basis-Setup (Windows):
- Python: 3.9+
- Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki
- Poppler: falls nicht im System installiert, nutze ein lokales Poppler-Bundle

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

Optional und **potenziell destruktiv**: Wenn `DOCARO_STATELESS=1` gesetzt ist, wird beim Start des Web-Services (nicht beim Worker) ein Best-Effort-Reset des Runtime-States ausgeführt, damit nach einem Neustart keine alten Dokumente im Dashboard hängen bleiben.

Empfehlung: In Produktion nur aktivieren, wenn du wirklich „sauberen Neustart“ willst.

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
