from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

# Avoid Windows console encoding crashes when printing OCR output.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import extractor  # noqa: E402


def _summarize(text: str, max_chars: int = 700) -> str:
    text = (text or "").strip()
    text = " ".join(text.split())
    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def inspect(pdf: Path, pages: int = 1) -> None:
    images, err = extractor._render_pdf_images(pdf, extractor._POPPLER_BIN, pages=pages)
    print(f"PDF: {pdf.name}")
    print(f"render_err: {err}")
    if not images:
        return

    img = images[0]

    print("\nTesseract rotation candidates (ROI scoring):")
    try:
        cands = extractor._rotation_candidates_from_crops(img)
        print("  " + ", ".join([f"{rot}:{score}" for rot, score in cands[:4]]))
    except Exception as exc:
        print(f"  failed: {exc}")

    for rot in (0, 90, 180, 270):
        print(f"\n=== Rotation {rot} ===")
        try:
            roi_texts = extractor._ocr_rois(img, rot, ["roi1", "roi2", "roi4"])
            roi_combined = "\n".join(roi_texts)
            roi_score = extractor._score_rotation_text(roi_combined)
            roi_date_hits = extractor._count_date_hits(roi_combined)
            print(f"ROI: score={roi_score} date_hits={roi_date_hits}")
            print(f"ROI text: { _summarize(roi_combined) }")
        except Exception as exc:
            print(f"ROI failed: {exc}")

        try:
            full = extractor._ocr_image(img, rot, timeout=extractor.OCR_TIMEOUT_SECONDS)
            full_score = extractor._score_rotation_text(full)
            full_date_hits = extractor._count_date_hits(full)
            print(f"FULL: score={full_score} date_hits={full_date_hits}")
            print(f"FULL text: { _summarize(full) }")
        except Exception as exc:
            print(f"FULL failed: {exc}")

    # Also try date parser directly on best ocr
    try:
        best = extractor._ocr_single_image(img, force_best=False)
        best_text = best.get("text", "")
        print("\nBest single-image OCR:")
        print(f"  rotation={best.get('rotation')} reason={best.get('rotation_reason')} score={best.get('score')}")
        if extractor.date_parser and best_text:
            dp_iso, dp_reason = extractor.date_parser.extract_date_from_text(best_text)
            print(f"  date_parser: {dp_iso} ({dp_reason})")
        s, c, src, guess = extractor.detect_supplier(best_text or "")
        print(f"  supplier: {s} ({src},{c:.2f}) guess={guess}")
    except Exception as exc:
        print(f"Best OCR failed: {exc}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/inspect_pdf.py <pdf>")
        raise SystemExit(2)
    inspect(Path(sys.argv[1]), pages=1)
