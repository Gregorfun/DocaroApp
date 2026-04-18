"""Welle 13C: Trash-Bin – weiches Loeschen mit 7-Tage-Wiederherstellung.

Verschiebt PDFs und ihre Metadaten in data/users/<scope>/trash/.
Eintraege werden in trash.json indiziert, alte (>RETENTION_DAYS) automatisch
beim Lesen ausgemustert.
"""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REGISTRY_NAME = "trash.json"
TRASH_DIR_NAME = "trash"
RETENTION_DAYS = 7
_LOCK = threading.RLock()


def _trash_dir(data_dir: Path, scope: str) -> Path:
    safe = scope or "system"
    return data_dir / "users" / safe / TRASH_DIR_NAME


def _registry_path(data_dir: Path, scope: str) -> Path:
    return _trash_dir(data_dir, scope) / REGISTRY_NAME


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
    return [it for it in raw if isinstance(it, dict) and it.get("id")]


def _write(data_dir: Path, scope: str, items: list[dict[str, Any]]) -> None:
    path = _registry_path(data_dir, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _is_expired(entry: dict[str, Any], now: datetime | None = None) -> bool:
    deleted = str(entry.get("deleted_at") or "")
    if not deleted:
        return True
    try:
        dt = datetime.fromisoformat(deleted)
    except ValueError:
        return True
    cutoff = (now or datetime.now()) - timedelta(days=RETENTION_DAYS)
    return dt < cutoff


def prune_expired(data_dir: Path, scope: str) -> int:
    """Loescht abgelaufene Eintraege (>RETENTION_DAYS) endgueltig."""
    with _LOCK:
        items = _read(data_dir, scope)
        kept: list[dict[str, Any]] = []
        removed = 0
        td = _trash_dir(data_dir, scope)
        for it in items:
            if _is_expired(it):
                stored = it.get("stored_name") or ""
                if stored:
                    p = td / stored
                    if p.exists():
                        try:
                            p.unlink()
                        except OSError:
                            pass
                removed += 1
            else:
                kept.append(it)
        if removed:
            _write(data_dir, scope, kept)
        return removed


def list_items(data_dir: Path, scope: str) -> list[dict[str, Any]]:
    with _LOCK:
        prune_expired(data_dir, scope)
        return _read(data_dir, scope)


def move_to_trash(
    data_dir: Path,
    scope: str,
    pdf_path: Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verschiebt eine PDF-Datei in den Trash. Liefert den Eintrag zurueck."""
    if not pdf_path.exists():
        raise FileNotFoundError(str(pdf_path))
    with _LOCK:
        td = _trash_dir(data_dir, scope)
        td.mkdir(parents=True, exist_ok=True)
        tid = uuid.uuid4().hex[:12]
        stored_name = f"{tid}_{pdf_path.name}"
        # Sicherheit: keine Pfadtrenner im stored_name
        stored_name = stored_name.replace("/", "_").replace("\\", "_")
        target = td / stored_name
        # rename, mit Cross-Device-Fallback
        try:
            pdf_path.replace(target)
        except OSError:
            shutil.copy2(pdf_path, target)
            try:
                pdf_path.unlink()
            except OSError:
                pass
        entry = {
            "id": tid,
            "stored_name": stored_name,
            "original_name": pdf_path.name,
            "original_path": str(pdf_path),
            "deleted_at": _now_iso(),
            "metadata": metadata or {},
        }
        items = _read(data_dir, scope)
        items.append(entry)
        _write(data_dir, scope, items)
        return entry


def restore(data_dir: Path, scope: str, tid: str) -> Path:
    """Stellt einen Trash-Eintrag wieder am ursprünglichen Pfad her."""
    tid = (tid or "").strip()
    with _LOCK:
        items = _read(data_dir, scope)
        target_entry: dict[str, Any] | None = None
        for it in items:
            if it.get("id") == tid:
                target_entry = it
                break
        if target_entry is None:
            raise KeyError(f"Trash-Eintrag {tid!r} nicht gefunden.")
        td = _trash_dir(data_dir, scope)
        stored = td / str(target_entry.get("stored_name") or "")
        if not stored.exists():
            raise FileNotFoundError(str(stored))
        original = Path(str(target_entry.get("original_path") or ""))
        original.parent.mkdir(parents=True, exist_ok=True)
        # Konflikt: append _restored
        target = original
        if target.exists():
            target = original.with_name(f"{original.stem}_restored{original.suffix}")
        try:
            stored.replace(target)
        except OSError:
            shutil.copy2(stored, target)
            try:
                stored.unlink()
            except OSError:
                pass
        items = [it for it in items if it.get("id") != tid]
        _write(data_dir, scope, items)
        return target


def purge(data_dir: Path, scope: str, tid: str) -> bool:
    """Loescht einen einzelnen Trash-Eintrag endgueltig."""
    tid = (tid or "").strip()
    with _LOCK:
        items = _read(data_dir, scope)
        kept: list[dict[str, Any]] = []
        removed = False
        td = _trash_dir(data_dir, scope)
        for it in items:
            if it.get("id") == tid:
                stored = td / str(it.get("stored_name") or "")
                if stored.exists():
                    try:
                        stored.unlink()
                    except OSError:
                        pass
                removed = True
            else:
                kept.append(it)
        if removed:
            _write(data_dir, scope, kept)
        return removed


def empty_trash(data_dir: Path, scope: str) -> int:
    """Leert den gesamten Trash. Liefert die Anzahl entfernter Eintraege."""
    with _LOCK:
        items = _read(data_dir, scope)
        td = _trash_dir(data_dir, scope)
        for it in items:
            stored = td / str(it.get("stored_name") or "")
            if stored.exists():
                try:
                    stored.unlink()
                except OSError:
                    pass
        _write(data_dir, scope, [])
        return len(items)
