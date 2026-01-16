# 🎯 Docaro Modern Pipeline - Implementierungs-Roadmap

Diese Roadmap zeigt die schrittweise Integration aller Tools in die Docaro-Pipeline.

---

## ✅ Phase 1: Foundation (Woche 1-2)

### 1.1 Ordnerstruktur & Dependencies

- [x] Neue Ordnerstruktur erstellt (`pipelines/`, `ml/`, `services/`)
- [ ] `requirements-pipeline.txt` installieren
- [ ] Docker-Services starten (optional)
- [ ] Basis-Logging einrichten

**Aufgaben**:
```powershell
# Dependencies installieren
pip install -r requirements-pipeline.txt

# Docker-Services starten (optional)
cd docker
docker-compose up -d

# Test: Imports prüfen
python -c "from pipelines import DocumentPipeline; print('✅ OK')"
```

### 1.2 OCR-Integration testen

- [ ] OCRmyPDF mit Testdokument
- [ ] PaddleOCR mit Testdokument
- [ ] Fallback-Logik testen

**Aufgaben**:
```python
from pipelines.ocr_processor import process_with_ocr
from pathlib import Path

# Test mit gescanntem PDF
result = process_with_ocr(Path("test_scan.pdf"), method="auto")
print(f"Methode: {result.method}, Erfolg: {result.success}")
```

### 1.3 Docling-Integration testen

- [ ] Docling mit nativem PDF
- [ ] Tabellen-Extraktion validieren
- [ ] Layout-Analyse prüfen

**Aufgaben**:
```python
from pipelines.document_processor import DoclingProcessor

processor = DoclingProcessor()
result = processor.process(Path("test_invoice.pdf"))
print(f"Tabellen: {len(result.tables)}, Layout: {len(result.layout_elements)}")
```

---

## 🚀 Phase 2: Pipeline-Integration (Woche 3-4)

### 2.1 Haupt-Pipeline implementieren

- [ ] `DocumentPipeline` in bestehenden Code integrieren
- [ ] Qualitätsprüfung vor OCR
- [ ] OCR → Docling → ML Flow testen

**Integration in `app/app.py`**:
```python
from pipelines import DocumentPipeline

# In process_folder oder einzelnem Upload
pipeline = DocumentPipeline()
result = pipeline.process_document(pdf_path)

if result.status == "success":
    # Bestehende Logik für Umbenennung & Verschiebung
    new_filename = build_new_filename(result.supplier, result.date, ...)
    move_to_output(pdf_path, new_filename)
elif result.status == "quarantine":
    move_to_quarantine(pdf_path, result.review_reason)
```

### 2.2 ML-Analyzer erweitern

- [ ] Lieferanten-DB anbinden
- [ ] Datums-Patterns aus `constants.py` nutzen
- [ ] Dokumenttyp-Klassifikation verfeinern

**Aufgaben**:
- Bestehende Regex-Patterns aus `date_parser.py` in `ml_analyzer.py` integrieren
- Fuzzy-Matching für Lieferanten verbessern
- Konfidenz-Schwellenwerte kalibrieren

### 2.3 Quarantäne-Logik verfeinern

- [ ] Konfidenz-Schwellenwerte aus Config laden
- [ ] Detaillierte Review-Gründe loggen
- [ ] Quarantäne-Reports generieren

---

## 🤖 Phase 3: ML-Modelle (Woche 5-8)

### 3.1 Trainingsdaten sammeln

- [ ] Historische Dokumente labeln (manuell)
- [ ] Label Studio Setup
- [ ] Erste 100-200 Dokumente labeln

**Workflow**:
1. Quarantäne-Dokumente exportieren
2. Label Studio Projekt erstellen
3. Team-Labeling (Lieferant, Datum, Typ)
4. Export zu `ml/data/labeled/`

### 3.2 Lieferanten-Klassifikator trainieren

- [ ] Feature-Engineering (TF-IDF, Positionen, Fuzzy-Scores)
- [ ] RandomForest-Modell trainieren
- [ ] MLflow-Tracking einrichten
- [ ] Modell evaluieren & registrieren

**Script**: `ml/training/train_supplier_classifier.py`
```python
# Beispiel-Struktur:
# 1. Lade Trainingsdaten
# 2. Feature-Extraktion
# 3. Train/Test Split
# 4. Training mit MLflow
# 5. Evaluation
# 6. Modell-Registrierung
```

### 3.3 Datums-Extractor trainieren

- [ ] Regex-Kandidaten als Features
- [ ] Kontext-Features (Position, Labels)
- [ ] ML-Ranking-Modell
- [ ] Integration in `ml_analyzer.py`

### 3.4 Dokumenttyp-Klassifikator trainieren

- [ ] Keyword-Features
- [ ] Struktur-Features (Tabellen, Layout)
- [ ] Optional: BERT-Fine-Tuning
- [ ] Deployment

---

## 🔍 Phase 4: Semantische Suche (Woche 9-10)

### 4.1 Qdrant/Chroma Setup

- [ ] Vector-Service testen
- [ ] Embeddings generieren für bestehende Dokumente
- [ ] Bulk-Import in Vektordatenbank

**Bulk-Import-Script**:
```python
from services.vector_service import VectorService
from pathlib import Path
import json

service = VectorService(backend="chroma")

# Lade History
with open("data/history.jsonl") as f:
    for line in f:
        doc = json.loads(line)
        service.store_embedding(
            doc_id=doc['filename'],
            text=doc.get('text', ''),
            metadata={
                'supplier': doc['supplier'],
                'date': doc['date']
            }
        )
```

