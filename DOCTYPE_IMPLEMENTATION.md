# DocType Classification - Implementierung

## Übersicht

Die Dokumenttyp-Klassifikation wurde vollständig implementiert. Sie erkennt automatisch:
- **RECHNUNG**
- **LIEFERSCHEIN**
- **ÜBERNAHMESCHEIN**
- **KOMMISSIONIERLISTE**
- **SONSTIGES** (Fallback)

## Geänderte Dateien

### 1. `core/doctype_classifier.py` (neu/ersetzt)
**Hauptklasse für DocType-Klassifikation**

```python
@dataclass
class DocTypeResult:
    doc_type: str
    confidence: float
    evidence: List[str]  # Top-5 gefundene Keywords

class DocTypeClassifier:
    # Keyword-basierte Klassifikation
    # Stark (0.25 Punkte): "rechnung", "lieferschein", "uebernahmeschein", etc.
    # Unterstützend (0.10-0.12 Punkte): "netto", "brutto", "versand", etc.
    # Negativ (-0.15 Punkte): "lieferschein" bei RECHNUNG, "rechnung" bei LIEFERSCHEIN
    
    def classify_doc_type(text, supplier_canonical=None) -> DocTypeResult:
        # Confidence = min(0.99, best_score + (best_score - second_best) * 0.5)
        # Threshold: 0.60 für eindeutige Zuordnung
```

**Features:**
- Text-Normalisierung (lowercase, Umlaute → ae/oe/ue, Whitespace-Kollaps)
- Supplier-Hints (z.B. Manitowoc → +0.10 für RECHNUNG)
- Confidence-Berechnung mit Margin-Bonus
- Top-5 Evidence-Keywords

### 2. `core/extractor.py`
**Integration in OCR-Pipeline**

```python
# NEU: Import
from core.doctype_classifier import classify_doc_type

# GEÄNDERT: Nach OCR/Text-Extraktion (Zeile ~2052)
combined_text = "\n".join([t for t in (textlayer_text, ocr_text) if t])

# DocType-Klassifikation
if classify_doc_type is not None:
    doctype_result = classify_doc_type(combined_text, supplier_canonical)
    doc_type = doctype_result.doc_type
    doc_type_confidence = doctype_result.confidence
    doc_type_evidence = ", ".join(doctype_result.evidence[:3])

result["doc_type"] = doc_type
result["doc_type_confidence"] = f"{doc_type_confidence:.2f}"
result["doc_type_evidence"] = doc_type_evidence

# GEÄNDERT: DocType an extract_doc_number übergeben
doc_result = extract_doc_number(combined_text, supplier_canonical, doc_type)
```

### 3. `core/doc_number_extractor.py`
**DocType-Aware Field Prioritization**

```python
# GEÄNDERT: extract_doc_number() nimmt jetzt doc_type
def extract_doc_number(
    text: str,
    supplier_canonical: Optional[str] = None,
    doc_type: Optional[str] = None  # NEU
) -> DocNumberResult

# NEU: _reorder_fields_by_doctype()
def _reorder_fields_by_doctype(fields: List[str], doc_type: str) -> List[str]:
    """
    Priorisiert Felder basierend auf Dokumenttyp:
    - RECHNUNG → "Rechnungsnummer", "Invoice No" zuerst
    - LIEFERSCHEIN → "Lieferschein-Nr", "Delivery Note" zuerst
    - ÜBERNAHMESCHEIN → "Übernahmeschein-Nr" zuerst
    - KOMMISSIONIERLISTE → "Kommissionierauftrag", "Picking List" zuerst
    """
```

**Effekt:** Wenn doc_type="RECHNUNG", wird "Rechnungsnummer" vor "Lieferschein-Nr" gesucht.

### 4. `app/templates/index.html`
**UI-Integration**

```html
<!-- GEÄNDERT: Neue Spalte "Dokumenttyp" -->
<thead>
  <tr>
    <th>Datei</th>
    <th>Lieferant</th>
    <th>Datum</th>
    <th>Dokumenttyp</th>  <!-- NEU -->
    <th>Status</th>
    <th>Aktionen</th>
  </tr>
</thead>

<!-- NEU: DocType Badge mit Tooltip -->
<td data-field="doc_type">
  {% if item.doc_type %}
    {% set doc_conf = item.doc_type_confidence|float %}
    <span class="badge badge-{{ item.doc_type|lower }}" 
          title="Confidence: {{ '%.2f'|format(doc_conf) }}, Keywords: {{ item.doc_type_evidence }}">
      {{ item.doc_type }}
    </span>
  {% else %}
    <span class="muted">-</span>
  {% endif %}
</td>
```

