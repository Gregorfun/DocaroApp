# Review Queue Feature - Setup & Testing

## ✅ Implementierte Dateien

### Core Service
- **core/review_service.py** (470 Zeilen) - Neue Datei
  - `DocumentStatus`: Status-Enum (NEW, EXTRACTED, NEEDS_REVIEW, READY, FINALIZED, ERROR)
  - `ReviewReasonCode`: 9 Reason Codes für Gate-Failures
  - `decide_review_status()`: Gate-Check-Logik (4 Gates: Supplier, Date, DocType, DocNumber)
  - `finalize_document()`: Rename + AutoSort + Unique Suffix Handling
  - `save_correction()`: Audit Trail (corrections.json)
  - `save_ground_truth_sample()`: ML Training Samples (ground_truth.jsonl)
  - `load_review_settings()`, `save_review_settings()`: Settings Management

### Pipeline Integration
- **core/extractor.py** (Modifiziert)
  - Zeilen 48-51: Import `decide_review_status, load_review_settings, DocumentStatus`
  - Zeilen 2124-2135: Review-Status-Berechnung nach allen Extraktionen
  - Speichert `review_status` und `review_reasons` in result dict

### Web UI
- **app/review_routes.py** (Neu erstellt - 330 Zeilen)
  - `GET /review/` - Review Queue Liste
  - `GET /review/<file_id>` - Detail Seite mit Korrekturformular
  - `GET /review/api/queue` - API: Review Queue (JSON)
  - `GET /review/api/<file_id>` - API: Dokument Detail
  - `POST /review/api/<file_id>/correct` - API: Korrektur speichern + optional finalisieren
  - `POST /review/api/<file_id>/finalize` - API: Dokument finalisieren
  - `GET /review/api/settings` - API: Gate Settings abrufen
  - `POST /review/api/settings` - API: Gate Settings aktualisieren

- **app/templates/review_queue.html** (Neu)
  - Tabelle mit allen NEEDS_REVIEW + READY Dokumenten
  - Spalten: Preview, Supplier, Datum, DocType, DocNumber, Status, Gründe, Aktionen
  - Ampel-UI: Grün (≥ Gate), Orange (0.50..Gate), Rot (< 0.50)

- **app/templates/review_detail.html** (Neu)
  - PDF Preview (links)
  - Korrekturformular (rechts) mit Dropdowns/Date-Picker
  - 2 Submit-Buttons: "Speichern & READY" oder "Speichern & Finalisieren"
  - Confidence Badges für alle 4 Felder

### Settings
- **data/settings.json** (Erweitert - manuell zu prüfen)
  - Neue Felder:
    ```json
    {
      "gate_supplier_min": 0.80,
      "gate_date_min": 0.80,
      "gate_doc_type_min": 0.70,
      "gate_doc_number_min": 0.80,
      "auto_finalize_enabled": false,
      "autosort_enabled": false,
      "autosort_base_dir": "."
    }
    ```

### Data Files (werden automatisch erstellt)
- **data/corrections.json** - Audit Trail für manuelle Korrekturen
- **data/ml/ground_truth.jsonl** - ML Training Samples

---

## 📋 Setup-Schritte

### 1. Verzeichnisse erstellen
```powershell
# ML Ground Truth Verzeichnis
New-Item -ItemType Directory -Path "d:\Docaro\data\ml" -Force
```

### 2. settings.json erweitern
Öffne `data/settings.json` und füge die Review-Settings hinzu (falls nicht vorhanden):
```json
{
  "...existing settings...",
  "gate_supplier_min": 0.80,
  "gate_date_min": 0.80,
  "gate_doc_type_min": 0.70,
  "gate_doc_number_min": 0.80,
  "auto_finalize_enabled": false,
  "autosort_enabled": false,
  "autosort_base_dir": "d:/Docaro/daten_fertig"
}
```

### 3. Blueprint Registration (bereits erledigt)
In `app/app.py` ist der Blueprint bereits registriert:
```python
from review_routes import review_bp
app.register_blueprint(review_bp)
```

### 4. Server neu starten
```powershell
# App stoppen (falls läuft) mit Strg+C
# Dann neu starten:
python app/app.py
```

---

## 🧪 Manuelle Tests

### Test 1: Upload mit niedrigen Confidences
**Ziel**: Dokument landet in NEEDS_REVIEW Status

