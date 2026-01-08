# Docaro Startskript mit Tesseract-Konfiguration
# HINWEIS: Tesseract muss mit deutschen Sprachdaten (deu.traineddata) installiert sein
# Download: https://github.com/tesseract-ocr/tessdata/raw/main/deu.traineddata
# Speichern unter: C:\Program Files\Tesseract-OCR\tessdata\deu.traineddata

# Setze Tesseract-Pfade
$env:DOCARO_TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
$env:TESSDATA_PREFIX = "C:\Program Files\Tesseract-OCR\tessdata"

# Optional: Debug-Modi aktivieren (auskommentieren bei Bedarf)
# $env:DOCARO_DEBUG = "1"
# $env:DOCARO_DEBUG_EXTRACT = "1"

Write-Host "Tesseract konfiguriert: $env:DOCARO_TESSERACT_CMD" -ForegroundColor Green
Write-Host "Starte Docaro App..." -ForegroundColor Cyan

# Starte Flask-App mit Python aus der venv
& .\.venv\Scripts\python.exe .\app\app.py