### 5. `app/static/style.css`
**DocType Badge Styling**

```css
/* DocType Badges */
.badge {
  display: inline-flex;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  cursor: help;
}

.badge-rechnung { background: #ffe5e5; color: #b30000; }
.badge-lieferschein { background: #e5f0ff; color: #0047b3; }
.badge-übernahmeschein { background: #f0e5ff; color: #6b00b3; }
.badge-kommissionierliste { background: #fff5e5; color: #b37400; }
.badge-sonstiges { background: #f0f0f0; color: #666; }
```

### 6. `core/test_doctype_classifier.py` (neu)
**Unit Tests**

```python
def test_rechnung():
    text = "Rechnung\nRechnungsnummer: INV-12345\nIBAN: DE..."
    result = classify_doc_type(text)
    assert result.doc_type == "RECHNUNG"
    assert result.confidence >= 0.70

def test_lieferschein():
    text = "Lieferschein\nLieferschein-Nr: LS-9999..."
    ...

# + test_uebernahmeschein()
# + test_kommissionierliste()
# + test_sonstiges()
# + test_rechnung_mit_supplier_hint()
```

**Testergebnisse:**
```
✓ RECHNUNG: confidence=0.99
✓ LIEFERSCHEIN: confidence=0.99
✓ ÜBERNAHMESCHEIN: confidence=0.99
✓ KOMMISSIONIERLISTE: confidence=0.99
✓ SONSTIGES: confidence=0.10
✓ RECHNUNG (Manitowoc hint): confidence=0.99
✅ Alle Tests erfolgreich!
```

## Setup & Tests

### 1. Requirements
Keine neuen Dependencies! Nutzt nur Python Standard Library + vorhandene OCR-Tools.

### 2. Tests ausführen
```powershell
cd d:\Docaro
$env:PYTHONPATH="d:\Docaro"
python core\test_doctype_classifier.py
```

### 3. Manueller Test
```powershell
# App starten
.\start_app.ps1

# Browser: http://localhost:5000
# 1. PDF hochladen
# 2. Dokumentliste prüfen: "Dokumenttyp"-Spalte sichtbar?
# 3. Badge hover: Confidence + Keywords angezeigt?
# 4. Dateiname korrekt (nutzt doc_type für Nummern-Extraktion)?
```

## Workflow-Integration

### OCR-Pipeline
```
PDF Upload
  ↓
Textlayer-Extraktion (pdftotext)
  ↓
OCR (Tesseract/PaddleOCR)
  ↓
combined_text = textlayer + ocr
  ↓
Supplier Canonicalization  ← bereits vorhanden
  ↓
**DocType Classification** ← NEU
  ↓
Doc Number Extraction ← nutzt jetzt doc_type
  ↓
Filename: <Supplier>_<Date>_<DocNumber>.pdf
```

### DocType → Filename
**Beispiel:** PDF mit Text "Rechnung\nRechnungsnummer: RE-12345\nLieferschein-Nr: LS-99999"

**Ohne DocType:**
- Findet beide Nummern, nimmt erste: "LS-99999" (falsch)

**Mit DocType:**
1. DocType = "RECHNUNG" (Confidence 0.95)
2. extract_doc_number() priorisiert "Rechnungsnummer"-Felder
3. Findet "RE-12345" zuerst → korrekt!

## Datenmodell

### result dict (in extractor.py)
```python
result = {
    "supplier": "WM",
    "supplier_canonical": "WM",
    "supplier_confidence": "0.98",
    "date": "2026-01-15",
    "date_confidence": "0.95",
    "doc_number": "RE-12345",
    "doc_number_confidence": "high",
    "doc_type": "RECHNUNG",              # NEU
    "doc_type_confidence": "0.95",        # NEU
    "doc_type_evidence": "rechnung, rechnungsnummer, iban",  # NEU
    ...
}
```

### Session-Speicherung
`data/session_files.json` speichert result dict → doc_type automatisch enthalten.

## Keyword-Referenz

### RECHNUNG
**Stark (0.25):** rechnung, invoice, rechnungsnummer, rechnungs-nr, invoice number, faktura, zahlungsziel, payment terms, iban, bic, bankverbindung, mehrwertsteuer, mwst

**Unterstützend (0.10):** betrag, netto, brutto, summe, total, gesamt, steuer, tax, fällig

**Negativ (-0.15):** lieferschein, delivery note, uebernahmeschein

