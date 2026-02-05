# Abhängigkeiten (Docaro)

Diese Liste ist für eine typische Debian/Ubuntu VPS-Installation gedacht.

## System-Pakete (Debian/Ubuntu)

Minimal (Runtime):

- `python3` (>= 3.9)
- `python3-venv`
- `python3-pip`
- `python3-dev` (hilfreich, falls Wheels fehlen)
- `build-essential` (hilfreich, falls Wheels fehlen)
- `tesseract-ocr`
- `tesseract-ocr-deu` (Deutsch-Sprachpaket)
- `poppler-utils` (liefert `pdfinfo` und `pdftoppm` für `pdf2image`)
- `redis-server`

Empfohlen (oft nötig, wenn Python-Pakete aus Source bauen müssen, z.B. Pillow):

- `libjpeg-dev`
- `zlib1g-dev`
- `libfreetype6-dev`
- `libopenjp2-7-dev`
- `libtiff5-dev`

Optional (nur wenn aktiviert/verwendet):

- `libgl1` (für bestimmte ML/OCR-Komponenten, z.B. PaddleOCR/OpenCV)
- Reverse Proxy: `nginx`

## Python-Pakete

Installiert über:

- `pip install -r requirements.txt`

Wesentliche Runtime-Dependencies (Auszug):

- Web: `flask`, `gunicorn`
- Queue: `rq`, `redis`
- OCR/PDF: `pytesseract`, `pdf2image`, `pymupdf` (optional), `pdfplumber`, `PyPDF2`, `pillow`
- Parsing/Utility: `python-dateutil`, `PyYAML`, `argon2-cffi`

Optionale Stacks:

- ML/Extras: siehe `requirements-ml.txt`, `requirements-ml-full.txt`, `requirements-paddleocr.txt`, `requirements-docling.txt`.

## Externe Tools

- `tesseract` muss verfügbar sein (Befehl `tesseract`).
- `pdfinfo` und `pdftoppm` müssen verfügbar sein (aus `poppler-utils`).

## Hinweise

- In Git sollten keine Laufzeitdaten liegen: der Ordner `data/` (bzw. große Unterordner) ist in `.gitignore` aus gutem Grund ausgeschlossen.
- Die Start-Services nutzen standardmäßig `/etc/docaro/docaro.env` als EnvironmentFile.

## Beispiel-Dateien (für frische Installationen)

Damit ein neues Repo keine echten Produktionsdaten enthalten muss, liegen im Repo Beispiel-Dateien unter `data/`:

- `data/suppliers.example.json` → bei Bedarf nach `data/suppliers.json` kopieren
- `data/settings.example.json` → bei Bedarf nach `data/settings.json` kopieren
