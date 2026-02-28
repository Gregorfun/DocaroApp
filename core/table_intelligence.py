from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib import error, request


_LOGGER = logging.getLogger(__name__)


@dataclass
class TableExtractionSummary:
    source: str
    tables_count: int
    rows_count: int
    preview: list[list[str]]
    text: str
    error: str = ""


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip()
    return " ".join(text.split())


def _normalize_rows(raw_rows: Iterable[Iterable[Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in raw_rows:
        clean = [_clean_cell(cell) for cell in row]
        if any(clean):
            rows.append(clean)
    return rows


def _rows_to_text(rows: Iterable[Iterable[str]], max_rows: int = 60) -> str:
    lines: list[str] = []
    for idx, row in enumerate(rows):
        if idx >= max_rows:
            break
        parts = [str(cell).strip() for cell in row if str(cell).strip()]
        if parts:
            lines.append(" | ".join(parts))
    return "\n".join(lines)


def _extract_local_tables(pdf_path: Path, max_pages: int) -> TableExtractionSummary:
    try:
        import pdfplumber  # type: ignore
    except Exception as exc:
        return TableExtractionSummary(
            source="none",
            tables_count=0,
            rows_count=0,
            preview=[],
            text="",
            error=f"pdfplumber_unavailable: {exc}",
        )

    all_rows: list[list[str]] = []
    tables_count = 0
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[: max(1, max_pages)]:
                page_tables = page.extract_tables() or []
                for table in page_tables:
                    rows = _normalize_rows(table or [])
                    if not rows:
                        continue
                    tables_count += 1
                    all_rows.extend(rows)
    except Exception as exc:
        return TableExtractionSummary(
            source="none",
            tables_count=0,
            rows_count=0,
            preview=[],
            text="",
            error=f"local_table_extract_failed: {exc}",
        )

    preview = all_rows[:10]
    return TableExtractionSummary(
        source="pdfplumber",
        tables_count=tables_count,
        rows_count=len(all_rows),
        preview=preview,
        text=_rows_to_text(all_rows),
    )


def _call_table_webhook(
    endpoint: str,
    pdf_path: Path,
    timeout_seconds: float,
) -> Optional[TableExtractionSummary]:
    payload = {"pdf_path": str(pdf_path)}
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=max(1.0, timeout_seconds)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except error.URLError as exc:
        _LOGGER.info("Table webhook not reachable (%s): %s", endpoint, exc)
        return None
    except Exception as exc:
        _LOGGER.info("Table webhook failed (%s): %s", endpoint, exc)
        return None

    try:
        data = json.loads(raw)
    except Exception:
        _LOGGER.info("Table webhook returned non-JSON response")
        return None

    rows = _normalize_rows(data.get("rows") or [])
    if not rows:
        return None
    source = str(data.get("source") or "hf_space_webhook")
    return TableExtractionSummary(
        source=source,
        tables_count=int(data.get("tables_count") or 1),
        rows_count=len(rows),
        preview=rows[:10],
        text=_rows_to_text(rows),
    )


def extract_table_intelligence(
    pdf_path: Path,
    *,
    enabled: bool = True,
    max_pages: int = 2,
) -> TableExtractionSummary:
    if not enabled:
        return TableExtractionSummary(
            source="disabled",
            tables_count=0,
            rows_count=0,
            preview=[],
            text="",
            error="disabled",
        )

    webhook = (os.getenv("DOCARO_HF_TABLE_WEBHOOK") or "").strip()
    timeout_seconds = float(os.getenv("DOCARO_HF_TABLE_TIMEOUT_SECONDS", "6") or "6")
    if webhook:
        remote = _call_table_webhook(webhook, pdf_path, timeout_seconds=timeout_seconds)
        if remote is not None:
            return remote

    return _extract_local_tables(pdf_path, max_pages=max_pages)