### LIEFERSCHEIN
**Stark (0.25):** lieferschein, delivery note, lieferschein-nr, lieferdatum, delivery date, versand, shipment, warenausgang, lieferung

**Unterstützend (0.10):** versandadresse, empfänger, anzahl, menge, position, artikel, ware, geliefert

**Negativ (-0.15):** rechnung, invoice, iban

### ÜBERNAHMESCHEIN
**Stark (0.25):** uebernahmeschein, übernahmeschein, entsorgung, abfall, recycling, container, tonne, mulde, entsorgungsnachweis, entsorgungsbescheinigung, abfallart, abfallschluessel, avv-nr, avv

**Unterstützend (0.12):** kilogramm, kg, tonnen, kubikmeter, m3, abholung, anlieferung, standort, deponiert

### KOMMISSIONIERLISTE
**Stark (0.25):** kommissionierliste, picking list, kommissionierung, pickliste, entnahmeliste, auftragsliste, kommissionierauftrag, picking, kommission

**Unterstützend (0.10):** lager, lagerplatz, regal, fach, position, entnehmen, bereitstellen

## Confidence-Formel

```python
confidence = min(0.99, best_score + (best_score - second_best) * 0.5)

# Threshold: 0.60 (unter 0.60 → SONSTIGES)
```

**Beispiel:**
- best_score (RECHNUNG) = 0.75
- second_best (LIEFERSCHEIN) = 0.20
- confidence = 0.75 + (0.75 - 0.20) * 0.5 = 0.75 + 0.275 = **1.025** → min(0.99, 1.025) = **0.99**

## Edge Cases

### 1. Hybride Dokumente (Rechnung + Lieferschein)
→ Höchster Score gewinnt. Wenn ähnliche Scores: Fallback SONSTIGES (unter Threshold 0.60)

### 2. Supplier ohne klare Keywords (Manitowoc)
→ Supplier-Hint +0.10 für RECHNUNG

### 3. Falsche OCR (Gibberish)
→ SONSTIGES (keine Keywords → low score)

### 4. Mehrsprachige Dokumente
→ Keywords enthalten englische Varianten (invoice, delivery note, picking list)

## Nächste Schritte

### Optional - Erweiterte Features:
1. **DB-Persistierung:** doc_type in Datenbank-Tabelle speichern (aktuell nur in session_files.json)
2. **Review-UI:** DocType manuell korrigieren (analog zu Supplier/Datum)
3. **Statistics:** DocType-Verteilung über Zeit (Dashboard)
4. **ML-Upgrade:** TF-IDF oder Transformer-basierte Klassifikation
5. **Multi-Label:** Dokument kann mehrere Typen haben (RECHNUNG + LIEFERSCHEIN)

### Maintenance:
- Neue Dokumenttypen: Keywords in `doctype_classifier.py` ergänzen
- Supplier-Hints: `_apply_supplier_hints()` erweitern
- Threshold anpassen: `min_confidence` Parameter

## Kompatibilität

✅ **Keine Breaking Changes:**
- Extractor.py: Fallback wenn `classify_doc_type = None`
- DocNumberExtractor: `doc_type` Parameter optional
- UI: DocType-Spalte zeigt "-" wenn nicht vorhanden
- Session-Files: Alte Einträge ohne doc_type funktionieren weiter

✅ **Keine neuen Dependencies**

✅ **Keine DB-Migration nötig** (result dict dynamisch)

## Difflog

```diff
# core/doctype_classifier.py (NEU)
+ DocTypeResult dataclass
+ DocTypeClassifier mit Keyword-Dictionaries
+ classify_doc_type() Funktion

# core/extractor.py
+ from core.doctype_classifier import classify_doc_type
+ doctype_result = classify_doc_type(combined_text, supplier_canonical)
+ result["doc_type"] / result["doc_type_confidence"] / result["doc_type_evidence"]
+ doc_result = extract_doc_number(..., doc_type)  # Parameter hinzugefügt

# core/doc_number_extractor.py
+ doc_type: Optional[str] Parameter in extract_doc_number()
+ _reorder_fields_by_doctype() Methode
+ Aufruf in _extract_supplier_specific()

# app/templates/index.html
+ <th>Dokumenttyp</th> Spalte
+ <td data-field="doc_type"> mit Badge + Tooltip

# app/static/style.css
+ .badge / .badge-rechnung / .badge-lieferschein / etc.

# core/test_doctype_classifier.py (NEU)
+ 6 Test-Funktionen für alle DocTypes
```

---

**Status:** ✅ **Vollständig implementiert und getestet**