### 4.2 Semantic Search UI

- [ ] Suchfunktion in Web-UI
- [ ] "Ähnliche Dokumente" Feature
- [ ] Duplikaterkennung

**Integration in `app.py`**:
```python
@app.route('/search', methods=['POST'])
def semantic_search():
    query = request.form.get('query')
    results = vector_service.search(query, top_k=10)
    return render_template('search_results.html', results=results)
```

---

## 🔄 Phase 5: Continual Learning (Woche 11-12)

### 5.1 Feedback-Loop

- [ ] Korrektur-Interface in Web-UI
- [ ] Korrekturen automatisch zu Label Studio exportieren
- [ ] Wöchentliches Re-Training

**Workflow**:
1. User korrigiert Quarantäne-Dokument
2. Korrektur wird als Trainingsdaten gespeichert
3. Wöchentlich: Re-Training mit neuen Daten
4. Modell-Vergleich in MLflow
5. Bestes Modell promoten zu Production

### 5.2 A/B Testing

- [ ] Zwei Modell-Versionen parallel laufen lassen
- [ ] Metriken vergleichen (Accuracy, Quarantäne-Rate)
- [ ] Champion/Challenger Setup

### 5.3 Monitoring & Alerts

- [ ] Metriken-Dashboard (Grafana optional)
- [ ] Alerts bei sinkender Performance
- [ ] Automatische Re-Training-Trigger

---

## 🎓 Phase 6: Advanced Features (Woche 13+)

### 6.1 Docling-Serve API

- [ ] Docling-Serve Container starten
- [ ] API-Client implementieren
- [ ] Parallele Verarbeitung via API

### 6.2 Docling-Agent

- [ ] Ordner-Überwachung
- [ ] Automatische Pipeline-Trigger
- [ ] Batch-Processing mit Priorisierung

### 6.3 LLM-Integration (optional)

- [ ] Ollama lokal installieren
- [ ] LLM für komplexe Extraktion (z.B. Beträge, Artikelnummern)
- [ ] Zero-Shot-Klassifikation für neue Dokumenttypen

### 6.4 Graph-Datenbank (optional)

- [ ] Neo4j für Lieferanten-Beziehungen
- [ ] Dokumenten-Netzwerk visualisieren
- [ ] Anomalie-Detektion

---

## 📊 Success Metrics

### KPIs für Erfolg der Pipeline

| Metrik | Baseline (alt) | Ziel (neu) | Aktuell |
|--------|----------------|------------|---------|
| **Accuracy Lieferant** | ~85% | >92% | - |
| **Accuracy Datum** | ~80% | >90% | - |
| **Quarantäne-Rate** | ~15% | <8% | - |
| **Verarbeitungszeit/Dok** | ~5s | <3s | - |
| **Duplikat-Erkennung** | 0% | >95% | - |

### Tracking

Alle Metriken werden in MLflow geloggt:
```python
mlflow.log_metrics({
    'supplier_accuracy': 0.92,
    'date_accuracy': 0.90,
    'quarantine_rate': 0.08,
    'processing_time_avg': 2.5
})
```

---

## 🐛 Known Issues & Workarounds

### Issue 1: PaddleOCR Hard-Crash (Windows)

**Problem**: PaddleOCR kann auf manchen Windows-Systemen abstürzen.

**Lösung**: Subprocess-Test in `ocr_processor.py` verhindert Crash.

**Workaround**: Falls Problem besteht, in `config.py` setzen:
```python
USE_PADDLEOCR = False
```

### Issue 2: Docling Modelle Download

**Problem**: Beim ersten Start lädt Docling Modelle (langsam).

**Lösung**: Einmalig warm-up durchführen:
```python
from pipelines.document_processor import DoclingProcessor
processor = DoclingProcessor()
# Modelle werden jetzt geladen
```

### Issue 3: Qdrant Connection Failed

**Problem**: Qdrant-Container läuft nicht.

**Lösung**:
```powershell
docker-compose -f docker/docker-compose.yml up -d qdrant
```

**Fallback**: Nutze Chroma (kein Docker nötig):
```python
service = VectorService(backend="chroma")
```

---

## 📝 Nächste Schritte

### Sofort starten:

1. **Dependencies installieren**:
   ```powershell
   pip install -r requirements-pipeline.txt
   ```

2. **Ersten Test durchführen**:
   ```powershell
   python -m pipelines.tests.test_ocr_processor
   ```

3. **Testdokument verarbeiten**:
   ```python
   from pipelines import DocumentPipeline
   from pathlib import Path
   
   pipeline = DocumentPipeline()
   result = pipeline.process_document(Path("test.pdf"))
   print(f"Status: {result.status}")
   ```

### Diese Woche:

- [ ] Phase 1.1 abschließen (Dependencies)
- [ ] Phase 1.2 starten (OCR-Tests)
- [ ] Docker-Services aufsetzen

### Nächste Woche:

- [ ] Phase 2.1 beginnen (Pipeline-Integration)
- [ ] Erste Testdokumente durch komplette Pipeline
- [ ] Quarantäne-Logik anpassen

---

## 💬 Support & Fragen

Bei Fragen oder Problemen:

1. **Dokumentation prüfen**: [PIPELINE.md](PIPELINE.md), [QUICKSTART.md](QUICKSTART.md)
2. **Logs anschauen**: `data/logs/`
3. **Tests ausführen**: `pytest pipelines/tests/ -v`

**Happy Coding! 🚀**
