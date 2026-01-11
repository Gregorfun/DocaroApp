#!/usr/bin/env python
"""Direct test of extract_best_date for scan_20251127071452.pdf."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.extractor import extract_best_date, _render_pdf_images, _POPPLER_BIN, OCR_PAGES
from datetime import datetime

pdf_path = Path(r"D:\Docaro\Daten eingang\scan_20251127071452.pdf")

print(f"Testing: {pdf_path.name}")
print(f"Rendering PDF...")
images, err = _render_pdf_images(pdf_path, _POPPLER_BIN, pages=OCR_PAGES)
if err:
    print(f"Render error: {err}")
    sys.exit(1)

print(f"Running extract_best_date...")
result = extract_best_date(pdf_path, images=images, pages=OCR_PAGES)

date_obj = result.get("date")
date_iso = date_obj.strftime("%Y-%m-%d") if date_obj else "-"
source = result.get("source", "")
conf = result.get("confidence", 0.0)
evidence = result.get("evidence", "")[:100]

print(f"\n=== RESULT ===")
print(f"Date: {date_iso}")
print(f"Source: {source}")
print(f"Confidence: {conf:.2f}")
print(f"Evidence: {evidence}")
