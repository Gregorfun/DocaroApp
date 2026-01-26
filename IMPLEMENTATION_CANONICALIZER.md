# Supplier Canonicalizer - Implementation

## Implementierte Features

### 1. Alias-Konfiguration (config/supplier_aliases.yaml)
Supplier-Mappings für 9 Firmen mit kanonischen Namen und Varianten:

- **WM**: W+M, W & M, WM Fahrzeugteile, WM SE, etc.
- **Ortojohann+Kraft**: Ortojohann, OK, Ortojohann & Kraft, etc.
- **PIRTEK**: PIRTEK, Pirtek (case-insensitive)
- **FUCHS**: FUCHS LUBRICANTS, Fuchs Schmierstoffe, FUCHS OIL, etc.
- **Vergölst**: Vergolst, Vergoelst, Vergölst Filiale, etc.
- **WFI**: Wireless Funk, Wireless Funk- und Informationstechnik, etc.
- **LKQ PV AUTOMOTIVE**: LKQ, LKQ PV, PV Automotive, etc.
- **Hofmeister & Meincke**: Hofmeister, Meincke, Hofmeister+Meincke, etc.
- **Franz Bracht**: Bracht, Franz Bracht Kran-Vermietung, Bracht Autokrane, etc.

Features:
- **Exact Alias Matching**: String-basiertes Matching (case-insensitive)
- **Regex Pattern Matching**: Flexible Pattern für OCR-Varianten
- **Context Patterns**: Kontext-abhängige Matches (z.B. "Hofmeister" nur wenn "Meincke" auch vorkommt)
- **Normalisierung**: Umlaut-Varianten (ö↔oe), Sonderzeichen-Filterung, Whitespace-Normalisierung

### 2. Canonicalizer-Modul (core/supplier_canonicalizer.py)
- `canonicalize_supplier(raw_text, full_ocr_text)` → SupplierMatch
- **SupplierMatch** dataclass:
  - `canonical_name`: Kanonischer Supplier-Name
  - `confidence`: Matching-Confidence (0.60 - 1.00)
  - `matched_alias`: Gematchtes Alias
  - `match_type`: "exact", "regex", "substring", "context"

Matching-Strategie (in Reihenfolge):
1. **Exakte Alias-Matches** (Confidence: 0.95)
2. **Regex-Pattern-Matches** (Confidence: 0.90)
3. **Kontext-basierte Matches** (Confidence: 0.75)

### 3. Integration in extractor.py
- Nach bestehender Supplier-Erkennung (`detect_supplier()`) wird Canonicalizer aufgerufen
- Speichert in result dict:
  - `supplier_raw`: Original erkannter Name (z.B. "Vergolst", "LKQ PV")
  - `supplier_canonical`: Kanonischer Name (z.B. "Vergölst", "LKQ PV AUTOMOTIVE")
  - `supplier_matched_alias`: Gematchtes Alias
  - `supplier_confidence`: Aktualisiert wenn Canonicalizer höher
- **Dokumentnummern-Extraktion** nutzt `supplier_canonical`
- **Dateinamen-Builder** nutzt `supplier_canonical`

### 4. Synchronisation mit doc_number_extractor
- supplier_field_aliases.yaml angepasst: Keys nutzen jetzt canonical names
  - "OK" → "Ortojohann+Kraft"
  - "VERGOELST" → "Vergölst"
  - "LKQ PV AUTOMOTIVE" (vorher schon korrekt)
  - "HOFMEISTER & MEINCKE" → "Hofmeister & Meincke"

## Geänderte Dateien

### Neu erstellt:
1. **config/supplier_aliases.yaml** - Supplier-Alias-Mappings mit Regex-Patterns
2. **core/supplier_canonicalizer.py** - Canonicalizer-Logik
3. **core/test_supplier_canonicalizer.py** - Unit-Tests

### Modifiziert:
1. **core/extractor.py**
   - Import: `from core.supplier_canonicalizer import canonicalize_supplier`
   - `process_pdf()`: Canonicalization nach Supplier-Erkennung (Textlayer + OCR)
   - Result dict erweitert: `supplier_raw`, `supplier_canonical`, `supplier_matched_alias`
   - `build_new_filename()`: Nutzt `supplier_canonical` statt raw supplier
