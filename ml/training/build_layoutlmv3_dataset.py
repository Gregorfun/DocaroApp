"""Build a real LayoutLMv3 dataset from Docaro PDFs.

Output format: JSONL with one sample per PDF first page:
{
  "id": "...",
  "pdf_path": "...",
  "image_path": "...png",
  "words": ["..."],
  "boxes": [[x1,y1,x2,y2], ...],   # normalized to 0..1000
  "labels": {"supplier": "...", ...},
  "label": "..."                    # selected by --label-field
}
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image
import pytesseract


DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")


@dataclass
class ParsedName:
    supplier: str
    date: str
    doc_number: str
    doc_type: str


def _clean(s: str) -> str:
    s = s.replace("_", " ").strip()
    return re.sub(r"\s+", " ", s)


def _parse_filename(pdf_path: Path) -> Optional[ParsedName]:
    parts = pdf_path.stem.split("_")
    if len(parts) < 3:
        return None
    idx = None
    for i, part in enumerate(parts):
        if DATE_RE.match(part):
            idx = i
            break
    if idx is None or idx == 0:
        return None
    supplier = _clean("_".join(parts[:idx]))
    date = parts[idx]
    doc_number = _clean("_".join(parts[idx + 1 :])) or "ohneNr"
    return ParsedName(
        supplier=supplier,
        date=date,
        doc_number=doc_number,
        doc_type="LIEFERSCHEIN",
    )


def _norm_box(x0: float, y0: float, x1: float, y1: float, width: float, height: float) -> List[int]:
    def clamp(v: float, lo: int = 0, hi: int = 1000) -> int:
        return max(lo, min(hi, int(round(v))))

    if width <= 0 or height <= 0:
        return [0, 0, 1, 1]
    nx0 = clamp((x0 / width) * 1000.0)
    ny0 = clamp((y0 / height) * 1000.0)
    nx1 = clamp((x1 / width) * 1000.0)
    ny1 = clamp((y1 / height) * 1000.0)
    if nx1 <= nx0:
        nx1 = min(1000, nx0 + 1)
    if ny1 <= ny0:
        ny1 = min(1000, ny0 + 1)
    return [nx0, ny0, nx1, ny1]


def _extract_page_words(page: fitz.Page) -> Tuple[List[str], List[List[int]]]:
    words = page.get_text("words") or []
    page_rect = page.rect
    width, height = float(page_rect.width), float(page_rect.height)
    out_words: List[str] = []
    out_boxes: List[List[int]] = []
    for item in words:
        x0, y0, x1, y1, word = item[0], item[1], item[2], item[3], str(item[4]).strip()
        if not word:
            continue
        out_words.append(word)
        out_boxes.append(_norm_box(x0, y0, x1, y1, width, height))
    return out_words, out_boxes


def _extract_ocr_words(image: Image.Image) -> Tuple[List[str], List[List[int]]]:
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    width, height = image.size
    out_words: List[str] = []
    out_boxes: List[List[int]] = []
    n = len(data.get("text", []))
    for i in range(n):
        word = str(data["text"][i]).strip()
        conf = str(data.get("conf", ["-1"] * n)[i]).strip()
        try:
            conf_v = float(conf)
        except Exception:
            conf_v = -1.0
        if not word or conf_v < 0:
            continue
        x, y, w, h = (
            float(data["left"][i]),
            float(data["top"][i]),
            float(data["width"][i]),
            float(data["height"][i]),
        )
        out_words.append(word)
        out_boxes.append(_norm_box(x, y, x + w, y + h, width, height))
    return out_words, out_boxes


def _render_page_image(page: fitz.Page, dpi: int) -> Image.Image:
    scale = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def build_dataset(
    source_dir: Path,
    output_jsonl: Path,
    images_dir: Path,
    label_field: str,
    max_docs: int,
    min_words: int,
    dpi: int,
    ocr_fallback: bool,
) -> Dict[str, int]:
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_name = 0
    skipped_words = 0
    ocr_used = 0

    pdfs = sorted(source_dir.glob("*.pdf"))
    if max_docs > 0:
        pdfs = pdfs[:max_docs]

    with output_jsonl.open("w", encoding="utf-8") as out:
        for pdf in pdfs:
            parsed = _parse_filename(pdf)
            if parsed is None:
                skipped_name += 1
                continue

            doc = fitz.open(pdf)
            if doc.page_count == 0:
                skipped_words += 1
                continue
            page = doc[0]
            image = _render_page_image(page, dpi=dpi)
            words, boxes = _extract_page_words(page)

            if len(words) < min_words and ocr_fallback:
                o_words, o_boxes = _extract_ocr_words(image)
                if len(o_words) > len(words):
                    words, boxes = o_words, o_boxes
                    ocr_used += 1

            if len(words) < min_words:
                skipped_words += 1
                continue

            labels = {
                "supplier": parsed.supplier,
                "doc_type": parsed.doc_type,
                "doc_date_iso": parsed.date,
                "doc_number": parsed.doc_number,
            }
            label = labels.get(label_field, "")
            if not label:
                skipped_name += 1
                continue

            img_path = images_dir / f"{pdf.stem}.page1.png"
            image.save(img_path)

            payload = {
                "id": pdf.stem,
                "pdf_path": str(pdf),
                "image_path": str(img_path),
                "words": words,
                "boxes": boxes,
                "labels": labels,
                "label": label,
            }
            out.write(json.dumps(payload, ensure_ascii=True) + "\n")
            written += 1

    return {
        "pdf_total": len(pdfs),
        "samples_written": written,
        "skipped_filename": skipped_name,
        "skipped_words": skipped_words,
        "ocr_used": ocr_used,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build real LayoutLMv3 dataset from Docaro PDFs")
    parser.add_argument("--source-dir", type=Path, default=Path("data/fertig"))
    parser.add_argument("--output-jsonl", type=Path, default=Path("artifacts/layoutlmv3/dataset_supplier.jsonl"))
    parser.add_argument("--images-dir", type=Path, default=Path("artifacts/layoutlmv3/images"))
    parser.add_argument(
        "--label-field",
        type=str,
        default="supplier",
        choices=["supplier", "doc_type", "doc_date_iso", "doc_number"],
    )
    parser.add_argument("--max-docs", type=int, default=120)
    parser.add_argument("--min-words", type=int, default=6)
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--ocr-fallback", action="store_true")
    args = parser.parse_args()

    stats = build_dataset(
        source_dir=args.source_dir,
        output_jsonl=args.output_jsonl,
        images_dir=args.images_dir,
        label_field=args.label_field,
        max_docs=args.max_docs,
        min_words=args.min_words,
        dpi=args.dpi,
        ocr_fallback=args.ocr_fallback,
    )
    print(json.dumps(stats, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
