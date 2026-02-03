import os
import re
import argparse
from pathlib import Path
from datetime import datetime

from pdf2image import convert_from_path
import pytesseract
from dateutil import parser as date_parser

"""
Lieferschein-Umbenner mit OCR

Voraussetzungen (später auf dem großen Rechner):
    pip install pdf2image pytesseract pillow python-dateutil

Und:
    - Tesseract-OCR installieren
    - Für pdf2image unter Windows: Poppler installieren (z.B. poppler-xx für Windows)
      und ggf. convert_from_path(poppler_path=...) verwenden.
"""

# ======================================================================
# BASISPFAD: Projektordner = .../LieferscheinTool
# (dieses Script liegt in .../LieferscheinTool/python)
# ======================================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_INPUT_DIR = BASE_DIR / "daten_eingang"
DEFAULT_OUTPUT_DIR = BASE_DIR / "daten_fertig"

# Tesseract-Pfad:
# - Unter Windows ggf. hier eintragen, z.B.:
#   TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# - Unter Linux meist leer lassen, dann nimmt pytesseract den System-Pfad.
TESSERACT_CMD = r""  # später bei Bedarf anpassen

# Lieferanten-Liste: "Suchbegriff im Text" -> "Kurzname für Dateiname"
SUPPLIER_KEYWORDS = {
    "Liebherr-Werk Ehingen": "Liebherr_Ehingen",
    "Liebherr-Werk Nenzing": "Liebherr_Nenzing",
    "DB Schenker": "DBSchenker",
    "DHL Paket": "DHL",
    "Linde Material Handling": "Linde",
    "Manitowoc": "Manitowoc",
    "Pirtek": "Pirtek",
    "Vergoelst": "Vergoelst",
    "Tadano": "Tadano",
    "Georg Zopf": "Zopf",
    "WM Fahrzeugteile": "WM",
    "WFI Wireless Funk": "WFI",
    "Hofmeister & Meincke": "Hofmeister",
    "Förch GmbH": "Förch",
    "Borgmann": "VW Borgmann", 
    "Fuchs Lubricants Germany GmbH": "Fuchs",
    "Ortjohann und Kraft Werkzeug und Maschinenhandel GmbH": "Ortjohann+ Kraft",
    "PV Automotive GmbH": "PV Automotive",



    # hier deine echten Lieferanten ergänzen...
}

# Datums-Patterns (deutsch & ISO)
DATE_REGEXES = [
    r"\b(\d{2}\.\d{2}\.\d{4})\b",   # 24.12.2025
    r"\b(\d{4}-\d{2}-\d{2})\b",     # 2025-12-24
    r"\b(\d{2}/\d{2}/\d{4})\b",     # 24/12/2025
]


# ======================================================================
# HILFSFUNKTIONEN
# ======================================================================

def setup_tesseract():
    """
    Setzt den Pfad zur Tesseract-Installation, falls nötig.
    Unter Linux kannst du TESSERACT_CMD meist leer lassen.
    """
    if TESSERACT_CMD:
        t_path = Path(TESSERACT_CMD)
        if t_path.exists():
            pytesseract.pytesseract.tesseract_cmd = str(t_path)


def ocr_first_page(pdf_path: Path) -> str:
    """
    Liest die erste Seite eines gescannten PDFs per OCR aus
    und gibt den erkannten Text zurück.
    """
    # Hinweis: ggf. poppler_path=... ergänzen, wenn pdf2image meckert
    images = convert_from_path(str(pdf_path), dpi=300, first_page=1, last_page=1)
    if not images:
        return ""

    image = images[0]
    text = pytesseract.image_to_string(image, lang="deu")  # OCR auf Deutsch
    return text


def extract_date(text: str):
    """
    Versucht, ein Datum aus dem OCR-Text zu extrahieren.
    Gibt ein datetime-Objekt oder None zurück.
    """
    candidates = []

    for pattern in DATE_REGEXES:
        for match in re.findall(pattern, text):
            try:
                dt = date_parser.parse(match, dayfirst=True)
                candidates.append(dt)
            except (ValueError, OverflowError):
                continue

    if not candidates:
        return None

    # Heuristik: nimm das früheste Datum im Dokument
    return min(candidates)