2. **config/supplier_field_aliases.yaml**
   - Keys angepasst an canonical names aus supplier_aliases.yaml

## Setup-Schritte

### 1. Config validieren
```powershell
python -c "from core.supplier_canonicalizer import SupplierCanonicalizer; c=SupplierCanonicalizer(); print(f'Loaded: {len(c.suppliers)} suppliers'); print('Canonical names:', c.list_all_canonical_names())"
```
Erwartete Ausgabe:
```
Loaded: 9 suppliers
Canonical names: ['WM', 'Ortojohann+Kraft', 'PIRTEK', 'FUCHS', 'Vergölst', 'WFI', 'LKQ PV AUTOMOTIVE', 'Hofmeister & Meincke', 'Franz Bracht']
```

### 2. Tests ausführen
```powershell
# Unit-Tests
python core/test_supplier_canonicalizer.py

# Schnelltest
python -c "from core.supplier_canonicalizer import canonicalize_supplier; tests=[('Vergolst','Vergölst'),('LKQ PV','LKQ PV AUTOMOTIVE'),('W+M','WM')]; [print(f'{t}: {canonicalize_supplier(t).canonical_name if canonicalize_supplier(t) else \"None\"} -> {e}') for t,e in tests]"
```

## Manuelle Tests mit PDFs

### Test-Szenarien

1. **Vergölst-Varianten**: Upload PDF mit "Vergolst" (ohne Umlaut)
   - Erwartete Ausgabe: `supplier_canonical = "Vergölst"`
   - Dateiname: `Vergölst_2025-11-27_D018017955.pdf`

2. **LKQ-Varianten**: Upload PDF mit "LKQ PV Automotive GmbH"
   - Erwartete Ausgabe: `supplier_canonical = "LKQ PV AUTOMOTIVE"`
   - Dateiname: `LKQ_PV_AUTOMOTIVE_2025-11-25_3814300.pdf`

3. **WFI-Langform**: Upload PDF mit "Wireless Funk- und Informationstechnik"
   - Erwartete Ausgabe: `supplier_canonical = "WFI"`
   - Dateiname: `WFI_2025-11-26_LS20250982.pdf`

4. **FUCHS-Varianten**: Upload PDF mit "FUCHS LUBRICANTS GERMANY"
   - Erwartete Ausgabe: `supplier_canonical = "FUCHS"`
   - Dateiname: `FUCHS_2025-11-18_226267189.pdf`

5. **WM-Kurzformen**: Upload PDF mit "W+M Fahrzeugteile"
   - Erwartete Ausgabe: `supplier_canonical = "WM"`
   - Dateiname: `WM_2025-11-26_12345678.pdf`

### Verifikation nach Upload

Nach Upload eines PDFs:

1. **Check Logs** (`data/logs/`):
   ```json
   {
     "supplier_raw": "Vergolst",
     "supplier_canonical": "Vergölst",
     "supplier_matched_alias": "Vergolst",
     "supplier_confidence": "0.95"
   }
   ```

2. **Check Dateiname** in `daten_fertig/`:
   - Sollte canonical name enthalten (z.B. `Vergölst_...` statt `Vergolst_...`)

3. **Check Web-UI**:
   - "Lieferant erkannt: **Vergölst** (Alias: Vergolst)"
   - Dokumentnummer sollte korrekt extrahiert sein

## Troubleshooting

### Problem: Canonicalizer findet keinen Match
```powershell
# Debug-Output
python -c "from core.supplier_canonicalizer import canonicalize_supplier; r=canonicalize_supplier('Ihr Supplier', 'Volltext hier'); print(f'Result: {r.canonical_name if r else \"None\"}, Type: {r.match_type if r else \"None\"}')"
```

### Problem: Falscher canonical name
→ Config erweitern in `config/supplier_aliases.yaml`:
```yaml
suppliers:
  NEUER_SUPPLIER:
    canonical: "Neuer Supplier GmbH"
    aliases:
      - "Neuer"
      - "Neuer Supplier"
    regex_patterns:
      - "(?i)neuer\\s+supplier"
```

### Problem: Zu viele false positives
→ Context-Pattern hinzufügen:
```yaml
suppliers:
  SUPPLIER_X:
    context_patterns:
      "keyword": ["required_context1", "required_context2"]
```

