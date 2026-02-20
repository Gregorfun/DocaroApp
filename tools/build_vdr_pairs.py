#!/usr/bin/env python3
"""Erzeugt Benchmark-Paare fuer Visual-Document-Retrieval."""

from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")


@dataclass
class DocItem:
    path: Path
    supplier: str
    date: str
    doc_number: str
    doctype: str


def _clean_text(s: str) -> str:
    s = s.replace("_", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _parse_from_filename(path: Path) -> Optional[DocItem]:
    stem = path.stem
    parts = stem.split("_")
    if len(parts) < 3:
        return None

    date_idx = None
    for i, part in enumerate(parts):
        if DATE_RE.match(part):
            date_idx = i
            break
    if date_idx is None or date_idx == 0:
        return None

    supplier = _clean_text("_".join(parts[:date_idx]))
    date = parts[date_idx]
    doc_number = _clean_text("_".join(parts[date_idx + 1 :])) or "ohneNr"

    return DocItem(
        path=path,
        supplier=supplier,
        date=date,
        doc_number=doc_number,
        doctype="LIEFERSCHEIN",
    )


def _audit_overrides(audit_path: Path) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    if not audit_path.exists():
        return out

    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue

        document_path = entry.get("document_path") or ""
        if not document_path:
            continue
        name = Path(document_path).name

        extractions = entry.get("extractions") or {}
        supplier = ((extractions.get("supplier") or {}).get("value") or "").strip()
        date_iso = ((extractions.get("date") or {}).get("value") or "").strip()
        doctype = ((extractions.get("doctype") or {}).get("value") or "").strip()

        date = ""
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_iso):
            y, m, d = date_iso.split("-")
            date = f"{d}-{m}-{y}"

        payload = out.setdefault(name, {})
        if supplier:
            payload["supplier"] = supplier
        if date:
            payload["date"] = date
        if doctype:
            payload["doctype"] = doctype

    return out


def _make_query(item: DocItem) -> str:
    return (
        f"{item.doctype} von {item.supplier} "
        f"vom {item.date} mit Nummer {item.doc_number}"
    )


def _make_document(item: DocItem) -> str:
    return (
        f"Datei: {item.path.name}. "
        f"Lieferant: {item.supplier}. "
        f"Datum: {item.date}. "
        f"Belegnummer: {item.doc_number}. "
        f"Dokumenttyp: {item.doctype}."
    )


def build_pairs(
    source_dir: Path,
    audit_path: Path,
    output_path: Path,
    max_docs: int,
    negatives_per_positive: int,
    seed: int,
) -> Dict[str, int]:
    rng = random.Random(seed)

    parsed: List[DocItem] = []
    overrides = _audit_overrides(audit_path)

    for pdf in sorted(source_dir.glob("*.pdf")):
        item = _parse_from_filename(pdf)
        if not item:
            continue
        ov = overrides.get(pdf.name, {})
        if ov.get("supplier"):
            item.supplier = _clean_text(ov["supplier"])
        if ov.get("date"):
            item.date = ov["date"]
        if ov.get("doctype"):
            item.doctype = _clean_text(ov["doctype"]).upper()
        parsed.append(item)

    if max_docs > 0:
        parsed = parsed[:max_docs]
    if len(parsed) < 2:
        raise ValueError("Zu wenige PDFs fuer Benchmark-Paare gefunden.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    positives = 0
    negatives = 0
    with output_path.open("w", encoding="utf-8") as f:
        for item in parsed:
            q = _make_query(item)
            d = _make_document(item)
            f.write(json.dumps({"query": q, "document": d, "label": 1}, ensure_ascii=True) + "\n")
            positives += 1

            candidates = [x for x in parsed if x.path != item.path and x.supplier != item.supplier]
            if not candidates:
                candidates = [x for x in parsed if x.path != item.path]
            rng.shuffle(candidates)
            for neg in candidates[: max(0, negatives_per_positive)]:
                f.write(
                    json.dumps(
                        {"query": q, "document": _make_document(neg), "label": 0},
                        ensure_ascii=True,
                    )
                    + "\n"
                )
                negatives += 1

    return {
        "documents": len(parsed),
        "positives": positives,
        "negatives": negatives,
        "total_pairs": positives + negatives,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Erzeuge VDR-Paare aus Docaro-PDFs")
    parser.add_argument("--source-dir", default="data/fertig", type=Path)
    parser.add_argument("--audit", default="data/audit.jsonl", type=Path)
    parser.add_argument("--output", default="data/ml/vdr_pairs.jsonl", type=Path)
    parser.add_argument("--max-docs", default=200, type=int)
    parser.add_argument("--neg-per-pos", default=1, type=int)
    parser.add_argument("--seed", default=42, type=int)
    args = parser.parse_args()

    stats = build_pairs(
        source_dir=args.source_dir,
        audit_path=args.audit,
        output_path=args.output,
        max_docs=args.max_docs,
        negatives_per_positive=args.neg_per_pos,
        seed=args.seed,
    )
    print(json.dumps(stats, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
