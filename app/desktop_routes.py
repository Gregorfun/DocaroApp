"""
Desktop-Komfort-Endpunkte: Reveal in Explorer, native Toasts, Recent-Files,
Diagnose-ZIP-Export, Runtime-Info (Offline-Badge).

Reveal/Toast funktionieren nur wenn DOCARO_DESKTOP_MODE=1 oder sys.frozen, damit
die Web-Variante keinen lokalen Dateisystemzugriff via API freigibt.
"""

from __future__ import annotations

import io
import logging
import os
import platform
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    has_request_context,
    jsonify,
    request,
    send_file,
    session,
)

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import Config
from core import recent_store, user_backup, user_prefs, user_profiles
from core import saved_searches as _saved_searches
from core import trash_bin as _trash_bin

_LOGGER = logging.getLogger(__name__)
_config = Config()

desktop_bp = Blueprint("desktop", __name__, url_prefix="/api/desktop")


def _is_desktop_mode() -> bool:
    return os.getenv("DOCARO_DESKTOP_MODE", "0") == "1" or bool(getattr(sys, "frozen", False))


def _user_scope() -> str:
    # Welle 10: Im Desktop-Modus immer das aktive Profil scopen, damit alle
    # User-Daten (recent/prefs/backups) sauber pro Profil getrennt sind.
    if _is_desktop_mode():
        try:
            return user_profiles.active_scope(_config.DATA_DIR)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("_user_scope: profile resolve failed: %s", exc)
            return user_profiles.scope_for(user_profiles.DEFAULT_PROFILE_ID)
    if not has_request_context():
        return "system"
    user_id = session.get("user_id")
    if user_id is not None and str(user_id).strip():
        return f"user_{user_id}"
    email = (session.get("user_email") or "").strip().lower()
    return f"user_{email}" if email else "system"