**Schritte**:
1. Upload ein PDF mit unsicheren Extraktionen (z.B. schlechte Qualität)
2. Prüfe in Logs/Upload-Response: `review_status: "NEEDS_REVIEW"`
3. Prüfe `review_reasons`: z.B. `["SUPPLIER_CONF_LOW", "DATE_CONF_LOW"]`

**Erwartung**:
- Status = NEEDS_REVIEW
- Reasons enthalten alle fehlgeschlagenen Gates

### Test 2: Review Queue UI
**Ziel**: Review Queue zeigt NEEDS_REVIEW Dokumente

**Schritte**:
1. Öffne http://localhost:5000/review
2. Prüfe: Dokument aus Test 1 wird angezeigt
3. Prüfe: Ampel-Badges zeigen Rot/Orange für niedrige Confidences

**Erwartung**:
- Tabelle zeigt alle NEEDS_REVIEW Dokumente
- Confidence Badges:
  - Grün (≥ Gate Threshold)
  - Orange (0.50 bis Gate)
  - Rot (< 0.50)
- Review-Button führt zu Detail-Seite

### Test 3: Korrektur & READY
**Ziel**: Manuelle Korrektur setzt Status auf READY

**Schritte**:
1. Klicke "Review" bei einem NEEDS_REVIEW Dokument
2. Korrigiere Felder (Supplier, Datum, DocType, DocNumber)
3. Klicke "Speichern & als READY markieren"
4. Warte 2 Sekunden (Auto-Redirect zur Queue)
5. Prüfe: Dokument nicht mehr in Queue (oder Status READY)

**Erwartung**:
- Erfolgsmeldung "✅ Gespeichert. Status: READY"
- data/corrections.json enthält neuen Entry mit original/corrected values
- data/ml/ground_truth.jsonl enthält neues Sample
- session_files.json: Dokument hat `review_status: "READY"`

### Test 4: Finalisierung
**Ziel**: Finalisierung renamed Datei + AutoSort

**Schritte**:
1. Review ein Dokument mit korrigierten Werten
2. Klicke "Speichern & Finalisieren"
3. Prüfe Erfolgsmeldung mit finalized_path
4. Prüfe Filesystem:
   - Datei im Zielverzeichnis vorhanden
   - Filename-Format: `<Supplier>_<YYYY-MM-DD>_<DocNumber>.pdf`
   - AutoSort: `<Base>/<Supplier>/<YYYY-MM>/` Struktur

**Erwartung**:
- Erfolgsmeldung "✅ Erfolgreich finalisiert: [Pfad]"
- Datei am Zielpfad vorhanden
- session_files.json: `review_status: "FINALIZED"`, `finalized_path` gesetzt
- Original-Datei verschoben (nicht kopiert, da mode="move")

### Test 5: Gate Threshold Anpassung
**Ziel**: Settings API funktioniert

**Schritte**:
1. GET /review/api/settings
2. Prüfe: JSON enthält alle gate_* Felder
3. POST /review/api/settings mit neuen Werten (z.B. gate_supplier_min: 0.70)
4. GET /review/api/settings erneut
5. Prüfe: Wert wurde gespeichert

**Erwartung**:
- API liefert/speichert alle Settings korrekt
- settings.json wird aktualisiert

### Test 6: Auto-Finalize (wenn enabled)
**Ziel**: Dokumente mit hohen Confidences werden automatisch finalisiert

**Schritte**:
1. Setze in settings.json: `"auto_finalize_enabled": true, "autosort_enabled": true`
2. Server neu starten
3. Upload ein PDF mit hohen Confidences (≥ alle Gates)
4. Prüfe Logs/Response: `review_status: "FINALIZED"` (nicht READY!)
5. Prüfe Filesystem: Datei bereits im Zielverzeichnis

**Erwartung**:
- Dokument überspringt Review Queue
- Status direkt FINALIZED
- Datei automatisch renamed + AutoSorted

---

## 🐛 Troubleshooting

### Problem: Import Error "review_service not found"
**Lösung**: Prüfe dass `core/review_service.py` existiert und keine Syntax-Fehler hat
```powershell
python -c "from core.review_service import decide_review_status; print('OK')"
```

