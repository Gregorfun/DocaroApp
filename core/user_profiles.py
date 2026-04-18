"""Welle 10: Multi-User & Profile-Switching.

Verwaltet mehrere lokale Benutzerprofile fuer den Desktop-Modus. Jedes Profil
hat eine eigene Scope-Id (`profile_<id>`), unter der `recent.json`/`prefs.json`
sowie die Backups (Welle 9) abgelegt werden.

Registry liegt unter ``data/profiles.json``::

    {
        "version": 1,
        "active": "default",
        "profiles": [
            {"id": "default", "label": "Standard", "created": "2026-04-18T10:00:00"}
        ]
    }
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)
_LOCK = threading.RLock()

REGISTRY_NAME = "profiles.json"
DEFAULT_PROFILE_ID = "default"
DEFAULT_PROFILE_LABEL = "Standard"
SCOPE_PREFIX = "profile_"
MAX_PROFILES = 8
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_LABEL_MAX = 40


def _registry_path(data_dir: Path) -> Path:
    return data_dir / REGISTRY_NAME


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _default_registry() -> dict[str, Any]:
    return {
        "version": 1,
        "active": DEFAULT_PROFILE_ID,
        "profiles": [
            {"id": DEFAULT_PROFILE_ID, "label": DEFAULT_PROFILE_LABEL, "created": _now_iso()}
        ],
    }


def _read_registry(data_dir: Path) -> dict[str, Any]:
    path = _registry_path(data_dir)
    if not path.is_file():
        return _default_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _LOGGER.warning("user_profiles: registry unreadable, using default (%s)", exc)
        return _default_registry()
    if not isinstance(data, dict):
        return _default_registry()
    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        return _default_registry()
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in profiles:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        if not _ID_RE.match(pid) or pid in seen:
            continue
        label = str(item.get("label") or pid)[:_LABEL_MAX]
        created = str(item.get("created") or _now_iso())
        cleaned.append({"id": pid, "label": label, "created": created})
        seen.add(pid)
    if not cleaned:
        return _default_registry()
    active = str(data.get("active") or "").strip()
    if active not in seen:
        active = cleaned[0]["id"]
    return {"version": 1, "active": active, "profiles": cleaned}


def _write_registry(data_dir: Path, registry: dict[str, Any]) -> None:
    path = _registry_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_profiles(data_dir: Path) -> dict[str, Any]:
    """Liste aller Profile + aktives Profil."""
    with _LOCK:
        reg = _read_registry(data_dir)
    return {"active": reg["active"], "profiles": list(reg["profiles"])}


def get_active_id(data_dir: Path) -> str:
    return list_profiles(data_dir)["active"]


def scope_for(profile_id: str) -> str:
    return f"{SCOPE_PREFIX}{profile_id}"


def active_scope(data_dir: Path) -> str:
    return scope_for(get_active_id(data_dir))


def _slugify_label(label: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    return (base or "profil")[:24]


def create_profile(data_dir: Path, label: str) -> dict[str, Any]:
    label = (label or "").strip()
    if not label:
        return {"ok": False, "error": "Label fehlt."}
    if len(label) > _LABEL_MAX:
        return {"ok": False, "error": f"Label zu lang (max. {_LABEL_MAX})."}
    with _LOCK:
        reg = _read_registry(data_dir)
        if len(reg["profiles"]) >= MAX_PROFILES:
            return {"ok": False, "error": f"Maximal {MAX_PROFILES} Profile erlaubt."}
        existing_ids = {p["id"] for p in reg["profiles"]}
        base_id = _slugify_label(label)
        pid = base_id
        n = 2
        while pid in existing_ids:
            pid = f"{base_id}_{n}"
            n += 1
        entry = {"id": pid, "label": label, "created": _now_iso()}
        reg["profiles"].append(entry)
        _write_registry(data_dir, reg)
    return {"ok": True, "profile": entry}


def rename_profile(data_dir: Path, profile_id: str, new_label: str) -> dict[str, Any]:
    new_label = (new_label or "").strip()
    if not new_label:
        return {"ok": False, "error": "Label fehlt."}
    if len(new_label) > _LABEL_MAX:
        return {"ok": False, "error": f"Label zu lang (max. {_LABEL_MAX})."}
    with _LOCK:
        reg = _read_registry(data_dir)
        for prof in reg["profiles"]:
            if prof["id"] == profile_id:
                prof["label"] = new_label
                _write_registry(data_dir, reg)
                return {"ok": True, "profile": prof}
    return {"ok": False, "error": "Profil nicht gefunden."}


def activate_profile(data_dir: Path, profile_id: str) -> dict[str, Any]:
    with _LOCK:
        reg = _read_registry(data_dir)
        ids = {p["id"] for p in reg["profiles"]}
        if profile_id not in ids:
            return {"ok": False, "error": "Profil nicht gefunden."}
        reg["active"] = profile_id
        _write_registry(data_dir, reg)
    return {"ok": True, "active": profile_id}


def delete_profile(data_dir: Path, profile_id: str) -> dict[str, Any]:
    with _LOCK:
        reg = _read_registry(data_dir)
        if len(reg["profiles"]) <= 1:
            return {"ok": False, "error": "Letztes Profil kann nicht geloescht werden."}
        target = next((p for p in reg["profiles"] if p["id"] == profile_id), None)
        if target is None:
            return {"ok": False, "error": "Profil nicht gefunden."}
        reg["profiles"] = [p for p in reg["profiles"] if p["id"] != profile_id]
        if reg["active"] == profile_id:
            reg["active"] = reg["profiles"][0]["id"]
        _write_registry(data_dir, reg)
        # Profil-Datenverzeichnis aufraeumen (best-effort)
        scope_dir = data_dir / "users" / scope_for(profile_id)
        try:
            if scope_dir.is_dir():
                shutil.rmtree(scope_dir, ignore_errors=True)
        except OSError as exc:  # noqa: BLE001
            _LOGGER.warning("user_profiles: cleanup of %s failed: %s", scope_dir, exc)
    return {"ok": True, "active": reg["active"], "deleted": profile_id}
