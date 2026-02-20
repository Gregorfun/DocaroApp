#!/usr/bin/env python3
"""Pilot für granite-docling-258M via Docling VLM-Pipeline."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

os.environ.setdefault("TORCHINDUCTOR_DISABLE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _run_granite_docling(source: str):
    from docling.datamodel import vlm_model_specs
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import VlmPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.pipeline.vlm_pipeline import VlmPipeline

    pipeline_options = VlmPipelineOptions(
        vlm_options=vlm_model_specs.GRANITEDOCLING_TRANSFORMERS,
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=VlmPipeline,
                pipeline_options=pipeline_options,
            ),
        }
    )
    return converter.convert(source=source).document


def main() -> int:
    parser = argparse.ArgumentParser(description="Pilot für ibm-granite/granite-docling-258M")
    parser.add_argument("--source", required=True, help="PDF-Datei oder URL")
    parser.add_argument(
        "--out-dir",
        default="artifacts/granite_docling",
        help="Ausgabeverzeichnis für Markdown/JSON",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    start = time.time()
    doc = _run_granite_docling(args.source)
    elapsed = time.time() - start

    stem = Path(args.source).stem if "://" not in args.source else "remote_pdf"
    out_md = out_dir / f"{stem}.granite.md"
    out_json = out_dir / f"{stem}.granite.json"
    out_meta = out_dir / f"{stem}.meta.json"

    md_text = doc.export_to_markdown()
    out_md.write_text(md_text, encoding="utf-8")
    if hasattr(doc, "export_to_dict"):
        payload = doc.export_to_dict()
    elif hasattr(doc, "model_dump"):
        payload = doc.model_dump()
    else:
        payload = {"repr": str(doc)}
    out_json.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    out_meta.write_text(
        json.dumps(
            {
                "source": args.source,
                "model": "ibm-granite/granite-docling-258M",
                "pipeline": "docling-vlm",
                "processing_seconds": round(elapsed, 3),
                "markdown_chars": len(md_text),
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"OK: {out_md}")
    print(f"OK: {out_json}")
    print(f"OK: {out_meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
