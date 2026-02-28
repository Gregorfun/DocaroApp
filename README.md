# Docaro - Dokumenten-OCR & Extraktion

Docaro ist eine Flask-Web-App (Gunicorn) mit RQ-Worker (Redis), die PDF-Dokumente verarbeitet: Text-Layer nutzen, OCR-Fallback (Tesseract), Extraktion (Lieferant/Datum/Dokumenttyp/Dokumentnummer) und Review/Quarantäne.

## 🐧 Linux/VPS Deployment

Für einen produktiven Linux-Server (Installation nach `git pull`, systemd-Services, Nginx/Reverse-Proxy, System-Abhängigkeiten, Daten-Migration) siehe:

- [DEPLOYMENT_LINUX.md](DEPLOYMENT_LINUX.md)
- [DEPENDENCIES.md](DEPENDENCIES.md)

Wenn das ursprüngliche Git-Remote nicht mehr existiert:

- [NEW_GITHUB_REPO_SETUP.md](NEW_GITHUB_REPO_SETUP.md)

## 📈 Observability (Prometheus + Grafana)

Docaro exportiert Laufzeitmetriken aus dem Worker (Port `9108`, konfigurierbar via `DOCARO_WORKER_METRICS_PORT`) und aus dem Web-Service (`/metrics` auf Port `5001`):

- `docaro_ocr_duration_seconds`
- `docaro_pdf_render_duration_seconds`
- `docaro_pipeline_queue_depth`
- `docaro_pipeline_step_errors_total`
- `docaro_pipeline_step_duration_seconds`

Monitoring-Stack starten:

```bash
docker compose -f docker/docker-compose.yml up -d prometheus grafana redis-exporter
```

Danach:

- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000` (`admin` / `admin`)

Das Basis-Dashboard wird automatisch provisioniert (`Docaro Observability`), inklusive P95/P99-Latenzen und Queue-/Error-Sicht.
Zusätzlich sind Alert-Rules für Worker/Web-Down, Error-Rate, Queue-Backlog sowie OCR-P95/P99 enthalten.

## ⚡ Runtime Performance

JSON-Hotpaths (`session_files`, `history`, `supplier_corrections`) laufen jetzt über SQLite
(`data/runtime_state.db`) mit automatischer Bestandsmigration beim ersten Start.

Manuelle Migration/Verifikation:

```bash
python tools/migrate_runtime_store.py
```

Perzentil-Report aus `data/logs/run.csv`:

```bash
python tools/report_performance_percentiles.py
```

## 🧠 Document Intelligence (neu)

- Automatisches Routing pro Dokument (`processing_route`) basierend auf `doc_type`
- Unsicherheits-Priorisierung für Review (`review_priority_score`)
- Supplier-Profile (`config/supplier_profiles.json`, Vorlage: `config/supplier_profiles.example.json`)
- Dubletten-Erkennung im Upload via SHA-256 (SQLite-Registry)
- Human-in-the-loop Learning: Korrekturen werden zusätzlich als Samples in `data/ml/ground_truth.jsonl` geschrieben
- Tabellen-Intelligence (optional): zusätzliche Tabellenzeilen aus PDFs werden für `doc_type`/`doc_number` genutzt
  - Aktivierung: `DOCARO_TABLE_INTELLIGENCE_ENABLED=1`
  - Optionaler externer Adapter: `DOCARO_HF_TABLE_WEBHOOK` (sonst lokaler `pdfplumber`-Fallback)
- LLM-Assist (optional, z.B. Ollama lokal) für unsichere Fälle
  - Aktivierung: `DOCARO_LLM_ASSIST_ENABLED=1`
  - Modell: `DOCARO_LLM_ASSIST_MODEL` (z.B. `llama3.1:8b-instruct`)
  - Endpoint: `DOCARO_LLM_ASSIST_ENDPOINT` (Standard: `http://127.0.0.1:11434`)
  - Wird konservativ als Rescue-Pfad genutzt (kein erzwungenes Überschreiben guter Werte)

## 🚨 Exception Tracking (Sentry)

Sentry ist optional und wird nur aktiviert, wenn `DOCARO_SENTRY_DSN` gesetzt ist.

Relevante ENV-Variablen:

- `DOCARO_SENTRY_ENABLED=1`
- `DOCARO_SENTRY_DSN=...`
- `DOCARO_SENTRY_ENVIRONMENT=production|staging|development`
- `DOCARO_RELEASE=docaro-<sha>`
- `DOCARO_SENTRY_TRACES_SAMPLE_RATE=0.1` (optional)

Sentry ist im Web-Service und im RQ-Worker eingebunden, inklusive RQ-Integration für Job-Exceptions.

## 🧠 Retraining Gates

Retraining kann Modelle nur bei Mindestqualität in „production“ promoten
(`data/ml/production_models.json`):

- `DOCARO_MODEL_MIN_ACCURACY`
- `DOCARO_MODEL_MIN_F1_WEIGHTED`
- `DOCARO_MODEL_ALLOW_NO_EVAL`

## 🧰 RQ Dashboard

Das RQ Dashboard ist in die Flask-App integriert und standardmäßig unter `/rq` erreichbar
(Login-Schutz über die bestehende Auth-Middleware).

Konfiguration:

- `DOCARO_RQ_DASHBOARD_ENABLED=1`
- `DOCARO_RQ_DASHBOARD_URL_PREFIX=/rq`

## 👥 Multi-User Isolation

Docaro trennt Laufzeitdaten pro Benutzer:

- User-spezifische Verzeichnisse unter `data/users/<user_scope>/`
  - `tmp/`, `eingang/`, `fertig/`, `quarantaene/`
