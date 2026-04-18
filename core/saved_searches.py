"""Welle 13B: Saved-Searches – benannte Filter-Kombinationen pro User-Scope.

Speichert eine Liste von Suchen unter data/users/<scope>/saved_searches.json.
Jede Suche enthaelt: id, name, query, status, doctype, date_from, date_to, sort, created.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

REGISTRY_NAME = "saved_searches.json"
MAX_SEARCHES = 30
_NAME_MAX = 60
_LOCK = threading.RLock()

ALLOWED_STATUS = {"", "unvollstaendig", "in_bearbeitung", "fertig"}
ALLOWED_SORT = {"", "file_asc", "supplier_asc", "date_desc", "date_asc"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _registry_path(data_dir: Path, scope: str) -> Path:
    safe = scope or "system"
    return data_dir / "users" / safe / REGISTRY_NAME


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read(data_dir: Path, scope: str) -> list[dict[str, Any]]:
    path = _registry_path(data_dir, scope)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not sid or not name:
            continue
        out.append(_sanitize_entry(item))
    return out


def _write(data_dir: Path, scope: str, items: list[dict[str, Any]]) -> None:
    path = _registry_path(data_dir, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _sanitize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    status = str(entry.get("status") or "").strip()
    if status not in ALLOWED_STATUS:
        status = ""
    doctype = str(entry.get("doctype") or "").strip().upper()
    sort = str(entry.get("sort") or "").strip().lower()
    if sort not in ALLOWED_SORT:
        sort = ""
    date_from = str(entry.get("date_from") or "").strip()
    if date_from:
        if not _DATE_RE.match(date_from):
            date_from = ""
        else:
            try:
                datetime.strptime(date_from, "%Y-%m-%d")
            except ValueError:
                date_from = ""
    date_to = str(entry.get("date_to") or "").strip()
    if date_to:
        if not _DATE_RE.match(date_to):
            date_to = ""
        else:
            try:
                datetime.strptime(date_to, "%Y-%m-%d")
            except ValueError:
                date_to = ""
    name = str(entry.get("name") or "").strip()[:_NAME_MAX]
    query = str(entry.get("query") or "").strip()[:200]
    return {
        "id": str(entry.get("id") or "").strip(),
        "name": name,
        "query": query,
        "status": status,
        "doctype": doctype,
        "date_from": date_from,
        "date_to": date_to,
        "sort": sort,
        "created": str(entry.get("created") or "") or _now_iso(),
    }


def list_searches(data_dir: Path, scope: str) -> list[dict[str, Any]]:
    with _LOCK:
        return _read(data_dir, scope)


def create_search(data_dir: Path, scope: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Name darf nicht leer sein.")
    with _LOCK:
        items = _read(data_dir, scope)
        if len(items) >= MAX_SEARCHES:
            raise ValueError(f"Maximal {MAX_SEARCHES} gespeicherte Suchen.")
        entry = _sanitize_entry({**payload, "id": uuid.uuid4().hex[:12], "created": _now_iso()})
        if not entry["name"]:
            raise ValueError("Name darf nicht leer sein.")
        items.append(entry)
        _write(data_dir, scope, items)
        return entry


def delete_search(data_dir: Path, scope: str, sid: str) -> bool:
    sid = (sid or "").strip()
    if not sid:
        return False
    with _LOCK:
        items = _read(data_dir, scope)
        new = [it for it in items if it.get("id") != sid]
        if len(new) == len(items):
            return False
        _write(data_dir, scope, new)
        return True
