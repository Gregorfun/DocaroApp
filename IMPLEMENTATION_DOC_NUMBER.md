# Supplier-spezifische Dokumentnummern-Erkennung

## Implementierte Features

### 1. Konfiguration (config/supplier_field_aliases.yaml)
Supplier-spezifische Feldnamen-Mappings für 8 Firmen:
- **WM**: Auftrags-Nr, Auftragsnummer
- **OK (Ortojohann+Kraft)**: Rechnung, Rechnungsnummer, RE-, Ursprünglicher Auftrag
- **PIRTEK**: Arbeitsauftrag, Auftragsnummer
- **FUCHS**: Lieferschein, Nummer, Auftragsnummer
- **VERGOELST**: Belegnummer, Beleg-Nr
- **WFI**: Lieferscheinnr, Lieferschein Nr, LS
- **LKQ PV AUTOMOTIVE**: Lieferschein-Nr, Auftragsnummer
- **HOFMEISTER & MEINCKE**: Auftragsnr, Auftrags-Nr, Auftrag

### 2. Extraktion (core/doc_number_extractor.py)
- `extract_doc_number(text, supplier_canonical, doc_type)` → DocNumberResult
- Unterstützt alphanumerische, numerische und gemischte Formate:
  - Alphanumerisch: D018017955, LS20250982
  - Mit Bindestrichen: RE-2025-90879
  - Rein numerisch: 226267189, 3814300, 08625112402
- Filtert false positives:
  - Datumswerte (dd.mm.yyyy, yyyy-mm-dd)
  - PLZ (5-stellige Zahlen ohne Kontext)
  - IBAN, Telefonnummern, Beträge
- Confidence-Levels:
  - **high**: Keyword-Feldname direkt gematched
  - **medium**: Sekundäres Feld oder Fallback-Keyword
  - **low**: Generische Heuristik
  - **none**: Keine Nummer gefunden

### 3. Dateinamen-Builder (core/extractor.py)
- Format: `<Supplier>_<YYYY-MM-DD>_<DocNumber>.pdf`
- Fallback bei fehlender Nummer: `<Supplier>_<YYYY-MM-DD>_ohneNr_<HASH>.pdf`
  - Hash: 6-stelliger SHA1-Hash des PDF-Inhalts (deterministisch)
- Integration in `process_pdf()`:
  - Ruft `extract_doc_number()` nach supplier+date extraction auf
  - Speichert `doc_number`, `doc_number_source`, `doc_number_confidence` in result dict
  - Nutzt Nummer in `build_new_filename()`

## Geänderte Dateien

### Neu erstellt:
1. **config/supplier_field_aliases.yaml** - Supplier-Mappings
2. **core/doc_number_extractor.py** - Extraktionslogik
3. **core/test_doc_number_extractor.py** - Unit-Tests
4. **core/test_doc_number_manual.py** - Manueller Schnelltest

### Modifiziert:
1. **core/extractor.py**
   - Import: `from core.doc_number_extractor import extract_doc_number, generate_fallback_identifier`
   - `process_pdf()`: Integriert doc_number extraction
   - Speichert `doc_number`, `doc_number_source`, `doc_number_confidence` in result dict

## Setup-Schritte

### 1. Dependency prüfen
```powershell
python -c "import yaml; print('PyYAML OK')"
```
Falls nicht installiert:
```powershell
pip install pyyaml
```

### 2. Config validieren
```powershell
python -c "from core.doc_number_extractor import DocNumberExtractor; e=DocNumberExtractor(); print(f'Loaded {len(e.supplier_mappings)} suppliers')"
```
Erwartete Ausgabe: `Loaded 8 suppliers`

### 3. Tests ausführen
```powershell
# Schnelltest (alle 8 Supplier)
python test_quick.py

# Unit-Tests
python core/test_doc_number_extractor.py

# Manueller Test
python core/test_doc_number_manual.py
```

## Manuelle Tests mit echten PDFs

### Test 1: WM Auftrags-Nr
```powershell
# PDF mit "Auftrags-Nr: 12345678" hochladen
# Erwarteter Dateiname: WM_2025-11-26_12345678.pdf
```

