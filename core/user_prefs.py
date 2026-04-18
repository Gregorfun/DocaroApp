"""User-Prefs Store: lernt persistente Defaults pro User.

Persistiert pro User unter ``data/users/<scope>/prefs.json``:

- last_date_fmt           : str        – zuletzt gewähltes Datumsformat
- last_doctype            : str        – zuletzt gewählter Doctype
- recent_suppliers        : list[str]  – Top-N Lieferanten (häufigkeitssortiert)
- doctype_per_supplier    : dict[str, str] – pro Lieferant zuletzt gewählter Doctype
- updated_at              : str        – ISO-Zeitstempel
"""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)
_LOCK = threading.Lock()

#: Anzahl der zuletzt gemerkten Lieferanten (für Quick-Picks)
MAX_RECENT_SUPPLIERS = 10

#: Erlaubte Datumsformate (Whitelist gegen Stringinjection in Templates).
ALLOWED_DATE_FORMATS = {"%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y%m%d"}

#: Welle 11: erlaubte UI-Theme-Modi.
ALLOWED_UI_THEMES = {"auto", "light", "dark"}

DEFAULT_PREFS: dict[str, Any] = {
    "last_date_fmt": "%d-%m-%Y",
    "last_doctype": "",
    "recent_suppliers": [],
    "doctype_per_supplier": {},
    "supplier_counts": {},
    "tour_done": False,
    "ui_theme": "auto",
    "filename_template": "",
    "results_sort": "",
    "updated_at": "",
}


def _prefs_path(data_dir: Path, scope: str) -> Path:
    safe_scope = scope or "system"
    return data_dir / "users" / safe_scope / "prefs.json"


def load_prefs(data_dir: Path, scope: str) -> dict[str, Any]:
    """Lädt User-Prefs (mit Defaults gemerged). Keine Exceptions nach außen."""
    path = _prefs_path(data_dir, scope)
    prefs: dict[str, Any] = dict(DEFAULT_PREFS)
    prefs["recent_suppliers"] = []
    prefs["doctype_per_supplier"] = {}
    prefs["supplier_counts"] = {}
    if not path.exists():
        return prefs
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _LOGGER.warning("user_prefs konnten nicht gelesen werden (%s): %s", path, exc)
        return prefs
    if not isinstance(raw, dict):
        return prefs
    for key, default_value in DEFAULT_PREFS.items():
        value = raw.get(key, default_value)
        if isinstance(default_value, list) and not isinstance(value, list):
            value = []
        if isinstance(default_value, dict) and not isinstance(value, dict):
            value = {}
        prefs[key] = value
    return prefs


def _save_prefs(data_dir: Path, scope: str, prefs: dict[str, Any]) -> None:
    path = _prefs_path(data_dir, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    prefs["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def update_prefs(data_dir: Path, scope: str, **changes: Any) -> dict[str, Any]:
    """Merged ``changes`` in die User-Prefs und speichert sie.

    Erlaubte Keys: ``last_date_fmt``, ``last_doctype``.
    Andere Keys werden ignoriert.
    """
    with _LOCK:
        prefs = load_prefs(data_dir, scope)
        if "last_date_fmt" in changes:
            value = str(changes["last_date_fmt"] or "").strip()
            if value in ALLOWED_DATE_FORMATS:
                prefs["last_date_fmt"] = value
        if "last_doctype" in changes:
            value = str(changes["last_doctype"] or "").strip()
            if value:
                prefs["last_doctype"] = value
        if "tour_done" in changes:
            prefs["tour_done"] = bool(changes["tour_done"])
        if "ui_theme" in changes:
            value = str(changes["ui_theme"] or "").strip().lower()
            if value in ALLOWED_UI_THEMES:
                prefs["ui_theme"] = value
        if "filename_template" in changes:
            from core import naming_templates as _nt
            value = str(changes["filename_template"] or "").strip()
            if not value:
                prefs["filename_template"] = ""
            elif _nt.is_valid_template(value):
                prefs["filename_template"] = value
        if "results_sort" in changes:
            value = str(changes["results_sort"] or "").strip().lower()
            if value in {"", "file_asc", "supplier_asc", "date_desc", "date_asc"}:
                prefs["results_sort"] = value
        try:
            _save_prefs(data_dir, scope, prefs)
        except Exception as exc:
            _LOGGER.warning("user_prefs konnten nicht geschrieben werden: %s", exc)
        return prefs


def record_supplier_use(
    data_dir: Path,
    scope: str,
    supplier: str,
    *,
    doctype: str = "",
) -> dict[str, Any]:
    """Trackt einen Supplier-Use und (optional) den dazugehörigen Doctype."""
    name = (supplier or "").strip()
    if not name:
        return load_prefs(data_dir, scope)
    with _LOCK:
        prefs = load_prefs(data_dir, scope)
        counts = prefs.get("supplier_counts") or {}
        counts[name] = int(counts.get(name, 0)) + 1
        # Nur Top-N behalten, sonst wächst der Store unbegrenzt.
        top = Counter(counts).most_common(MAX_RECENT_SUPPLIERS * 2)
        counts = {n: c for n, c in top}
        prefs["supplier_counts"] = counts
        prefs["recent_suppliers"] = [n for n, _ in top[:MAX_RECENT_SUPPLIERS]]
        if doctype:
            mapping = prefs.get("doctype_per_supplier") or {}
            mapping[name] = doctype
            prefs["doctype_per_supplier"] = mapping
            prefs["last_doctype"] = doctype
        try:
            _save_prefs(data_dir, scope, prefs)
        except Exception as exc:
            _LOGGER.warning("user_prefs konnten nicht geschrieben werden: %s", exc)
        return prefs


def record_doctype_use(data_dir: Path, scope: str, doctype: str) -> dict[str, Any]:
    """Trackt einen Doctype-Use (ohne Supplier-Bindung)."""
    value = (doctype or "").strip()
    if not value:
        return load_prefs(data_dir, scope)
    with _LOCK:
        prefs = load_prefs(data_dir, scope)
        prefs["last_doctype"] = value
        try:
            _save_prefs(data_dir, scope, prefs)
        except Exception as exc:
            _LOGGER.warning("user_prefs konnten nicht geschrieben werden: %s", exc)
        return prefs