### Problem: Review Queue zeigt keine Dokumente
**Ursachen**:
1. Keine Dokumente mit NEEDS_REVIEW Status → Upload mit niedrigen Confidences testen
2. session_files.json fehlt → App einmal Upload machen
3. Falscher Filter in Template → Prüfe review_queue.html Zeile 15

### Problem: Finalize schlägt fehl "Source file not found"
**Ursachen**:
1. `doc["path"]` zeigt auf nicht-existierende Datei
2. Prüfe `doc["original_path"]` Fallback
3. Prüfe dass Upload-Dateien in `data/tmp/` liegen

### Problem: corrections.json oder ground_truth.jsonl werden nicht erstellt
**Ursachen**:
1. Verzeichnis `data/ml/` fehlt → Setup Schritt 1 ausführen
2. Keine Schreibrechte → Prüfe File Permissions
3. Exception in save_correction() → Prüfe Logs für Fehlermeldungen

---

## 📊 Datenstruktur

### session_files.json - Erweiterung
Jedes Dokument hat neue Felder:
```json
{
  "file_id": "abc123",
  "review_status": "NEEDS_REVIEW",
  "review_reasons": ["SUPPLIER_CONF_LOW", "DATE_CONF_LOW"],
  "finalized_path": null,
  "supplier_confidence": 0.65,
  "date_confidence": 0.58,
  "doc_type_confidence": 0.72,
  "doc_number_confidence": 0.83
}
```

### corrections.json - Format
```json
[
  {
    "timestamp": "2025-01-15T10:30:00Z",
    "doc_id": "abc123",
    "user": "admin@docaro.local",
    "original": {
      "supplier_canonical": "Unklar GmbH",
      "doc_type": "Rechnung",
      "date": "2025-01-10",
      "doc_number": "RE-123"
    },
    "corrected": {
      "supplier_canonical": "Musterfirma GmbH",
      "doc_type": "Lieferschein",
      "date": "2025-01-11",
      "doc_number": "LS-456"
    }
  }
]
```

### ground_truth.jsonl - Format
```jsonl
{"doc_id": "abc123", "text": "Full OCR text...", "labels": {"supplier_canonical": "Musterfirma GmbH", "doc_type": "Lieferschein", "date": "2025-01-11", "doc_number": "LS-456"}}
{"doc_id": "def456", "text": "Another document...", "labels": {...}}
```

---

## 🎯 Nächste Schritte (Optional)

### 1. Settings UI erweitern
Füge in `app/templates/settings.html` Slider für Gate Thresholds hinzu:
- Range-Slider für gate_supplier_min (0.0 - 1.0)
- Checkbox für auto_finalize_enabled
- Checkbox für autosort_enabled

### 2. Unit Tests
Erstelle `core/test_review_service.py`:
- Test decide_review_status() mit verschiedenen Confidences
- Test finalize_document() Filename Building
- Test save_correction() / save_ground_truth_sample()

### 3. Review Queue Badge in Navigation
Füge in `app/templates/base.html` Navigation Badge mit Count hinzu:
```html
<a href="/review" class="nav-link">
  Review Queue <span class="badge bg-danger">{{ review_count }}</span>
</a>
```

### 4. Dashboard Widget
Zeige auf Dashboard:
- Anzahl NEEDS_REVIEW Dokumente
- Anzahl FINALIZED heute
- Durchschnittliche Confidence pro Feld

---

## 📝 Zusammenfassung

**Neue Features**:
✅ Confidence-Gates für 4 Felder (Supplier, Date, DocType, DocNumber)
✅ Status-Workflow (NEW → EXTRACTED → NEEDS_REVIEW → READY → FINALIZED)
✅ Review Queue UI mit Ampel-Farbcodierung
✅ 1-Klick-Korrektur + Finalize Workflow
✅ ML Feedback (corrections.json + ground_truth.jsonl)
✅ Auto-Finalize bei hohen Confidences (opt-in)
✅ API Endpoints für alle Review-Operationen

**Geänderte Dateien**:
- core/review_service.py (NEU)
- core/extractor.py (MODIFIZIERT - 2 kleine Änderungen)
- app/review_routes.py (NEU ERSTELLT)
- app/templates/review_queue.html (NEU)
- app/templates/review_detail.html (NEU)

**Setup-Aufwand**: ~5 Minuten (Verzeichnis erstellen, settings.json erweitern, Server restart)
