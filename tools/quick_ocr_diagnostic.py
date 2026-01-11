#!/usr/bin/env python
"""Quick OCR diagnostic for two problematic PDFs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf2image import convert_from_path
from config import Config
from core.extractor import _TESSERACT_PATH, _POPPLER_BIN
import pytesseract

if _TESSERACT_PATH:
    pytesseract.pytesseract.tesseract_cmd = str(_TESSERACT_PATH)

pdf_path_1 = Path(r"D:\Docaro\Daten eingang\scan_20251127071452.pdf")
pdf_path_2 = Path(r"D:\Docaro\Daten eingang\scan_20251127053019.pdf")

print("=== PDF 1: scan_20251127071452.pdf (detected 270° by OSD) ===")
try:
    images_1 = convert_from_path(str(pdf_path_1), dpi=150, first_page=1, last_page=1, 
                                 poppler_path=r"D:\Docaro\poppler\Library\bin")
    print(f"Size: {images_1[0].size}")
    
    # Try OSD
    try:
        osd = pytesseract.image_to_osd(images_1[0], timeout=10)
        print(f"OSD: {osd}")
    except Exception as e:
        print(f"OSD error: {e}")
    
    # OCR at 0 degrees
    text_0 = pytesseract.image_to_string(images_1[0], lang="deu", timeout=10)
    print(f"\nOCR at 0° (first 300 chars):\n{text_0[:300]}")
    
    # OCR at 270 degrees
    rotated = images_1[0].rotate(270, expand=True)
    text_270 = pytesseract.image_to_string(rotated, lang="deu", timeout=10)
    print(f"\nOCR at 270° (first 300 chars):\n{text_270[:300]}")
except Exception as e:
    print(f"Error PDF1: {e}")

print("\n=== PDF 2: scan_20251127053019.pdf (WM recognized, no date found) ===")
try:
    images_2 = convert_from_path(str(pdf_path_2), dpi=150, first_page=1, last_page=1, 
                                 poppler_path=r"D:\Docaro\poppler\Library\bin")
    print(f"Size: {images_2[0].size}")
    
    # OCR at 0 degrees
    text_0 = pytesseract.image_to_string(images_2[0], lang="deu", timeout=10)
    print(f"\nOCR at 0° (full text):\n{text_0}")
except Exception as e:
    print(f"Error PDF2: {e}")
