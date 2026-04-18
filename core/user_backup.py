"""User-Backup: Snapshots + Export/Import der per-User-Daten.

Pro User-Scope werden die "leichten" JSON-Dateien gesichert:

- ``data/users/<scope>/prefs.json``      (Smart Defaults aus core.user_prefs)
- ``data/users/<scope>/recent.json``     (Recent-Files aus core.recent_store)

Snapshots landen unter ``data/users/<scope>/backups/backup-<ts>.zip`` und werden
auf ``MAX_BACKUPS`` Eintraege gerollt. Export/Import nutzt das gleiche ZIP-Format.

Welle 9: Datenpflege & Backup.
"""

from __future__ import annotations

import io
import json
import logging
import re
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)
_LOCK = threading.RLock()

#: Welche Dateien (Pfad relativ zum Scope-Verzeichnis) werden gesichert.
TRACKED_FILES = ("prefs.json", "recent.json")

#: Wieviele Snapshots maximal pro User behalten werden.
MAX_BACKUPS = 10

#: Maximalgroesse einer hochgeladenen Backup-ZIP (5 MB reicht fuer JSON-Daten).
MAX_IMPORT_BYTES = 5 * 1024 * 1024

_TS_FMT = "%Y%m%d-%H%M%S"
_BACKUP_NAME_RE = re.compile(r"^backup-(\d{8}-\d{6})\.zip$")


def _safe_scope(scope: str) -> str:
    s = (scope or "").strip()
    if not s:
        return "system"
    # nur ASCII-Letters/Digits/_-., kein Pfadtrenner
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", s)


def _scope_dir(data_dir: Path, scope: str) -> Path:
    return data_dir / "users" / _safe_scope(scope)


def _backups_dir(data_dir: Path, scope: str) -> Path:
    return _scope_dir(data_dir, scope) / "backups"


def _collect_payload(scope_dir: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for name in TRACKED_FILES:
        path = scope_dir / name
        if path.exists() and path.is_file():
            try:
                out[name] = path.read_bytes()
            except OSError as exc:
                _LOGGER.warning("user_backup: cannot read %s: %s", path, exc)
    return out


def _write_zip(payload: dict[str, bytes], scope: str) -> bytes:
    buf = io.BytesIO()
    meta = {
        "scope": _safe_scope(scope),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files": sorted(payload.keys()),
        "version": 1,
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docaro-backup.json", json.dumps(meta, ensure_ascii=False, indent=2))
        for name, data in payload.items():
            zf.writestr(name, data)
    return buf.getvalue()


def create_backup(data_dir: Path, scope: str) -> dict[str, Any]:
    """Erzeugt Snapshot-ZIP, prunet auf MAX_BACKUPS. Gibt Metadaten zurueck."""
    with _LOCK:
        scope_dir = _scope_dir(data_dir, scope)
        scope_dir.mkdir(parents=True, exist_ok=True)
        payload = _collect_payload(scope_dir)
        if not payload:
            return {"ok": False, "error": "Keine User-Daten vorhanden."}
        bdir = _backups_dir(data_dir, scope)
        bdir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime(_TS_FMT)
        target = bdir / f"backup-{ts}.zip"
        # bei Kollision (gleicher Sekundenstempel) Suffix anhaengen
        idx = 1
        while target.exists():
            target = bdir / f"backup-{ts}-{idx}.zip"
            idx += 1
        target.write_bytes(_write_zip(payload, scope))
        prune_backups(data_dir, scope, keep=MAX_BACKUPS)
        return {
            "ok": True,
            "name": target.name,
            "size": target.stat().st_size,
            "files": sorted(payload.keys()),
            "created": ts,
        }


def list_backups(data_dir: Path, scope: str) -> list[dict[str, Any]]:
    bdir = _backups_dir(data_dir, scope)
    if not bdir.exists():
        return []
    items: list[dict[str, Any]] = []
    for entry in bdir.iterdir():
        if not entry.is_file():
            continue
        m = _BACKUP_NAME_RE.match(entry.name)
        if not m:
            continue
        try:
            st = entry.stat()
        except OSError:
            continue
        items.append({
            "name": entry.name,
            "size": st.st_size,
            "created": m.group(1),
            "mtime": int(st.st_mtime),
        })
    items.sort(key=lambda it: it["name"], reverse=True)
    return items


def prune_backups(data_dir: Path, scope: str, keep: int = MAX_BACKUPS) -> int:
    items = list_backups(data_dir, scope)
    if len(items) <= keep:
        return 0
    bdir = _backups_dir(data_dir, scope)
    removed = 0
    for it in items[keep:]:
        try:
            (bdir / it["name"]).unlink()
            removed += 1
        except OSError as exc:
            _LOGGER.warning("user_backup: prune failed for %s: %s", it["name"], exc)
    return removed


def export_user_data(data_dir: Path, scope: str) -> bytes:
    """ZIP-Bytes der aktuellen User-Daten (fuer Download)."""
    payload = _collect_payload(_scope_dir(data_dir, scope))
    return _write_zip(payload, scope)


def import_user_data(data_dir: Path, scope: str, zip_bytes: bytes) -> dict[str, Any]:
    """Restauriert prefs.json/recent.json aus einer Backup-ZIP.

    Macht vorher automatisch ein Sicherheits-Backup, validiert JSON-Inhalt und
    schreibt nur erlaubte Dateinamen (TRACKED_FILES, keine Pfadtraversal).
    """
    if not zip_bytes:
        return {"ok": False, "error": "Leere Datei."}
    if len(zip_bytes) > MAX_IMPORT_BYTES:
        return {"ok": False, "error": "Datei zu gross."}
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return {"ok": False, "error": "Keine gueltige ZIP-Datei."}

    restored: list[str] = []
    with _LOCK:
        # Vorher Sicherheits-Snapshot anlegen (best-effort)
        try:
            create_backup(data_dir, scope)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("user_backup: pre-import snapshot failed: %s", exc)
        scope_dir = _scope_dir(data_dir, scope)
        scope_dir.mkdir(parents=True, exist_ok=True)
        for name in TRACKED_FILES:
            if name not in zf.namelist():
                continue
            try:
                data = zf.read(name)
            except KeyError:
                continue
            # JSON validieren
            try:
                json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                return {"ok": False, "error": f"{name}: ungueltiges JSON ({exc})."}
            (scope_dir / name).write_bytes(data)
            restored.append(name)
    if not restored:
        return {"ok": False, "error": "Keine bekannten Dateien im Backup."}
    return {"ok": True, "restored": restored}


def read_backup(data_dir: Path, scope: str, name: str) -> bytes | None:
    """Liest ein Backup-File (mit Pfad-Validierung) fuer Download."""
    if not _BACKUP_NAME_RE.match(name or ""):
        return None
    path = _backups_dir(data_dir, scope) / name
    try:
        if not path.is_file():
            return None
        return path.read_bytes()
    except OSError:
        return None


def delete_backup(data_dir: Path, scope: str, name: str) -> bool:
    if not _BACKUP_NAME_RE.match(name or ""):
        return False
    path = _backups_dir(data_dir, scope) / name
    try:
        if not path.is_file():
            return False
        path.unlink()
        return True
    except OSError:
        return False