- User-spezifische Ergebnis-/Progress-Dateien
- Job-Metadaten (`owner_scope`) in der Queue
- Dokument-Ownership im RuntimeStore (`owned_documents`)
- SHA-256-Dedupe user-scoped (keine user-übergreifende "bekannt"-Leckage)

## 🔐 Security Hardening

Optionale Schutzmechanismen (standardmäßig risikoarm konfiguriert):

- Upload/Login Rate-Limits: `DOCARO_RATE_LIMIT_UPLOAD`, `DOCARO_RATE_LIMIT_LOGIN`
- CSRF-Absicherung für mutierende Requests: `DOCARO_CSRF_STRICT=0|1`
- Stufenweiser Rollout für CSRF-Härtung: `DOCARO_CSRF_CANARY_PERCENT=0..100`
- Stufenweiser Rollout für Upload-Pipeline-Änderungen: `DOCARO_UPLOAD_CANARY_PERCENT=0..100`

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

### 🤖 ML Training (Automatisch, Nightly)

Docaro trainiert jedes Nacht um 02:00 Uhr automatisch neue Modelle basierend auf Korrektionen:

```bash
# ML-Training Service Status
sudo systemctl status docaro-ml-scheduler

# Trainings-Logs anschauen
tail -f /opt/Docaro/data/logs/extract_debug.log | grep -i training
```

→ Modelle werden besser, je mehr du korrigierst!

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
from core.extractor import ocr_first_page
from pathlib import Path

# Tesseract als Primary, PaddleOCR als Fallback (bei Score < 400)
result = ocr_first_page(Path("dokument.pdf"), poppler_bin=None)
print(f"Erkannter Text: {result['text']}")
print(f"Score: {result['score']}")
```

### Semantische Suche

```python
from services.vector_service import VectorService

# Standard-Profil (sentence-transformers)
service = VectorService(backend="chroma", embedding_profile="sentence-transformers")
# Optional: VDR-optimiertes Dense-Profil
# service = VectorService(backend="chroma", embedding_profile="bimodernvbert")

results = service.search("Rechnungen von ABC GmbH Januar 2026")
```

Für Visual-Retrieval-Modelle (optional):

```bash
pip install -r requirements-visual-retrieval.txt
```

ENV-Overrides für Pipeline-Embedding:

```bash
export DOCARO_EMBEDDING_PROFILE=bimodernvbert
export DOCARO_VECTOR_BACKEND=chroma
```

Granite-Docling Pilot (separat, ohne Main-Pipeline-Umbau):

```bash
/opt/Docaro/.venv/bin/python tools/pilot_granite_docling.py --source data/eingang/dein_dokument.pdf
```

VDR-Benchmark (inkl. `colnomic-7b`):

```bash
/opt/Docaro/.venv/bin/python tools/build_vdr_pairs.py --output data/ml/vdr_pairs.jsonl
/opt/Docaro/.venv/bin/python tools/benchmark_visual_retrieval.py --input data/ml/vdr_pairs.jsonl --profiles bimodernvbert colnomic-7b
```

---

## 📚 Dokumentation

- **[PIPELINE.md](PIPELINE.md)** - Vollständige Architektur-Dokumentation
- **[QUICKSTART.md](QUICKSTART.md)** - Schnelleinstieg mit Beispielen
- **[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)** - Schrittweise Integration
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Übersicht aller Komponenten

## 🧪 DevEx & Qualität

### Pre-commit + Ruff

```bash
pip install -r requirements-dev.txt
pre-commit install
pre-commit run --all-files
```

### Performance-Baselines

- `pytest-benchmark`:
  ```bash
  pytest tests/performance/test_benchmark_extractor.py --benchmark-only
  ```
- `Locust`:
  ```bash
  DOCARO_LOAD_HOST=http://127.0.0.1:5001 locust -f loadtests/locustfile.py
  ```
- `k6`:
  ```bash
  BASE_URL=http://127.0.0.1:5001 k6 run loadtests/k6-smoke.js
  ```

### Dependency-Updates

Dependabot ist über `.github/dependabot.yml` aktiviert (pip, GitHub Actions, Docker).
Zusätzlich läuft ein Security-Workflow mit `pip-audit` unter `.github/workflows/security.yml`.

## 🗃️ Data Versioning (DVC)

Für Trainingsdaten-Reproduzierbarkeit ist ein DVC-Stage vorbereitet:

```bash
pip install -r requirements-dev.txt
dvc repro ground_truth_snapshot
```

Der Stage exportiert `data/ml/ground_truth.jsonl` nach `artifacts/ml/ground_truth_snapshot.jsonl`
(`dvc.yaml`, `tools/export_ground_truth_snapshot.py`).

## 📉 Drift Monitoring (optional)

Optionales Evidently-basiertes Drift-Reporting:

```bash
python tools/drift_report.py
```

Outputs:
- `artifacts/drift/drift_report.html` (wenn Evidently installiert)
- `artifacts/drift/drift_report.json`

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

### Aktiv genutzten Tools
- **PaddleOCR**: https://github.com/PaddlePaddle/PaddleOCR (Fallback-OCR für schwierige Scans)
- **MLflow**: https://mlflow.org/docs/latest/ (Experiment-Tracking für ML-Training)

### Setup & Deployment
- **Tesseract OCR**: https://github.com/UB-Mannheim/tesseract/wiki (Primary OCR)
- **PDF-Verarbeitung**: pdf2image, PyPDF2, pdfplumber (Dokumentenhandling)

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
