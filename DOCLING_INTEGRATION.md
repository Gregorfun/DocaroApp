# Docling-Integration für Docaro

## 📋 Übersicht

Docling ist ein modernes Document Processing Framework von IBM Research, das erweiterte PDF-Verarbeitung mit Layout-Erkennung, OCR und Tabellenerkennung bietet.

### Features:
- ✅ **Fortgeschrittene PDF-Analyse**: Layout-Erkennung, Reading Order, Tabellen-Struktur
- ✅ **Multiple Formate**: PDF, DOCX, PPTX, XLSX, HTML, Bilder, Audio
- ✅ **Integrierte OCR**: RapidOCR (schneller, Open Source)
- ✅ **Strukturierte Ausgabe**: Markdown, JSON, HTML, DocTags
- ✅ **Lokal ausführbar**: Keine Cloud-Abhängigkeiten, datenschutzfreundlich

## 🚀 Installation

### Schritt 1: Basis-Installation
```bash
pip install docling
```

**Hinweis**: Die Installation kann 5-10 Minuten dauern und benötigt ~1-2 GB Speicherplatz (mit vorgeladenen Modellen).

### Schritt 2: Optional - Verbesserte OCR (für gescannte PDFs)
```bash
pip install "docling[ocr]"
```

### Schritt 3: Optional - Vision Language Models (VLMs)
```bash
pip install "docling[granite]"
```

## 📖 Verwendung

### 1. In der Flask Web-UI

Nach der Installation ist die **Docling-Analyse-Sektion** auf der Startseite verfügbar:

- **Neue Section**: "Docling-Analyse (Vorschau)"
- **Funktionalität**: 
  - PDFs hochladen
  - Schnelle Analyse mit Docling
  - Extraktion von: Text, Datum, Lieferant, Tabellen, Metadaten
  - Live-Vorschau der Ergebnisse

### 2. Im Python-Code

```python
from core.docling_extractor import get_extractor

# Extractor initialisieren
extractor = get_extractor()

if extractor:
    # Text extrahieren
    text = extractor.extract_text("path/to/document.pdf")
    
    # Seitenweise Extraktion
    pages = extractor.extract_text_per_page("path/to/document.pdf")
    
    # Tabellen extrahieren
    tables = extractor.extract_tables("path/to/document.pdf")
    
    # Metadaten abrufen
    metadata = extractor.extract_metadata("path/to/document.pdf")
    
    # Datum extrahieren
    date = extractor.extract_date("path/to/document.pdf")
    
    # Lieferant erkennen
    supplier = extractor.extract_supplier("path/to/document.pdf")
```

## 🔧 Integration mit bestehenden Extractoren

### Fallback-Logik (empfohlen)

Die neue Docling-Integration läuft **parallel** zum bestehenden Tesseract-System:

```python
# Versuche mit Docling
extractor = get_extractor()
if extractor:
    # Docling ist verfügbar
    text = extractor.extract_text(pdf_path)
else:
    # Fallback auf Tesseract
    from core.extractor import extract_text_ocr
    text = extract_text_ocr(pdf_path)
```

### Neue Flask-Routes

| Route | Methode | Beschreibung |
|-------|---------|-------------|
| `/analyze_docling` | POST | Analysiert hochgeladene PDFs mit Docling |
| `/docling_status.json` | GET | Gibt Status der Docling-Verfügbarkeit zurück |

## 📊 Vergleich: Docling vs. Tesseract

| Feature | Tesseract | Docling |
|---------|-----------|---------|
| **PDF-Text** | Gut | Sehr gut |
| **Layout-Erkennung** | Nein | Ja ✓ |
| **Tabellen** | Nein | Ja ✓ |
| **Scans (OCR)** | Spezialisiert | Unterstützt |
| **Geschwindigkeit** | Sehr schnell | Moderat (1-5s pro PDF) |
| **Speichernutzung** | Niedrig | Mittel (inkl. Modelle) |
| **Modelle** | Statisch | Herunterladbar |

## 🧪 Tests

Zur Überprüfung der Installation:

```bash
# Alle Docling-Tests ausführen
python core/test_docling.py

# Oder mit pytest
pytest core/test_docling.py -v
```

**Erwartete Ausgabe**:
```
test_is_docling_available ... ok
Docling verfügbar: True
test_extractor_init ... ok
...
```

## 📝 Konfiguration

### Umgebungsvariablen

In `config.py` oder `.env` können folgende Werte gesetzt werden:

```bash
# Docling aktivieren (optional, standardmäßig immer verfügbar wenn installiert)
DOCLING_ENABLED=1

# Pipeline-Wahl (standard, vlm)
DOCLING_PIPELINE=standard

# Verbesserte OCR aktivieren
DOCLING_USE_OCR=1

# VLM-Modell wählen (z.B. "granite_docling")
DOCLING_VLM_MODEL=granite_docling
```

## 🔍 Beispiel: Text-Extraktion mit Vorschau

```python
from pathlib import Path
from core.docling_extractor import get_extractor

pdf_file = Path("example.pdf")
extractor = get_extractor()

if extractor:
    # Text extrahieren
    full_text = extractor.extract_text(pdf_file)
    print(f"Text-Länge: {len(full_text)} Zeichen")
    print(f"Erste 500 Zeichen:\n{full_text[:500]}")
    
    # Metadaten
    metadata = extractor.extract_metadata(pdf_file)
    print(f"Seiten: {metadata['num_pages']}")
    
    # Datum & Lieferant erkennen
    date = extractor.extract_date(pdf_file)
    supplier = extractor.extract_supplier(pdf_file)
    print(f"Datum: {date}, Lieferant: {supplier}")
```

## ⚠️ Häufige Probleme

### Problem: "Docling ist nicht installiert"
**Lösung**: 
```bash
pip install docling
```

### Problem: Speicherprobleme bei der Installation
**Lösung**: Installiere in Etappen
```bash
# 1. Nur Core
pip install docling-core

# 2. Parser
pip install docling-parse

# 3. Volles Paket
pip install docling
```

### Problem: Zu langsam
**Lösung**: Nutze nur die erste Seite für schnelle Vorschauen:
```python
# Nur erste 3 Seiten analysieren
pages = extractor.extract_text_per_page(pdf_path)
first_pages = {k: v for k, v in list(pages.items())[:3]}
```

## 📚 Weitere Ressourcen

- **Offizielle Dokumentation**: https://docling-project.github.io/docling/
- **GitHub-Repository**: https://github.com/docling-project/docling
- **Technischer Report**: https://arxiv.org/abs/2408.09869
- **Modelle**: https://huggingface.co/ibm-granite

## 🤝 Integration mit Docaro-Workflow

### Empfohlener Workflow:

1. **Upload**: Nutzer lädt PDFs hoch
2. **Docling-Analyse** (optional):
   - Schnelle Vorschau der erkannten Daten
   - User kann Ergebnisse vor Verarbeitung sehen
3. **Tesseract-Fallback**: Für OCR-intensive Fälle immer noch verfügbar
4. **Export**: Kombinierte Ergebnisse speichern

### Zukünftige Verbesserungen:

- [ ] Automatische Modell-Updates
- [ ] Multi-Processing für Batch-Verarbeitung
- [ ] VLM-basierte Intelligent Extraction
- [ ] Webhook-Integration für asynchrone Verarbeitung
- [ ] Caching von Erkennungsergebnissen

## 📞 Support

Bei Problemen oder Fragen:
1. Überprüfe die Tests: `python core/test_docling.py`
2. Schau in die Debug-Logs: `tail -f data/logs/*.log`
3. Eröffne ein Issue mit Fehlermeldung und PDF-Beispiel