### Test 2: Vergölst Belegnummer
```powershell
# PDF mit "Beleg-Nr: D018017955" hochladen
# Erwarteter Dateiname: VERGOELST_2025-11-27_D018017955.pdf
```

### Test 3: WFI Lieferscheinnr
```powershell
# PDF mit "Lieferscheinnr: LS20250982" hochladen
# Erwarteter Dateiname: WFI_2025-11-26_LS20250982.pdf
```

### Test 4: FUCHS Nummer
```powershell
# PDF mit "Nummer: 226267189" hochladen
# Erwarteter Dateiname: FUCHS_2025-11-18_226267189.pdf
```

### Test 5: LKQ Lieferschein-Nr
```powershell
# PDF mit "Lieferschein-Nr: 3814300" hochladen
# Erwarteter Dateiname: LKQ_PV_AUTOMOTIVE_2025-11-25_3814300.pdf
```

### Test 6: OK Rechnungsnummer
```powershell
# PDF mit "Rechnungsnummer: RE-2025-90879" hochladen
# Erwarteter Dateiname: OK_2025-11-22_RE-2025-90879.pdf
```

### Test 7: Hofmeister Auftragsnr
```powershell
# PDF mit "Auftragsnr.: 14619213" hochladen
# Erwarteter Dateiname: HOFMEISTER_MEINCKE_2025-11-25_14619213.pdf
```

### Test 8: PIRTEK Arbeitsauftrag
```powershell
# PDF mit "Arbeitsauftrag: 08625112402" hochladen
# Erwarteter Dateiname: PIRTEK_2025-11-24_08625112402.pdf
```

### Test 9: Fallback ohne Nummer
```powershell
# PDF ohne erkennbare Dokumentnummer hochladen
# Erwarteter Dateiname: <Supplier>_<Datum>_ohneNr_A1B2C3.pdf
# (Hash ist deterministisch pro PDF-Inhalt)
```

## Verifikation nach Upload

Nach dem Upload eines PDFs:

1. **Check Dateiname** in `daten_fertig/` oder Auto-Sort-Ordner
2. **Check Logs** in `data/logs/`:
   - `doc_number`: Extrahierte Nummer
   - `doc_number_source`: Feldname der Quelle (z.B. "Beleg-Nr", "Auftragsnummer")
   - `doc_number_confidence`: Confidence-Level ("high", "medium", "low", "none")
3. **Check Web-UI**: Review-Details sollten doc_number anzeigen

## Troubleshooting

### Problem: Config nicht geladen
```powershell
# Prüfe Pfad
python -c "from pathlib import Path; from core.doc_number_extractor import DocNumberExtractor; e=DocNumberExtractor(); print(f'Config path: {e.config_path}'); print(f'Exists: {e.config_path.exists()}')"
```

### Problem: Nummer nicht erkannt
```powershell
# Debug-Extraktion für spezifischen Text
python -c "from core.doc_number_extractor import extract_doc_number; r=extract_doc_number('Ihr Text hier', 'WM'); print(f'Number: {r.doc_number}, Source: {r.source_field}, Conf: {r.confidence}')"
```

### Problem: False Positive (z.B. PLZ erkannt als Nummer)
→ Feldname-Mapping in `config/supplier_field_aliases.yaml` erweitern
→ Filter in `_is_plausible_doc_number()` anpassen

## Erweiterung für neue Supplier

1. **Config erweitern** (`config/supplier_field_aliases.yaml`):
```yaml
suppliers:
  NEUER_SUPPLIER:
    doc_number_fields:
      - "Belegnr"
      - "Beleg Nr"
    secondary_fields:
      - "Auftragsnummer"
```

2. **Test hinzufügen** (`test_quick.py`):
```python
('NEUER_SUPPLIER', 'Belegnr: 999888', '999888'),
```

3. **Validieren**:
```powershell
python test_quick.py
```

## Hinweise

- **Unique Suffix**: Bei Duplikaten wird automatisch `_01`, `_02` angehängt
- **Logging**: Alle Extraktionen werden in result dict gespeichert für Audit-Trail
- **Performance**: Config wird nur einmal beim ersten Aufruf geladen (lazy loading)
- **Fallback**: Wenn neuer Extractor nicht verfügbar, nutzt System alte `extract_document_numbers()` Methode
