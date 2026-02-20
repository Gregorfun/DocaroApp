# 🤖 ML-Training in Docaro - Automatisches Lernen

## 📋 Übersicht

Docaro hat ein **automatisches, selbstlernendes System**:

1. **Benutzer korrigiert Extraktion** (Lieferant, Datum, Dokumenttyp)
2. **Korrektionen werden gesammelt** → `ground_truth.jsonl`
3. **Jede Nacht um 02:00 Uhr trainiert das System** automatisch
4. **Neues Modell wird aktualisiert** → `supplier_model.pkl`
5. **Nächster Scan nutzt besseres Modell** ✅

---

## 🔄 **Workflow: Selbstlernend**

```
┌─────────────────────────────────┐
│  Scan hochladen                 │
└────────────┬────────────────────┘
             ↓
┌─────────────────────────────────┐
│  Tesseract OCR (Primary)        │
│  + PaddleOCR (Fallback)         │
└────────────┬────────────────────┘
             ↓
┌─────────────────────────────────┐
│  TF-IDF Klassifikator           │  ← Trainiert jede Nacht!
│  (Lieferant-Erkennung)          │
└────────────┬────────────────────┘
             ↓
┌─────────────────────────────────┐
│  Extraktion zeigen              │
│  (Lieferant, Datum, etc.)       │
└────────────┬────────────────────┘
             ↓
┌─────────────────────────────────┐
│  User: Korrekt? Falsch?         │
│  → Speichere Korrektur          │
└────────────┬────────────────────┘
             ↓
┌─────────────────────────────────┐
│  🌙 02:00 Uhr: Training         │
│  - Sammle Korrektionen          │
│  - Trainiere Modell neu         │
│  - Speichere supplier_model.pkl │
└────────────┬────────────────────┘
             ↓
         ✅ System wird besser!
```

---

## 📊 **Training Status & Logs**

### Service Status

```bash
# Check ob ML-Training läuft
sudo systemctl status docaro-ml-scheduler

# Siehe letzte Training-Ausführung
sudo systemctl status docaro-ml-scheduler -l | tail -20
```

### Training-Logs

```bash
# Wenn ML-Training um 02:00 läuft:
journalctl -u docaro-ml-scheduler -n 50

# Beispiel Output:
# 2026-02-06 02:00:00 INFO - Lade Trainingsdaten von: /opt/Docaro/data/ml/ground_truth.jsonl
# 2026-02-06 02:00:00 INFO - Trainingsdaten: supplier=6, date=6, doctype=6
# 2026-02-06 02:00:01 INFO - Modell gespeichert: /opt/Docaro/data/ml/supplier_model.pkl
# 2026-02-06 02:00:01 INFO - Nächstes Training: 2026-02-07 02:00:00
```

### Training-Daten

```bash
# Daten für Training anschauen
cat /opt/Docaro/data/ml/ground_truth.jsonl | head -1 | python3 -m json.tool

# Beispiel:
# {
#   "doc_id": "test_001",
#   "text": "Lieferschein Manitowoc GmbH Datum: 2026-01-15",
#   "labels": {
#     "supplier_canonical": "Manitowoc",
#     "doc_type": "LIEFERSCHEIN",
#     "doc_date_iso": "2026-01-15"
#   }
# }
```

### Modell-Info

```bash
# Trainiertes Modell anschauen (Größe, Datum)
ls -lh /opt/Docaro/data/ml/supplier_model.pkl

# Beispiel:
# -rw-r--r-- 1 docaro docaro 6.5K Feb 6 02:00 supplier_model.pkl
```

---

## 🎯 **Wie Korrektionen hinzufügen?**

### Über Web-UI (Empfohlen)

1. **PDF hochladen** → https://www.docaro.de
2. **Extraktion überprüfen** (Lieferant, Datum, Dokumenttyp)
3. **Falls falsch: Bearbeiten** → Korrekte Werte eingeben
4. **Speichern** → Korrektur wird gesammelt
5. **🌙 Nächte Nacht** → Training mit deiner Korrektur!

### Manuell (ground_truth.jsonl)

