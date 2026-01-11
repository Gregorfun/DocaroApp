from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# PowerShell 5.1 (and some VS Code terminals) can treat native stderr output as a failing
# NativeCommandError. Paddle/PaddleX emits some informational messages to stderr
# (e.g., connectivity checks). When PaddleOCR is enabled, redirect stderr -> stdout
# early so batch runs complete and still capture logs.
_use_paddle_env = os.getenv("DOCARO_USE_PADDLEOCR", "").strip().lower()
if _use_paddle_env and _use_paddle_env not in {"0", "false", "no"}:
    try:
        os.dup2(sys.stdout.fileno(), sys.stderr.fileno())
    except Exception:
        try:
            sys.stderr = sys.stdout  # type: ignore[assignment]
        except Exception:
            pass

# Ensure workspace root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import extractor  # noqa: E402


@dataclass
class Row:
    filename: str
    rotation: str
    rotation_reason: str
    textlayer_words: int
    date_iso: str
    date_source: str
    date_conf: float
    date_evidence: str
    supplier: str
    supplier_source: str
    supplier_conf: float
    supplier_guess: str
    used_paddle: bool
    paddle_error: str
    error: str
    elapsed_ms: int


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return default


def _ocr_and_signals(pdf: Path, pages: int) -> Tuple[str, int, str, str, List[str], List[object]]:
    """Returns (textlayer_text, textlayer_words, text_err, render_err, text_pages, images)."""
    text_pages, text_err = extractor._extract_textlayer(pdf, pages=pages)
    textlayer_text = "\n".join(text_pages) if text_pages else ""
    textlayer_words = len(textlayer_text.split())

    images, render_err = extractor._render_pdf_images(pdf, extractor._POPPLER_BIN, pages=pages)
    return textlayer_text, textlayer_words, text_err, render_err, text_pages, images


def _maybe_paddle_fallback(
    images: List[object],
    supplier: str,
    supplier_conf: float,
    date_iso: str,
    date_conf: float,
) -> Tuple[str, float, str, float, bool, str]:
    """Try PaddleOCR on first page if it would improve missing/low-confidence fields."""
    use_paddle = getattr(extractor, "USE_PADDLEOCR", False)
    if not use_paddle or not images:
        return supplier, supplier_conf, date_iso, date_conf, False, ""

    need_paddle = (not date_iso or date_conf < 0.75) or (not supplier or supplier == "Unbekannt" or supplier_conf < 0.70)
    if not need_paddle:
        return supplier, supplier_conf, date_iso, date_conf, False, ""

    # _paddle_ocr_image is optional and returns (text, avg_conf, error)
    try:
        paddle_text, _paddle_avg_conf, paddle_err = extractor._paddle_ocr_image(images[0])
    except Exception as exc:
        return supplier, supplier_conf, date_iso, date_conf, True, f"paddle_failed: {exc}"

    if paddle_err:
        return supplier, supplier_conf, date_iso, date_conf, True, paddle_err

    updated_supplier = supplier
    updated_supplier_conf = supplier_conf
    if (not supplier) or supplier == "Unbekannt" or supplier_conf < 0.70:
        s2, c2, _src2, guess2 = extractor.detect_supplier(paddle_text)
        if s2 and s2 != "Unbekannt" and c2 >= updated_supplier_conf:
            updated_supplier = s2
            updated_supplier_conf = c2

    updated_date_iso = date_iso
    updated_date_conf = date_conf
    if (not date_iso) or (date_conf < 0.75):
        if extractor.date_parser:
            dp_iso, _dp_reason = extractor.date_parser.extract_date_from_text(paddle_text)
            if dp_iso:
                updated_date_iso = dp_iso
                updated_date_conf = max(updated_date_conf, 0.88)
        if not updated_date_iso:
            candidates = extractor._extract_candidates_from_lines(paddle_text.splitlines(), "paddle", 0.72)
            best = extractor._select_best_candidate(candidates)
            if best and best.get("date"):
                updated_date_iso = best["date"].strftime("%Y-%m-%d")
                updated_date_conf = max(updated_date_conf, _safe_float(best.get("confidence"), 0.72))

    return updated_supplier, updated_supplier_conf, updated_date_iso, updated_date_conf, True, ""


