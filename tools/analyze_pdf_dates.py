from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

# Allow running from tools/
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import extractor

KEYWORDS = [
    "tag der liefer",
    "liefer",
    "beleg",
    "datum",
    "warenausgang",
    "bestellt",
    "document date",
    "delivery",
]


def _keyword_lines(text: str, max_lines: int = 20) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        l = line.strip()
        if not l:
            continue
        ll = l.lower()
        if any(k in ll for k in KEYWORDS) or extractor.NUMERIC_DATE_REGEX.search(l) or extractor.ISO_DATE_REGEX.search(l):
            out.append(l)
        if len(out) >= max_lines:
            break
    return out


def analyze(pdf_path: Path, dpi: int = 300) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "pdf": str(pdf_path),
        "exists": pdf_path.exists(),
        "render_error": "",
        "rotations": [],
        "textlayer": {
            "error": "",
            "words": 0,
            "sample": "",
        },
    }
    if not pdf_path.exists():
        return result

    # text layer
    pages, err = extractor._extract_textlayer(pdf_path, pages=1)
    textlayer_text = "\n".join(pages) if pages else ""
    result["textlayer"]["error"] = err
    result["textlayer"]["words"] = len(textlayer_text.split())
    result["textlayer"]["sample"] = textlayer_text[:500]

    images, render_err = extractor._render_pdf_images(pdf_path, extractor._POPPLER_BIN, pages=1)
    result["render_error"] = render_err
    if not images:
        return result

    img = images[0]

    for rot in (0, 90, 180, 270):
        entry: Dict[str, Any] = {"rotation": rot}
        try:
            text = extractor._ocr_image(img, rotation=rot, config="--psm 6")
        except Exception as e:
            entry["ocr_error"] = f"{type(e).__name__}: {e}"
            result["rotations"].append(entry)
            continue

        candidates = extractor._extract_candidates_from_lines(text.splitlines(), f"full_ocr_rot_{rot}", 0.55)
        best = extractor._select_best_candidate(candidates)
        entry["best"] = None
        if best:
            dt = best.get("date")
            entry["best"] = {
                "raw": best.get("raw"),
                "label": best.get("label"),
                "confidence": float(best.get("confidence", 0.0) or 0.0),
                "evidence": best.get("evidence"),
                "source": best.get("source"),
                "date": dt.strftime("%Y-%m-%d") if dt else None,
                "priority": int(best.get("priority", 99) or 99),
            }
        entry["keyword_lines"] = _keyword_lines(text)
        # also store a short snippet
        entry["snippet"] = text[:800]
        result["rotations"].append(entry)

    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tools/analyze_pdf_dates.py <pdf1> [<pdf2> ...]")
        return 2

    out_dir = ROOT / "data" / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)

    for raw in sys.argv[1:]:
        pdf = Path(raw)
        data = analyze(pdf)
        out_path = out_dir / f"diag_{pdf.stem}.json"
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(str(out_path))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