```bash
# Training-Daten manuell hinzufügen
echo '{"doc_id":"scan_123","text":"...Lieferschein...","labels":{"supplier_canonical":"Manitowoc","doc_type":"LIEFERSCHEIN","doc_date_iso":"2026-01-15"}}' >> /opt/Docaro/data/ml/ground_truth.jsonl

# Training sofort starten (statt warten bis 02:00)
python3 -c "from ml.retrain_scheduler import RetrainScheduler; from config import Config; from pathlib import Path; scheduler = RetrainScheduler(Path('/opt/Docaro/data/ml/ground_truth.jsonl')); scheduler.train_supplier_model()"
```

---

## 🔧 **Konfiguration**

### Training-Zeit ändern

Editiere `/etc/systemd/system/docaro-ml-scheduler.service`:

```ini
[Service]
ExecStart=/opt/Docaro/.venv/bin/python -c "from ml.retrain_scheduler import RetrainScheduler; scheduler = RetrainScheduler(..., schedule_time=time(3, 0))"  # 03:00 Uhr statt 02:00
```

Dann neustarten:
```bash
sudo systemctl daemon-reload
sudo systemctl restart docaro-ml-scheduler
```

### Minimum Korrektionen für Training

```python
# In ml/retrain_scheduler.py
scheduler = RetrainScheduler(
    ...
    min_corrections=5  # Default: 10
)
# Training startet erst wenn >= 5 Korrektionen gesammelt
```

---

## 📈 **MLflow - Experiment Tracking**

Das System speichert Training-Metriken in MLflow:

```bash
# MLflow-Datenbank ansehen
sqlite3 /opt/Docaro/data/ml/mlflow.db ".tables"

# Letzte Training-Experimente
sqlite3 /opt/Docaro/data/ml/mlflow.db "SELECT * FROM experiments LIMIT 5;"
```

**Metriken pro Training:**
- ✅ Accuracy auf Validation-Set
- ✅ Precision/Recall für Supplier-Klassifikation
- ✅ Training-Zeit
- ✅ Anzahl Samples

---

## 🎓 **Machine Learning Modelle erklärt**

### **Supplier-Klassifikation (Hauptmodell)**

**Algorithmus:** TF-IDF + LogisticRegression

```python
# Funktionsweise:
1. Text in Zahlen umwandeln (TF-IDF Vectorizer)
   "Lieferschein Manitowoc GmbH" → [0.5, 0.3, ..., 0.1]

2. LogisticRegression vorhersagen
   [0.5, 0.3, ..., 0.1] → Wahrscheinlichkeit für jeden Lieferant
   "Manitowoc": 0.95 ✅
   "Caterpillar": 0.03
   "Andere": 0.02

3. Höchste Wahrscheinlichkeit gewinnt
   → Lieferant = "Manitowoc"
```

**Warum TF-IDF + LogisticRegression?**
- ✅ Schnell (< 1ms pro Vorhersage)
- ✅ Einfach zu trainieren (braucht wenige Samples)
- ✅ Interpretierbar (welche Wörter → welcher Lieferant)
- ✅ Robust gegen Overfitting

**Alternativen (später):**
- 🟡 Transformer-Modelle (BERT) - besser, aber langsamer
- 🟡 Neuronale Netze (LSTM) - brauchen viele Daten

---

## 🧪 LayoutLMv3 Fine-Tuning (Template)

Docaro enthaelt jetzt ein Template fuer LayoutLMv3:
- Datensatz-Build: `ml/training/build_layoutlmv3_dataset.py`
- Training: `ml/training/train_layoutlmv3_template.py`

Empfohlener Pfad:
1. Realen Layout-Datensatz aus PDFs erstellen (Worte + echte Bounding-Boxes + Seitenbild)
2. LayoutLMv3 auf diesem Datensatz trainieren

Fallback:
- Wenn kein Layout-Datensatz vorhanden ist, trainiert das Script weiterhin auf
  `ground_truth.jsonl` mit synthetischen Boxes.

### Installation (optional)

```bash
/opt/Docaro/.venv/bin/pip install -r /opt/Docaro/requirements-layoutlmv3.txt
```

### 1) Layout-Datensatz bauen (Supplier)