def analyze_pdf(pdf: Path, pages: int) -> Row:
    started = time.time()
    error = ""
    paddle_error = ""
    used_paddle = False

    textlayer_text, textlayer_words, text_err, render_err, text_pages, images = _ocr_and_signals(pdf, pages=pages)

    # OCR best + rotation
    rotation = ""
    rotation_reason = ""
    ocr_text = ""
    if images:
        try:
            ocr_info = extractor._ocr_images_best(images, force_best=False)
            rotation = str(ocr_info.get("rotation", ""))
            rotation_reason = str(ocr_info.get("rotation_reason", ""))
            ocr_text = str(ocr_info.get("text", ""))
            if ocr_info.get("error"):
                error = str(ocr_info.get("error"))
        except Exception as exc:
            error = f"ocr_failed: {exc}"
    else:
        error = render_err or text_err or "no_images"

    # Supplier: prefer textlayer, then OCR
    supplier = "Unbekannt"
    supplier_conf = 0.0
    supplier_source = "none"
    supplier_guess = ""
    if textlayer_text.strip():
        supplier, supplier_conf, supplier_source, supplier_guess = extractor.detect_supplier(textlayer_text)
    elif ocr_text.strip():
        supplier, supplier_conf, supplier_source, supplier_guess = extractor.detect_supplier(ocr_text)

    # Date
    date_iso = ""
    date_source = ""
    date_conf = 0.0
    date_evidence = ""
    try:
        pick = extractor.extract_best_date(pdf, images=images, textlayer_pages=text_pages, pages=pages)
        date_obj = pick.get("date")
        date_iso = date_obj.strftime("%Y-%m-%d") if date_obj else ""
        date_source = str(pick.get("source", ""))
        date_conf = _safe_float(pick.get("confidence"), 0.0)
        date_evidence = str(pick.get("evidence", "") or "")
    except Exception as exc:
        error = error or f"date_failed: {exc}"

    # Optional paddle fallback (only if enabled)
    supplier2, supplier_conf2, date_iso2, date_conf2, used_paddle, paddle_error = _maybe_paddle_fallback(
        images,
        supplier,
        supplier_conf,
        date_iso,
        date_conf,
    )
    if supplier2 != supplier:
        supplier = supplier2
        supplier_conf = supplier_conf2
        supplier_source = "paddle"
    if date_iso2 != date_iso:
        date_iso = date_iso2
        date_conf = date_conf2
        date_source = "paddle" if date_source == "" else f"{date_source}+paddle"

    elapsed_ms = int((time.time() - started) * 1000)

    return Row(
        filename=pdf.name,
        rotation=rotation,
        rotation_reason=rotation_reason,
        textlayer_words=textlayer_words,
        date_iso=date_iso or "-",
        date_source=date_source or "none",
        date_conf=date_conf,
        date_evidence=(date_evidence[:160] + "...") if len(date_evidence) > 160 else date_evidence,
        supplier=supplier or "Unbekannt",
        supplier_source=supplier_source,
        supplier_conf=supplier_conf,
        supplier_guess=(supplier_guess[:160] + "...") if len(supplier_guess) > 160 else supplier_guess,
        used_paddle=used_paddle,
        paddle_error=paddle_error,
        error=error,
        elapsed_ms=elapsed_ms,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-Report für eingehende PDFs (Datum/Lieferant/Rotation).")
    parser.add_argument("folder", type=str, help="Ordner mit PDFs")
    parser.add_argument("--pages", type=int, default=int(os.getenv("DOCARO_OCR_PAGES", "1")), help="Anzahl Seiten (default: env DOCARO_OCR_PAGES oder 1)")
    parser.add_argument("--out", type=str, default="", help="CSV Output-Pfad (default: data/logs/incoming_report_<timestamp>.csv)")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        print(f"Folder not found: {folder}")
        return 2

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print("No PDFs found.")
        return 0

    ts = time.strftime("%Y%m%d_%H%M%S")
    default_out = ROOT / "data" / "logs" / f"incoming_report_{ts}.csv"
    out_path = Path(args.out) if args.out else default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows: List[Row] = []
    errors = 0
    missing_date = 0
    missing_supplier = 0
    needs_review = 0

    print(f"Scanning {len(pdfs)} PDFs in: {folder}")
    requested = getattr(extractor, 'USE_PADDLEOCR', False)
    print(f"PaddleOCR requested: {requested}")
    if requested:
        try:
            available = bool(extractor._get_paddle_ocr())
        except Exception:
            available = False
        print(f"PaddleOCR available: {available}")

    for idx, pdf in enumerate(pdfs, start=1):
        r = analyze_pdf(pdf, pages=max(1, min(args.pages, 3)))
        rows.append(r)

        has_date = r.date_iso and r.date_iso != "-"
        has_supplier = r.supplier and r.supplier != "Unbekannt"
        ok = has_date and has_supplier and (r.error == "")
        if r.error:
            errors += 1
        if not has_date:
            missing_date += 1
        if not has_supplier:
            missing_supplier += 1
        date_conf_ok = (r.date_conf >= 0.75) or (r.date_source.startswith("filename_scan"))
        supplier_conf_ok = r.supplier_conf >= 0.70
        if (not ok) or (not date_conf_ok) or (not supplier_conf_ok):
            needs_review += 1

        if idx % 5 == 0 or idx == len(pdfs):
            print(f"  {idx}/{len(pdfs)} processed...")

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(
            [
                "filename",
                "rotation",
                "rotation_reason",
                "textlayer_words",
                "date",
                "date_source",
                "date_conf",
                "date_evidence",
                "supplier",
                "supplier_source",
                "supplier_conf",
                "supplier_guess",
                "used_paddle",
                "paddle_error",
                "error",
                "elapsed_ms",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.filename,
                    r.rotation,
                    r.rotation_reason,
                    r.textlayer_words,
                    r.date_iso,
                    r.date_source,
                    f"{r.date_conf:.2f}",
                    r.date_evidence,
                    r.supplier,
                    r.supplier_source,
                    f"{r.supplier_conf:.2f}",
                    r.supplier_guess,
                    "1" if r.used_paddle else "0",
                    r.paddle_error,
                    r.error,
                    r.elapsed_ms,
                ]
            )

    print("\nSummary:")
    print(f"  total: {len(rows)}")
    print(f"  missing_date: {missing_date}")
    print(f"  missing_supplier: {missing_supplier}")
    print(f"  errors: {errors}")
    print(f"  needs_review: {needs_review}")
    print(f"\nCSV written: {out_path}")

    # Print top review list
    print("\nNeeds review (first 15):")
    count = 0
    for r in rows:
        has_date = r.date_iso and r.date_iso != "-"
        has_supplier = r.supplier and r.supplier != "Unbekannt"
        ok = has_date and has_supplier and (r.error == "")
        date_conf_ok = (r.date_conf >= 0.75) or (r.date_source.startswith("filename_scan"))
        supplier_conf_ok = r.supplier_conf >= 0.70
        if (not ok) or (not date_conf_ok) or (not supplier_conf_ok):
            print(
                f"  {r.filename} | date={r.date_iso}({r.date_source},{r.date_conf:.2f}) | "
                f"supplier={r.supplier}({r.supplier_source},{r.supplier_conf:.2f}) | rot={r.rotation}({r.rotation_reason}) | err={r.error or r.paddle_error}"
            )
            count += 1
            if count >= 15:
                break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