def _safe_within_data_dir(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    data_root = _config.DATA_DIR.resolve()
    try:
        resolved.relative_to(data_root)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Runtime info (Offline-Badge)
# ---------------------------------------------------------------------------

@desktop_bp.get("/info")
def runtime_info():
    return jsonify({
        "desktop_mode": _is_desktop_mode(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "platform": platform.system(),
        "data_dir": str(_config.DATA_DIR),
        "offline": True,
    })


# ---------------------------------------------------------------------------
# Reveal in Explorer
# ---------------------------------------------------------------------------

@desktop_bp.post("/reveal")
def reveal_path():
    if not _is_desktop_mode():
        return jsonify({"ok": False, "error": "Nur im Desktop-Modus verfuegbar."}), 403

    payload = request.get_json(silent=True) or {}
    raw = (payload.get("path") or "").strip()
    if not raw:
        return jsonify({"ok": False, "error": "Pfad fehlt."}), 400

    target = Path(raw).expanduser()
    if not target.is_absolute():
        target = (_config.DATA_DIR / target).resolve()

    if not _safe_within_data_dir(target):
        return jsonify({"ok": False, "error": "Pfad ausserhalb des erlaubten Bereichs."}), 403

    if not target.exists():
        return jsonify({"ok": False, "error": "Datei oder Ordner nicht gefunden."}), 404

    system = platform.system().lower()
    try:
        if system == "windows":
            if target.is_dir():
                subprocess.Popen(["explorer.exe", str(target)])
            else:
                subprocess.Popen(["explorer.exe", "/select,", str(target)])
        elif system == "darwin":
            subprocess.Popen(["open", "-R", str(target)] if target.is_file() else ["open", str(target)])
        else:
            folder = target.parent if target.is_file() else target
            subprocess.Popen(["xdg-open", str(folder)])
    except OSError as exc:
        _LOGGER.warning("reveal_path failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "path": str(target)})


# ---------------------------------------------------------------------------
# Native Toast Notifications
# ---------------------------------------------------------------------------

_TOAST_TITLE_MAX = 80
_TOAST_BODY_MAX = 240


def _send_windows_toast(title: str, body: str) -> bool:
    title = title.replace('"', "'")[:_TOAST_TITLE_MAX]
    body = body.replace('"', "'")[:_TOAST_BODY_MAX]
    ps_script = (
        "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime] | Out-Null;"
        "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$nodes = $template.GetElementsByTagName('text');"
        f"$nodes.Item(0).AppendChild($template.CreateTextNode('{title}')) | Out-Null;"
        f"$nodes.Item(1).AppendChild($template.CreateTextNode('{body}')) | Out-Null;"
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($template);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('DocaroApp').Show($toast);"
    )
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except OSError as exc:
        _LOGGER.warning("Windows toast failed: %s", exc)
        return False


@desktop_bp.post("/notify")
def notify():
    if not _is_desktop_mode():
        return jsonify({"ok": False, "error": "Nur im Desktop-Modus verfuegbar."}), 403

    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title") or "DocaroApp").strip()[:_TOAST_TITLE_MAX]
    body = str(payload.get("body") or "").strip()[:_TOAST_BODY_MAX]
    if not body:
        return jsonify({"ok": False, "error": "Body fehlt."}), 400

    system = platform.system().lower()
    sent = False
    if system == "windows":
        sent = _send_windows_toast(title, body)
    else:
        # Plyer-Fallback (optional installiert)
        try:
            from plyer import notification  # type: ignore

            notification.notify(title=title, message=body, app_name="DocaroApp", timeout=6)
            sent = True
        except Exception as exc:  # pragma: no cover - optional dep
            _LOGGER.info("Toast nicht versendet (%s): %s", system, exc)

    return jsonify({"ok": sent})


# ---------------------------------------------------------------------------
# Recent Files
# ---------------------------------------------------------------------------

@desktop_bp.get("/recent")
def recent_list():
    items = recent_store.load_recent(_config.DATA_DIR, _user_scope())
    return jsonify({"items": items, "max_entries": recent_store.MAX_ENTRIES})


@desktop_bp.post("/recent")
def recent_add():
    payload = request.get_json(silent=True) or {}
    kind = str(payload.get("kind") or "").strip().lower()
    filename = str(payload.get("filename") or "").strip()[:200]
    if not kind or not filename:
        return jsonify({"ok": False, "error": "kind/filename fehlt."}), 400
    if kind not in recent_store.ALLOWED_KINDS:
        return jsonify({"ok": False, "error": "kind ungueltig."}), 400

    extra = {}
    for key in ("savings_pct", "parts", "lang"):
        if key in payload and payload[key] is not None:
            extra[key] = payload[key]

    recent_store.add_recent(
        _config.DATA_DIR,
        _user_scope(),
        kind=kind,
        filename=filename,
        path=str(payload.get("path") or "")[:400],
        download_token=str(payload.get("download_token") or "")[:80],
        extra=extra,
    )
    return jsonify({"ok": True})


@desktop_bp.post("/recent/clear")
def recent_clear():
    recent_store.clear_recent(_config.DATA_DIR, _user_scope())
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Diagnose-ZIP
# ---------------------------------------------------------------------------

_LOG_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.log(\.\d+)?$")


def _collect_log_files() -> list[Path]:
    log_dir = _config.LOG_DIR
    if not log_dir.exists():
        return []
    out: list[Path] = []
    for entry in sorted(log_dir.iterdir()):
        if entry.is_file() and _LOG_NAME_RE.match(entry.name):
            out.append(entry)
    return out


@desktop_bp.get("/diagnostics.zip")
def diagnostics_zip():
    buf = io.BytesIO()
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    info_lines = [
        f"Docaro diagnostics export {timestamp}",
        f"Platform: {platform.platform()}",
        f"Python: {sys.version.split()[0]}",
        f"Frozen: {bool(getattr(sys, 'frozen', False))}",
        f"Desktop-Mode: {_is_desktop_mode()}",
        f"Data dir: {_config.DATA_DIR}",
        f"Log dir: {_config.LOG_DIR}",
    ]

    settings_path = _config.SETTINGS_PATH
    settings_text = ""
    if settings_path.exists():
        try:
            settings_text = settings_path.read_text(encoding="utf-8")
        except OSError as exc:
            settings_text = f"(read error: {exc})"

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("info.txt", "\n".join(info_lines) + "\n")
        if settings_text:
            zf.writestr("settings.json", settings_text)
        for log_file in _collect_log_files():
            try:
                zf.write(log_file, arcname=f"logs/{log_file.name}")
            except OSError as exc:
                _LOGGER.warning("diagnostics_zip skipped %s: %s", log_file, exc)

    buf.seek(0)
    fname = f"docaro-diagnose-{timestamp}.zip"
    return send_file(
        buf,
        download_name=fname,
        as_attachment=True,
        mimetype="application/zip",
    )


# ---------------------------------------------------------------------------
# User-Prefs (Smart Defaults: Datumsformat, Lieferanten-Quick-Picks, Doctype)
# ---------------------------------------------------------------------------


def _prefs_response(prefs: dict[str, Any]) -> dict[str, Any]:
    return {
        "last_date_fmt": prefs.get("last_date_fmt") or "%d-%m-%Y",
        "last_doctype": prefs.get("last_doctype") or "",
        "recent_suppliers": list(prefs.get("recent_suppliers") or []),
        "doctype_per_supplier": dict(prefs.get("doctype_per_supplier") or {}),
        "tour_done": bool(prefs.get("tour_done")),
        "ui_theme": prefs.get("ui_theme") or "auto",
        "filename_template": prefs.get("filename_template") or "",
        "results_sort": prefs.get("results_sort") or "",
        "updated_at": prefs.get("updated_at") or "",
    }


@desktop_bp.get("/prefs")
def prefs_get():
    prefs = user_prefs.load_prefs(_config.DATA_DIR, _user_scope())
    return jsonify({"ok": True, "prefs": _prefs_response(prefs)})


@desktop_bp.post("/prefs")
def prefs_post():
    payload = request.get_json(silent=True) or {}
    changes: dict[str, Any] = {}
    if "last_date_fmt" in payload:
        changes["last_date_fmt"] = payload["last_date_fmt"]
    if "last_doctype" in payload:
        changes["last_doctype"] = payload["last_doctype"]
    if "tour_done" in payload:
        changes["tour_done"] = payload["tour_done"]
    if "ui_theme" in payload:
        changes["ui_theme"] = payload["ui_theme"]
    if "filename_template" in payload:
        changes["filename_template"] = payload["filename_template"]
    if "results_sort" in payload:
        changes["results_sort"] = payload["results_sort"]
    if not changes:
        return jsonify({"ok": False, "error": "Keine erlaubten Felder."}), 400
    prefs = user_prefs.update_prefs(_config.DATA_DIR, _user_scope(), **changes)
    return jsonify({"ok": True, "prefs": _prefs_response(prefs)})


@desktop_bp.post("/naming/preview")
def naming_preview():
    from core import naming_templates as _nt
    payload = request.get_json(silent=True) or {}
    template = str(payload.get("template", "") or "").strip()
    if not template:
        return jsonify({"ok": True, "preview": "", "valid": False, "default": _nt.DEFAULT_TEMPLATE})
    valid = _nt.is_valid_template(template)
    return jsonify({
        "ok": True,
        "valid": valid,
        "preview": _nt.preview(template) if valid else "",
        "tokens": sorted(_nt.ALLOWED_TOKENS),
    })


# ---------------------------------------------------------------------------
# Welle 13B: Saved-Searches
# ---------------------------------------------------------------------------


@desktop_bp.get("/searches")
def searches_list():
    items = _saved_searches.list_searches(_config.DATA_DIR, _user_scope())
    return jsonify({"ok": True, "searches": items, "max": _saved_searches.MAX_SEARCHES})


@desktop_bp.post("/searches")
def searches_create():
    payload = request.get_json(silent=True) or {}
    try:
        entry = _saved_searches.create_search(_config.DATA_DIR, _user_scope(), payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "search": entry})


@desktop_bp.post("/searches/<sid>/delete")
def searches_delete(sid: str):
    ok = _saved_searches.delete_search(_config.DATA_DIR, _user_scope(), sid)
    if not ok:
        return jsonify({"ok": False, "error": "Suche nicht gefunden."}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Welle 13C: Trash-Bin
# ---------------------------------------------------------------------------


@desktop_bp.get("/trash")
def trash_list():
    items = _trash_bin.list_items(_config.DATA_DIR, _user_scope())
    return jsonify({
        "ok": True,
        "items": items,
        "retention_days": _trash_bin.RETENTION_DAYS,
    })


@desktop_bp.post("/trash/<tid>/restore")
def trash_restore(tid: str):
    try:
        path = _trash_bin.restore(_config.DATA_DIR, _user_scope(), tid)
    except KeyError:
        return jsonify({"ok": False, "error": "Eintrag nicht gefunden."}), 404
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "Datei fehlt im Trash."}), 410
    return jsonify({"ok": True, "path": str(path)})


@desktop_bp.post("/trash/<tid>/delete")
def trash_purge(tid: str):
    ok = _trash_bin.purge(_config.DATA_DIR, _user_scope(), tid)
    if not ok:
        return jsonify({"ok": False, "error": "Eintrag nicht gefunden."}), 404
    return jsonify({"ok": True})


@desktop_bp.post("/trash/empty")
def trash_empty():
    n = _trash_bin.empty_trash(_config.DATA_DIR, _user_scope())
    return jsonify({"ok": True, "removed": n})


# ---------------------------------------------------------------------------
# Welle 9: Datenpflege & Backup (Snapshots, Export, Import)
# ---------------------------------------------------------------------------


@desktop_bp.get("/backup")
def backup_list():
    items = user_backup.list_backups(_config.DATA_DIR, _user_scope())
    return jsonify({"ok": True, "backups": items, "max": user_backup.MAX_BACKUPS})


@desktop_bp.post("/backup")
def backup_create():
    res = user_backup.create_backup(_config.DATA_DIR, _user_scope())
    code = 200 if res.get("ok") else 400
    return jsonify(res), code


@desktop_bp.get("/backup/export.zip")
def backup_export():
    scope = _user_scope()
    data = user_backup.export_user_data(_config.DATA_DIR, scope)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    fname = f"docaro-userdata-{scope}-{timestamp}.zip"
    return send_file(
        io.BytesIO(data),
        download_name=fname,
        as_attachment=True,
        mimetype="application/zip",
    )


@desktop_bp.post("/backup/import")
def backup_import():
    upload = request.files.get("file")
    if upload is None:
        return jsonify({"ok": False, "error": "Keine Datei uebermittelt."}), 400
    raw = upload.read(user_backup.MAX_IMPORT_BYTES + 1)
    if len(raw) > user_backup.MAX_IMPORT_BYTES:
        return jsonify({"ok": False, "error": "Datei zu gross."}), 400
    res = user_backup.import_user_data(_config.DATA_DIR, _user_scope(), raw)
    code = 200 if res.get("ok") else 400
    return jsonify(res), code


@desktop_bp.get("/backup/<name>")
def backup_download(name: str):
    data = user_backup.read_backup(_config.DATA_DIR, _user_scope(), name)
    if data is None:
        abort(404)
    return send_file(
        io.BytesIO(data),
        download_name=name,
        as_attachment=True,
        mimetype="application/zip",
    )


@desktop_bp.post("/backup/<name>/delete")
def backup_delete(name: str):
    ok = user_backup.delete_backup(_config.DATA_DIR, _user_scope(), name)
    if not ok:
        return jsonify({"ok": False, "error": "Backup nicht gefunden."}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Welle 10: Multi-User & Profile-Switching
# ---------------------------------------------------------------------------

_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


@desktop_bp.get("/profiles")
def profiles_list():
    data = user_profiles.list_profiles(_config.DATA_DIR)
    return jsonify({"ok": True, **data, "max": user_profiles.MAX_PROFILES})


@desktop_bp.post("/profiles")
def profiles_create():
    payload = request.get_json(silent=True) or {}
    label = str(payload.get("label") or "").strip()
    res = user_profiles.create_profile(_config.DATA_DIR, label)
    return jsonify(res), (200 if res.get("ok") else 400)


@desktop_bp.post("/profiles/<pid>/activate")
def profiles_activate(pid: str):
    if not _PROFILE_ID_RE.match(pid or ""):
        return jsonify({"ok": False, "error": "Ungueltige Profil-Id."}), 400
    res = user_profiles.activate_profile(_config.DATA_DIR, pid)
    return jsonify(res), (200 if res.get("ok") else 404)


@desktop_bp.post("/profiles/<pid>/rename")
def profiles_rename(pid: str):
    if not _PROFILE_ID_RE.match(pid or ""):
        return jsonify({"ok": False, "error": "Ungueltige Profil-Id."}), 400
    payload = request.get_json(silent=True) or {}
    label = str(payload.get("label") or "").strip()
    res = user_profiles.rename_profile(_config.DATA_DIR, pid, label)
    return jsonify(res), (200 if res.get("ok") else 400)


@desktop_bp.post("/profiles/<pid>/delete")
def profiles_delete(pid: str):
    if not _PROFILE_ID_RE.match(pid or ""):
        return jsonify({"ok": False, "error": "Ungueltige Profil-Id."}), 400
    res = user_profiles.delete_profile(_config.DATA_DIR, pid)
    return jsonify(res), (200 if res.get("ok") else 400)