```bash
cd /opt/Docaro
/opt/Docaro/.venv/bin/python ml/training/build_layoutlmv3_dataset.py \
  --source-dir data/fertig \
  --output-jsonl artifacts/layoutlmv3/dataset_supplier.jsonl \
  --images-dir artifacts/layoutlmv3/images \
  --label-field supplier \
  --max-docs 200 \
  --ocr-fallback
```

### 2) Training starten (Supplier-Klassifikation)

```bash
/opt/Docaro/.venv/bin/python ml/training/train_layoutlmv3_template.py \
  --layout-input artifacts/layoutlmv3/dataset_supplier.jsonl \
  --label-field supplier \
  --output-dir artifacts/layoutlmv3/supplier \
  --epochs 3 \
  --batch-size 4
```

### Fallback-Training (ohne Layout-Datensatz)

```bash
/opt/Docaro/.venv/bin/python ml/training/train_layoutlmv3_template.py \
  --input data/ml/ground_truth.jsonl \
  --label-field supplier \
  --output-dir artifacts/layoutlmv3/supplier_text_fallback
```

### Andere Label-Felder

```bash
# Dokumenttyp
/opt/Docaro/.venv/bin/python ml/training/train_layoutlmv3_template.py --label-field doc_type

# Dokumentnummer
/opt/Docaro/.venv/bin/python ml/training/train_layoutlmv3_template.py --label-field doc_number
```

### Outputs

- `artifacts/layoutlmv3/<task>/model/` (HF Modell + Processor)
- `artifacts/layoutlmv3/<task>/metrics.json`
- `artifacts/layoutlmv3/<task>/label_map.json`

---

## 🚀 **Performance optimieren**

### **Problem: Wenige Trainingsdaten**

**Lösung:**
```python
# Data Augmentation: Variationen erzeugen
"Lieferschein Manitowoc GmbH"
→ "Manitowoc GmbH - Lieferschein"
→ "Lieferschein Manitowoc"
→ "Manitowoc Lieferschein"

# Modell sieht mehr Variationen, wird robuster
```

### **Problem: Neue Lieferanten**

**Lösung:**
```python
# Few-Shot Learning: Nur 2-3 Beispiele nötig
# Training nutzt automatisch verwandte Lieferanten
"Neuer Lieferant Siemens"
→ System vergleicht mit ähnlichen Lieferanten
→ Neue Kategorie wird schnell gelernt
```

---

## ❓ **Häufige Fragen**

### Q: Warum dauert Training nur 1 Sekunde?

A: Mit nur 6-12 Samples ist TF-IDF sehr schnell. Bei 10.000+ Samples würde es längerer werden.

### Q: Verliere ich alte Modelle?

A: Nein! MLflow speichert alle Versionen. Du kannst zu älteren zurück, falls neue Modell schlechter ist.

### Q: Funktioniert Training mit nur 2-3 Korrektionen?

A: Default ist min_corrections=10. Mit <10 skipped Training. Du kannst ändern, aber <5 ist unreliabel.

### Q: Kann ich Modell manuell trainieren?

A: Ja!
```bash
python3 -c "from ml.retrain_scheduler import RetrainScheduler; from config import Config; scheduler = RetrainScheduler(Config().DATA_DIR / 'ml' / 'ground_truth.jsonl'); scheduler.train_supplier_model()"
```

### Q: Wie überprüfe ich Training-Qualität?

A: Check Logs + Metriken:
```bash
# Logs
journalctl -u docaro-ml-scheduler -n 100

# SQLite-Metriken
sqlite3 /opt/Docaro/data/ml/mlflow.db "SELECT params.value FROM params WHERE key='accuracy';"
```

---

## 🎯 **Nächste Schritte für bessere Genauigkeit**

1. **Sammle 50+ Korrektionen** pro Lieferant
2. **Training werden automatisch besser** (exponentielles Lernen)
3. **Bei 1000+ Scans:** Erwäge Transformer-Modelle (BERT)
4. **Bei Multi-Page-Docs:** Nutze Docling (später auf größerem Server)

---

**Dein System lernt automatisch mit jedem Scan! 🚀**
