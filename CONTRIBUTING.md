# Entwicklerhandbuch fuer DocaroApp

Vielen Dank fuer Ihr Interesse an der Mitarbeit an DocaroApp!

## Entwicklungsumgebung einrichten

### 1. Repository klonen

```bash
git clone https://github.com/Gregorfun/DocaroApp.git
cd DocaroApp
```

### 2. Virtuelle Umgebung erstellen

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

### 3. Abhängigkeiten installieren

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
pre-commit install
```

### 4. Umgebungsvariablen konfigurieren

```bash
# .env.example zu .env kopieren
cp .env.example .env

# .env bearbeiten und anpassen
```

### 5. Entwicklungsserver starten

```bash
python app/app.py
```

## Projektstruktur

```
Docaro/
├── app/                    # Flask Web-Anwendung
│   ├── app.py             # Hauptanwendung und Routen
│   ├── static/            # CSS, JavaScript, Bilder
│   └── templates/         # HTML-Templates (Jinja2)
├── core/                   # Kernlogik
│   ├── extractor.py       # OCR und Metadaten-Extraktion
│   └── test_extractor.py  # Unit-Tests
├── tools/                  # Hilfsskripte
├── data/                   # Laufzeitdaten (nicht im Git)
├── config.py              # Zentrale Konfiguration
├── constants.py           # Konstanten (Regex-Patterns, etc.)
├── date_parser.py         # Spezielle Datumsparser-Logik
├── utils.py               # Hilfsfunktionen
└── requirements.txt       # Python-Abhängigkeiten
```

## Coding-Standards

### Python-Stil

- Folgen Sie [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- Verwenden Sie aussagekräftige Variablennamen (auch auf Deutsch, wenn sinnvoll)
- Fügen Sie Docstrings für Funktionen und Klassen hinzu
- Verwenden Sie Type Hints wo möglich
- Vor jedem Commit `pre-commit run --all-files` ausführen

### Beispiel:

```python
def extract_date(text: str, format_hint: str = "") -> Optional[datetime]:
    """
    Extrahiert ein Datum aus einem Text.

    Args:
        text: Der zu durchsuchende Text
        format_hint: Optional ein erwartetes Datumsformat

    Returns:
        datetime-Objekt oder None, wenn kein Datum gefunden wurde
    """
    # Implementierung hier
    pass
```

### Git-Workflow

1. **Feature Branch erstellen**
   ```bash
   git checkout -b feature/meine-neue-funktion
   ```

2. **Änderungen committen**
   ```bash
   git add .
   git commit -m "Beschreibende Commit-Nachricht"
   ```

3. **Tests ausführen**
   ```bash
    python -m unittest core.test_extractor
   python tools/test_extract_date.py
   ```

4. **Push und Pull Request**
   ```bash
   git push origin feature/meine-neue-funktion
   ```

### Commit-Nachrichten

Verwenden Sie klare, beschreibende Commit-Nachrichten:

- ✓ "Fix: OCR-Timeout-Fehler bei großen PDFs behoben"
- ✓ "Feature: Unterstützung für österreichische Datumsformate"
- ✓ "Refactor: Extraktor-Logik in separate Funktionen aufgeteilt"
- ✗ "Fix"
- ✗ "Änderungen"

## Tests schreiben

### Unit-Tests

Tests befinden sich in `core/test_extractor.py`. Neue Tests hinzufügen:

```python
def test_neue_funktion():
    """Testet die neue Funktion."""
    result = meine_funktion(test_input)
    assert result == expected_output
```

### Tests ausführen

```bash
# Alle Tests
python -m pytest core/test_extractor.py -v

# Spezifischer Test
python -m pytest core/test_extractor.py::test_name -v

# Mit Coverage
python -m pytest --cov=core core/test_extractor.py

# Benchmark-Tests
python -m pytest tests/performance/test_benchmark_extractor.py --benchmark-only
```

## Häufige Aufgaben

### Neues Datumsformat hinzufügen

1. Pattern in `constants.py` unter `DATE_REGEX_PATTERNS` hinzufügen
2. Parser-Logik in `date_parser.py` erweitern (falls nötig)
3. Tests in `tools/test_extract_date.py` hinzufügen
4. In `app/app.py` unter `ALLOWED_DATE_FORMATS` eintragen

### Neue OCR-Strategie implementieren

1. Funktion in `core/extractor.py` hinzufügen
2. In `process_pdf()` einbinden
3. Timeout-Konfiguration in `config.py` hinzufügen
4. Tests schreiben

### Web-Interface erweitern

1. Route in `app/app.py` hinzufügen
2. Template in `app/templates/` erstellen
3. Statische Assets in `app/static/` ablegen

## Debugging

### Debug-Modus aktivieren

In `.env`:
```bash
DOCARO_DEBUG=1
DOCARO_DEBUG_EXTRACT=1
```

### Logs überprüfen

```bash
# Live-Logs anzeigen
tail -f data/logs/docaro.log

# Debug-Logs für Extraktion
tail -f data/logs/extract_debug.log
```

### Tesseract-OCR debuggen

```bash
# Direkt testen
tesseract test.pdf output.txt -l deu

# Mit Preprocessing
python -c "from core.extractor import *; test_ocr_on_file('test.pdf')"
```

## Performance-Optimierung

- OCR ist der langsamste Teil - begrenzen Sie die Anzahl der Seiten (`DOCARO_OCR_PAGES`)
- PDF-zu-Bild-Konvertierung ist I/O-intensiv - verwenden Sie SSDs
- Parallele Verarbeitung wird über Threading in `app/app.py` gehandhabt
- Vermeiden Sie `DOCARO_DEEP_SCAN=1`, es sei denn, es ist wirklich nötig

## Sicherheit

### Wichtige Regeln

- ✓ Verwenden Sie immer `secure_filename()` für Dateinamen
- ✓ Validieren Sie alle Benutzereingaben
- ✓ Verwenden Sie Umgebungsvariablen für Secrets
- ✓ Setzen Sie `DEBUG=0` in Produktion
- ✗ Committen Sie niemals `.env` oder Secrets
- ✗ Verwenden Sie keine hartcodierten Pfade mit Benutzereingaben

### Eingabe-Validierung

```python
# Gut
safe_name = secure_filename(user_input)
cleaned = _normalize_supplier_input(user_input)

# Schlecht
path = Path(user_input)  # Keine Validierung!
```

## Fragen?

Bei Fragen oder Problemen:

1. Überprüfen Sie die [README.md](README.md)
2. Durchsuchen Sie bestehende Issues
3. Erstellen Sie ein neues Issue mit detaillierter Beschreibung
4. Fügen Sie Logs und Fehlermeldungen hinzu

Vielen Dank für Ihre Mitarbeit! 🎉
