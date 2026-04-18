"""Per-User Store für zuletzt verarbeitete Dateien (Recent Files Panel)."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)
_LOCK = threading.Lock()

MAX_ENTRIES = 20
ALLOWED_KINDS = {"merge", "split", "compress", "ocr", "upload", "autosort"}


def _safe_scope(scope: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in (scope or ""))
    return cleaned.strip("_") or "system"


def _store_path(data_dir: Path, scope: str) -> Path:
    base = data_dir / "users" / _safe_scope(scope) / "recent.json"
    base.parent.mkdir(parents=True, exist_ok=True)
    return base


def load_recent(data_dir: Path, scope: str) -> list[dict[str, Any]]:
    path = _store_path(data_dir, scope)
    if not path.exists():
        return []
    try:
        with _LOCK:
            data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except (json.JSONDecodeError, OSError) as exc:
        _LOGGER.warning("recent_store load failed for %s: %s", scope, exc)
    return []


def add_recent(
    data_dir: Path,
    scope: str,
    *,
    kind: str,
    filename: str,
    path: str = "",
    download_token: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    if kind not in ALLOWED_KINDS:
        return
    entry = {
        "kind": kind,
        "filename": filename or "datei",
        "path": path or "",
        "download_token": download_token or "",
        "ts": time.time(),
    }
    if extra:
        for k, v in extra.items():
            if isinstance(k, str) and k not in entry and isinstance(v, (str, int, float, bool)):
                entry[k] = v

    store = _store_path(data_dir, scope)
    with _LOCK:
        try:
            existing = []
            if store.exists():
                existing = json.loads(store.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            existing.insert(0, entry)
            existing = existing[:MAX_ENTRIES]
            store.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            _LOGGER.warning("recent_store write failed for %s: %s", scope, exc)


def clear_recent(data_dir: Path, scope: str) -> None:
    path = _store_path(data_dir, scope)
    with _LOCK:
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            _LOGGER.warning("recent_store clear failed for %s: %s", scope, exc)
