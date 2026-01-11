# Docaro

Kleines Tool/Web-UI zum Auswerten von Lieferscheinen (PDF), inkl. OCR/Rotation sowie Extraktion von Lieferant und Datum.

## Setup (Windows)

- Python 3.11
- Poppler + Tesseract (Pfad kann per ENV gesetzt werden)

Installation:

```powershell
D:/Docaro/.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Start:

```powershell
./start_app.ps1
```

## Wichtige Umgebungsvariablen

- `DOCARO_TESSERACT_CMD` – Pfad zur `tesseract.exe`
- `DOCARO_POPPLER_BIN` – Pfad zum Poppler `bin`-Ordner
- `DOCARO_OCR_PAGES` – Anzahl Seiten für OCR (Default: 2)
- `DOCARO_OCR_TIMEOUT` – OCR Timeout in Sekunden (Default: 8)

Optional (experimentell):

- `DOCARO_USE_PADDLEOCR=1` – aktiviert PaddleOCR als Fallback (wenn installiert)
- `DOCARO_PADDLEOCR_LANG=german` – PaddleOCR Sprache

## Tools

Batch-Report für einen Ordner mit PDFs (ohne Dateien zu verschieben):

```powershell
D:/Docaro/.venv/Scripts/python.exe tools/report_incoming.py "D:\Docaro\Daten eingang"
```

Einzel-PDF Diagnose (Rotation/ROI OCR):

```powershell
D:/Docaro/.venv/Scripts/python.exe tools/inspect_pdf.py "D:\Docaro\Daten eingang\scan_20251120054226.pdf"
```

## Repo-Hinweis

Eingangsordner/Scans und generierte Reports/Logs werden per `.gitignore` bewusst nicht mitversioniert.