def detect_supplier(text: str) -> str:
    """
    Sucht nach bekannten Lieferanten im Text.
    Gibt den Kurzname für den Dateinamen oder 'Unbekannt' zurück.
    """
    lower_text = text.lower()

    for keyword, shortname in SUPPLIER_KEYWORDS.items():
        if keyword.lower() in lower_text:
            return shortname

    return "Unbekannt"


def build_new_filename(original: Path, supplier: str, date_obj):
    """
    Baut den neuen Dateinamen:
    Lieferant + Datum, z.B. Liebherr_2025-12-24.pdf
    """
    # Datumsteil
    if date_obj is not None:
        # ISO-Format: 2025-12-24
        date_part = date_obj.strftime("%d.%m.%Y")
        # Wenn du lieber deutsches Format willst, nimm:
        # date_part = date_obj.strftime("%d.%m.%Y")
    else:
        date_part = "unbekanntes-Datum"

    # Lieferantenname auf sichere Zeichen begrenzen (Leerzeichen erlaubt)
    if not supplier:
        supplier = "Unbekannter_Lieferant"

    # Unerlaubte/komische Zeichen ersetzen
    safe_supplier = re.sub(r'[^a-zA-Z0-9äöüÄÖÜß \-]', '_', supplier)

    # Finaler Name: Lieferant_Datum.pdf
    new_name = f"{safe_supplier}_{date_part}.pdf"
    return new_name



def get_unique_path(target_dir: Path, filename: str) -> Path:
    """
    Sorgt dafür, dass der Dateiname eindeutig ist.
    Falls der Name bereits existiert, wird _1, _2, ... angehängt.
    """
    candidate = target_dir / filename
    counter = 1
    while candidate.exists():
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        candidate = target_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def process_pdf(pdf_path: Path, output_dir: Path):
    print(f"\nVerarbeite: {pdf_path.name}")

    try:
        text = ocr_first_page(pdf_path)
        if not text.strip():
            print("  Warnung: Kein Text erkannt.")
    except Exception as e:
        print(f"  Fehler bei OCR: {e}")
        return

    # Lieferant und Datum ermitteln
    supplier = detect_supplier(text)
    date_obj = extract_date(text)

    print(f"  Ermittelter Lieferant: {supplier}")
    print(f"  Ermitteltes Datum:    {date_obj.strftime('%Y-%m-%d') if date_obj else 'kein Datum gefunden'}")

    # Neuen Dateinamen bauen
    new_filename = build_new_filename(pdf_path, supplier, date_obj)
    target_path = get_unique_path(output_dir, new_filename)

    try:
        if pdf_path.parent == output_dir:
            pdf_path.rename(target_path)
        else:
            os.replace(pdf_path, target_path)

        print(f"  Umbenannt in: {target_path.name}")
    except Exception as e:
        print(f"  Fehler beim Umbenennen/Verschieben: {e}")


# ======================================================================
# HAUPTFUNKTION
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Lieferscheine-PDFs per OCR auslesen und nach Lieferant + Datum umbenennen."
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=str(DEFAULT_INPUT_DIR),
        help="Ordner mit den eingehenden PDF-Dateien (Standard: daten_eingang im Projektordner)."
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Zielordner für umbenannte Dateien (Standard: daten_fertig im Projektordner)."
    )

    args = parser.parse_args()

    setup_tesseract()

    input_dir = Path(args.input)
    output_dir = Path(args.output)

    if not input_dir.exists():
        print(f"Input-Ordner existiert nicht: {input_dir}")
        return

    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(input_dir.glob("*.pdf"))

    if not pdf_files:
        print("Keine PDF-Dateien im Input-Ordner gefunden.")
        print(f"Ordner: {input_dir}")
        return

    print(f"{len(pdf_files)} PDF-Datei(en) gefunden. Starte Verarbeitung...")
    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")

    for pdf in pdf_files:
        process_pdf(pdf, output_dir)

    print("\nFertig!")


if __name__ == "__main__":
    main()
