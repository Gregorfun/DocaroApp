from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from pathlib import Path
import sys

# Ensure parent directory (workspace root) is on sys.path to import 'core'
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.extractor import (
    _extract_textlayer,
    _render_pdf_images,
    _ocr_images_best,
    detect_supplier,
    extract_best_date,
    OCR_PAGES,
    _POPPLER_BIN,
)


def diagnose_pdf(pdf_path: Path) -> None:
    if not pdf_path.exists():
        print(f"{pdf_path} -> not found")
        return

    # Textlayer check
    text_pages, text_err = _extract_textlayer(pdf_path, pages=OCR_PAGES)
    textlayer_text = "\n".join(text_pages) if text_pages else ""
    textlayer_words = len(textlayer_text.split())

    # OCR rotation/text
    images, render_err = _render_pdf_images(pdf_path, _POPPLER_BIN, pages=OCR_PAGES)
    ocr_info = _ocr_images_best(images or [], force_best=False) if images else {"text": "", "error": render_err or ""}
    rotation = ocr_info.get("rotation", "")
    rotation_reason = ocr_info.get("rotation_reason", "")
    ocr_error = ocr_info.get("error", "")
    ocr_text = ocr_info.get("text", "")

    # Supplier
    supplier, supplier_conf, supplier_src, supplier_guess = ("", 0.0, "none", "")
    if textlayer_text.strip():
        supplier, supplier_conf, supplier_src, supplier_guess = detect_supplier(textlayer_text)
    elif ocr_text.strip():
        supplier, supplier_conf, supplier_src, supplier_guess = detect_supplier(ocr_text)

    # Date extraction
    pick = extract_best_date(pdf_path, images=images, textlayer_pages=text_pages, pages=OCR_PAGES)
    date_obj = pick.get("date")
    date_iso = date_obj.strftime("%Y-%m-%d") if date_obj else "-"
    date_src = pick.get("source", "")
    date_conf = pick.get("confidence", 0.0) or 0.0
    date_evidence = pick.get("evidence", "") or ""

    # Output concise summary
    print(
        f"{pdf_path.name} | rot={rotation or 0}({rotation_reason}) | textlayer_words={textlayer_words} | "
        f"date={date_iso}({date_src},{date_conf:.2f}) | supplier={supplier}({supplier_src},{supplier_conf:.2f}) | "
        f"err={text_err or ocr_error or ''} | evidence={date_evidence[:80]}"
    )


if __name__ == "__main__":
    args = [Path(a) for a in sys.argv[1:]]
    if not args:
        print("Usage: python tools/diagnose_incoming.py <pdf> [<pdf> ...]")
        sys.exit(1)
    for p in args:
        diagnose_pdf(p)