### Problem: Umlaute nicht erkannt
→ Normalisierung prüfen in `config/supplier_aliases.yaml`:
```yaml
normalization:
  umlauts:
    ö: ["oe", "o"]
    ü: ["ue", "u"]
    ä: ["ae", "a"]
```

## Erweitere für neue Supplier

1. **Alias-Config erweitern** (`config/supplier_aliases.yaml`):
```yaml
suppliers:
  NEUER_SUPPLIER:
    canonical: "Neuer Supplier GmbH"
    aliases:
      - "Neuer Supplier"
      - "NS GmbH"
    regex_patterns:
      - "(?i)neuer.*supplier"
    domain_hints: ["neuer-supplier.de"]
```

2. **Doc-Number-Mapping hinzufügen** (`config/supplier_field_aliases.yaml`):
```yaml
suppliers:
  "Neuer Supplier GmbH":  # Muss canonical name sein!
    doc_number_fields:
      - "Belegnummer"
      - "Auftragsnr"
```

3. **Testen**:
```powershell
python -c "from core.supplier_canonicalizer import canonicalize_supplier; r=canonicalize_supplier('NS GmbH'); print(r.canonical_name if r else 'None')"
```

## Performance & Hinweise

- **Lazy Loading**: Canonicalizer-Instanz wird nur einmal geladen (globaler Cache)
- **Fallback**: Wenn Canonicalizer nicht verfügbar (z.B. PyYAML fehlt), nutzt System raw supplier name
- **Confidence Update**: Wenn Canonicalizer höhere Confidence liefert, wird sie übernommen
- **Logging**: Alle Canonicalization-Fehler werden als Warning geloggt (nicht fatal)
- **Backward Compatible**: Bestehende Supplier-Erkennung bleibt erhalten, Canonicalizer ist Add-on

## Test-Ergebnisse

Alle Tests bestanden ✅

```
======================================================================
SUPPLIER CANONICALIZER TEST
======================================================================
✓ OK   | Vergolst                                 -> Vergölst
✓ OK   | LKQ PV Automotive                        -> LKQ PV AUTOMOTIVE
✓ OK   | Wireless Funk- und Informationstechnik   -> WFI
✓ OK   | FUCHS LUBRICANTS GERMANY                 -> FUCHS
✓ OK   | W+M                                      -> WM
✓ OK   | WM Fahrzeugteile                         -> WM
✓ OK   | Ortojohann                               -> Ortojohann+Kraft
✓ OK   | PIRTEK                                   -> PIRTEK
✓ OK   | Pirtek                                   -> PIRTEK
✓ OK   | Franz Bracht                             -> Franz Bracht
✓ OK   | Bracht Autokrane                         -> Franz Bracht
======================================================================
Result: 11 passed, 0 failed
======================================================================
```

## Integration mit doc_number_extractor

Der Canonicalizer stellt sicher, dass die Dokumentnummern-Extraktion immer mit einheitlichen Supplier-Namen arbeitet:

**Vorher:**
- Supplier-Erkennung liefert "Vergolst" oder "LKQ PV" → doc_number_extractor findet kein Mapping

**Nachher:**
- Supplier-Erkennung liefert "Vergolst" → Canonicalizer → "Vergölst" → doc_number_extractor nutzt Mapping für "Vergölst" ✅
- Supplier-Erkennung liefert "LKQ PV" → Canonicalizer → "LKQ PV AUTOMOTIVE" → doc_number_extractor nutzt Mapping für "LKQ PV AUTOMOTIVE" ✅

## Dateinamen-Beispiele

Mit Canonicalizer:
- `Vergölst_2025-11-27_D018017955.pdf` (nicht "Vergolst")
- `LKQ_PV_AUTOMOTIVE_2025-11-25_3814300.pdf` (nicht "LKQ PV")
- `WFI_2025-11-26_LS20250982.pdf` (nicht "Wireless Funk...")
- `FUCHS_2025-11-18_226267189.pdf` (einheitlich, egal ob "Fuchs Lubricants" oder "FUCHS OIL")
- `WM_2025-11-26_12345678.pdf` (einheitlich, egal ob "W+M" oder "WM Fahrzeugteile")
