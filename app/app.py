from __future__ import annotations

from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
import sys
import zipfile
import json
import re
from uuid import uuid4
from contextlib import contextmanager
import time
import secrets
import logging
import traceback

import os

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.extractor import (
    load_suppliers_db,
    normalize_text,
    process_folder,
    get_unique_path,
    save_suppliers_db,
    build_new_filename,
    INTERNAL_DATE_FORMAT,
)
DATA_DIR = BASE_DIR / "data"
INBOX_DIR = DATA_DIR / "eingang"
OUT_DIR = DATA_DIR / "fertig"
TMP_DIR = DATA_DIR / "tmp"
SUPPLIER_CORRECTIONS_PATH = DATA_DIR / "supplier_corrections.json"
SESSION_FILES_PATH = DATA_DIR / "session_files.json"
SESSION_FILES_LOCK = DATA_DIR / "session_files.lock"

ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y%m%d")
MANUAL_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d/%m/%y",
)
HISTORY_PATH = DATA_DIR / "history.jsonl"
LOG_RETENTION_DAYS = int(os.getenv("DOCARO_LOG_RETENTION_DAYS", "90"))

try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

DEBUG_MODE = os.getenv("DOCARO_DEBUG") == "1"

app = Flask(__name__)
_secret = os.getenv("DOCARO_SECRET_KEY")
if not _secret:
    if os.getenv("DOCARO_ALLOW_INSECURE_SECRET") == "1":
        _secret = secrets.token_hex(32)
    else:
        raise RuntimeError(
            "DOCARO_SECRET_KEY fehlt. Bitte setzen. Beispiel (PowerShell): "
            '$env:DOCARO_SECRET_KEY="change-me-please" '
            "(optional nur fuer Tests: DOCARO_ALLOW_INSECURE_SECRET=1)."
        )
app.secret_key = _secret
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "server.log"
_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
_handler.setLevel(logging.INFO)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler])
app.logger.addHandler(_handler)
app.logger.setLevel(logging.INFO)
app.config["PROPAGATE_EXCEPTIONS"] = True
app.config["DEBUG"] = DEBUG_MODE

_werkzeug_logger = logging.getLogger("werkzeug")
_werkzeug_logger.addHandler(_handler)
_werkzeug_logger.setLevel(logging.INFO)


def _log_exception(context: str, exc: Exception) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} ERROR {context}\n")
        handle.write(f"{repr(exc)}\n")
        handle.write(traceback.format_exc())
        handle.write("\n")


@app.before_request
def _trace_upload_requests():
    if request.path == "/upload":
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat(timespec='seconds')} INFO request {request.method} {request.path}\n")


if not DEBUG_MODE:
    @app.errorhandler(Exception)
    def _handle_exception(exc: Exception):
        if isinstance(exc, HTTPException):
            return exc
        app.logger.exception("Unhandled exception", exc_info=exc)
        return "Internal Server Error", 500


@app.after_request
def _log_server_errors(response):
    if response.status_code >= 500:
        app.logger.error(
            "HTTP %s %s -> %s",
            request.method,
            request.path,
            response.status_code,
        )
    return response


def _allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


@app.get("/")
def index():
    files = _list_finished()
    reset_done = request.args.get("reset") == "1"
    results = _load_last_results()
    if results is not None:
        results = _attach_file_ids(results)
        results = _apply_result_flags(results)
        _save_last_results(results)
    incomplete_only = request.args.get("incomplete") == "1"
    edit_all = request.args.get("edit") == "1"
    filtered = _filter_results(results, incomplete_only) if results else results
    return render_template(
        "index.html",
        results=filtered,
        files=files,
        reset_done=reset_done,
        incomplete_only=incomplete_only,
        edit_all=edit_all,
    )


@app.post("/upload")
def upload():
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        TMP_DIR.mkdir(parents=True, exist_ok=True)

        uploaded = request.files.getlist("files")
        if not uploaded:
            return render_template("index.html", results=[], files=_list_finished())

        date_fmt = request.form.get("date_fmt", "").strip()
        if date_fmt not in ALLOWED_DATE_FORMATS:
            date_fmt = "%Y-%m-%d"

        upload_dir = TMP_DIR / f"upload_{uuid4().hex}"
        upload_dir.mkdir(parents=True, exist_ok=True)
        for storage in uploaded:
            if not storage or not storage.filename:
                continue
            safe_name = secure_filename(storage.filename)
            if not safe_name or not _allowed_file(safe_name):
                continue
            target_path = get_unique_path(upload_dir, safe_name)
            storage.save(target_path)

        results = process_folder(upload_dir, OUT_DIR, date_format=date_fmt)
        _clear_pdfs(upload_dir)
        results = _attach_file_ids(results)
        results = _apply_result_flags(results)
        _save_last_results(results)
        return render_template("index.html", results=results, files=_list_finished(), reset_done=False)
    except Exception as exc:
        _log_exception("upload:handler", exc)
        raise


@app.get("/upload")
def upload_overview():
    return redirect(url_for("index"))


def _list_finished():
    results = _load_last_results() or []
    files = [item.get("out_name") for item in results if item.get("out_name")]
    return sorted({name for name in files if name})


def _clear_pdfs(dir_path: Path) -> None:
    if not dir_path.exists():
        return
    for pdf in dir_path.glob("*.pdf"):
        try:
            pdf.unlink()
        except OSError:
            continue


def _get_session_id() -> str:
    sid = session.get("sid")
    if not sid:
        sid = uuid4().hex
        session["sid"] = sid
    return sid


def _session_results_path() -> Path:
    sid = _get_session_id()
    return TMP_DIR / f"last_results_{sid}.json"


def _save_last_results(results) -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    session["last_results"] = results
    _session_results_path().write_text(json.dumps(results, indent=2), encoding="utf-8")


def _load_last_results():
    results = session.get("last_results")
    if results is not None:
        return _apply_supplier_corrections(results)
    results_path = _session_results_path()
    if not results_path.exists():
        return None
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    results = _apply_supplier_corrections(results)
    session["last_results"] = results
    return results


def _load_session_files() -> dict:
    if not SESSION_FILES_PATH.exists():
        return {}
    with _locked_file(SESSION_FILES_LOCK, mode="a+"):
        try:
            return json.loads(SESSION_FILES_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}


def _save_session_files(data: dict) -> None:
    SESSION_FILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2)
    with _locked_file(SESSION_FILES_LOCK, mode="a+"):
        tmp_path = SESSION_FILES_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(SESSION_FILES_PATH)


def _get_session_file_map() -> dict:
    data = _load_session_files()
    sid = _get_session_id()
    return data.get(sid, {})


def _set_session_file_entry(file_id: str, path: Path, filename: str) -> None:
    data = _load_session_files()
    sid = _get_session_id()
    session_map = data.setdefault(sid, {})
    session_map[file_id] = {"path": str(path), "filename": filename}
    _save_session_files(data)


def _remove_session_files() -> None:
    data = _load_session_files()
    sid = _get_session_id()
    if sid in data:
        data.pop(sid, None)
        _save_session_files(data)


def _append_history(entry: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    _trim_history()


def _load_supplier_corrections() -> dict:
    if not SUPPLIER_CORRECTIONS_PATH.exists():
        return {}
    try:
        return json.loads(SUPPLIER_CORRECTIONS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_supplier_corrections(data: dict) -> None:
    SUPPLIER_CORRECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUPPLIER_CORRECTIONS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_history_entries() -> list:
    if not HISTORY_PATH.exists():
        return []
    entries = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _latest_history_entry() -> Optional[dict]:
    entries = _load_history_entries()
    for entry in reversed(entries):
        if entry.get("action_type") != "undo":
            return entry
    return None


def _is_date_missing(date_valAe: Optional[str], parsing_failed: bool = False) -> bool:
    if parsing_failed:
        return True
    if date_valAe is None:
        return True
    valAe = str(date_valAe).strip()
    if not valAe or valAe == "-":
        return True
    if "unbekannt" in valAe.lower():
        return True
    return False


def _is_supplier_missing(supplier_valAe: Optional[str]) -> bool:
    if supplier_valAe is None:
        return True
    valAe = str(supplier_valAe).strip()
    return not valAe or valAe == "Unbekannt"


def _is_supplier_broken(supplier_valAe: Optional[str]) -> bool:
    if supplier_valAe is None:
        return False
    valAe = str(supplier_valAe).strip()
    if not valAe:
        return False
    if len(valAe) > 60:
        return True
    non_word = sum(1 for ch in valAe if not (ch.isalnum() or ch in (" ", "-", "_", "&", ".")))
    if non_word >= 6:
        return True
    if valAe.count(" ") >= 8:
        return True
    return False


def _apply_result_flags(results):
    if results is None:
        return results
    for item in results:
        parsing_failed = bool(item.get("parsing_failed"))
        date_valAe = item.get("date")
        supplier_valAe = item.get("supplier")
        item["date_missing"] = _is_date_missing(date_valAe, parsing_failed)
        item["supplier_missing"] = _is_supplier_missing(supplier_valAe)
        item["supplier_broken"] = _is_supplier_broken(supplier_valAe)
        item["needs_review"] = _is_review_needed(item)
        if item.get("file_id"):
            item["view_url"] = url_for("view_pdf", file_id=item["file_id"])
    return results


def _is_ajax_request() -> bool:
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


def _row_payload(file_id: str, message: str = "") -> dict:
    result = _result_for_file_id(file_id) or {}
    return {
        "ok": True,
        "file_id": file_id,
        "out_name": result.get("out_name") or "",
        "supplier": result.get("supplier") or "",
        "supplier_source": result.get("supplier_source") or "",
        "supplier_confidence": result.get("supplier_confidence") or "",
        "date": result.get("date") or "",
        "error": result.get("error") or "",
        "tesseract_status": result.get("tesseract_status") or "",
        "poppler_status": result.get("poppler_status") or "",
        "supplier_missing": bool(result.get("supplier_missing")),
        "date_missing": bool(result.get("date_missing")),
        "needs_review": bool(result.get("needs_review")),
        "message": message,
    }


def _attach_file_ids(results):
    if results is None:
        return results
    for item in results:
        file_id = item.get("file_id")
        if not file_id:
            file_id = uuid4().hex
            item["file_id"] = file_id
        filename = item.get("out_name") or ""
        if filename:
            pdf_path = resolve_pdf_path(filename)
            if pdf_path:
                _set_session_file_entry(file_id, pdf_path, filename)
    return results


def _filter_results(results, incomplete_only: bool):
    if not results or not incomplete_only:
        return results
    return [item for item in results if item.get("date_missing") or item.get("supplier_missing") or item.get("needs_review")]


def _session_filenames() -> set[str]:
    results = _load_last_results() or []
    return {item.get("out_name") for item in results if item.get("out_name")}


@app.post("/reset")
def reset_downloads():
    session_files = _get_session_file_map()
    for entry in session_files.values():
        path_str = entry.get("path") or ""
        if not path_str:
            continue
        path = Path(path_str)
        if _is_allowed_pdf_path(path) and path.exists():
            try:
                path.unlink()
            except OSError:
                continue
    _remove_session_files()
    results_path = _session_results_path()
    session.pop("last_results", None)
    session.pop("sid", None)
    if results_path.exists():
        try:
            results_path.unlink()
        except OSError:
            pass
    return redirect(url_for("index", reset="1"))


@app.post("/confirm_supplier")
def confirm_supplier():
    supplier_input = request.form.get("supplier_input", "").strip()
    if not supplier_input:
        supplier_input = request.form.get("supplier_name", "").strip()
    file_id = request.form.get("file_id", "").strip()
    result = _result_for_file_id(file_id) if file_id else None
    if file_id and not result:
        message = "Datei nicht gefunden."
        if _is_ajax_request():
            return jsonify({"ok": False, "message": message}), 404
        flash(message)
        return redirect(url_for("index"))
    filename = (result or {}).get("out_name") or ""
    return_to = request.form.get("return_to", "")

    def _redirect_after_confirm():
        if return_to == "viewer" and file_id:
            return redirect(url_for("review_next", current=file_id))
        return redirect(url_for("index"))

    supplier_name = _normalize_supplier_input(supplier_input)
    if len(supplier_name) < 2:
        message = "Lieferant ungültig."
        if _is_ajax_request():
            return jsonify({"ok": False, "message": message}), 400
        flash(message)
        return _redirect_after_confirm()

    use_alias = request.form.get("use_alias") == "1" or request.form.get("alias_from_ocr") in ("1", "on", "true")
    alias = ""
    if use_alias:
        alias = request.form.get("supplier_guess_line", "").strip()

    data = load_suppliers_db()
    suppliers = data.get("suppliers", [])
    target = None
    target_key = normalize_text(supplier_name)
    for entry in suppliers:
        name = str(entry.get("name", "")).strip()
        if normalize_text(name) == target_key:
            target = entry
            break

    if target is None:
        target = {
            "name": supplier_name,
            "aliases": [],
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        suppliers.append(target)

    if alias:
        aliases = target.setdefault("aliases", [])
        if all(normalize_text(a) != normalize_text(alias) for a in aliases):
            aliases.append(alias)

    data["suppliers"] = suppliers
    save_suppliers_db(data)
    message = "Lieferant gespeichert."
    if file_id:
        before = result or {}
        supplier_before = before.get("supplier") or ""
        date_before = before.get("date") or ""
        pdf_path = _resolve_file_path(file_id) or resolve_pdf_path(filename)
        new_name = filename
        if pdf_path:
            _set_session_file_entry(file_id, pdf_path, pdf_path.name)
        # If a valid date exists, recompute the target filename using the corrected supplier.
        if date_before:
            try:
                date_obj = datetime.strptime(date_before, INTERNAL_DATE_FORMAT)
            except ValueError:
                date_obj = None
            if date_obj and pdf_path:
                recomputed = build_new_filename(supplier_name, date_obj, date_format=INTERNAL_DATE_FORMAT)
                target_path, rename_error = _rename_pdf_with_name(pdf_path, recomputed)
                if rename_error:
                    _set_result_error(file_id, f"rename_failed: {rename_error}")
                    message = "Lieferant gespeichert, aber Umbenennen fehlgeschlagen."
                elif target_path:
                    new_name = target_path.name
                    pdf_path = target_path
                    _set_session_file_entry(file_id, target_path, target_path.name)
            elif date_before:
                _set_result_error(file_id, "rename_skipped: invalid_date")
        _update_last_results(file_id, supplier_name, new_name=new_name)
        corrections = _load_supplier_corrections()
        corrections[file_id] = supplier_name
        _save_supplier_corrections(corrections)
        _append_history(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "file_id": file_id,
                "original_path": str(resolve_pdf_path(filename) or ""),
                "new_path": str(pdf_path or resolve_pdf_path(filename) or ""),
                "filename_before": filename,
                "filename_after": new_name,
                "supplier_before": supplier_before,
                "supplier_after": supplier_name,
                "date_before": date_before,
                "date_after": date_before,
                "action_type": "confirm_supplier",
            }
        )
        if new_name and new_name != filename:
            message = f"Umbenannt zu: {new_name}"
    if _is_ajax_request() and file_id:
        return jsonify(_row_payload(file_id, message=message))
    flash(message)
    return _redirect_after_confirm()


def _update_last_results(file_id: str, supplier_name: str, new_name: str = "") -> None:
    if not file_id:
        return
    results = _load_last_results()
    if not results:
        return
    for item in results:
        if item.get("file_id") == file_id:
            item["supplier"] = supplier_name
            item["supplier_source"] = "db"
            item["supplier_confidence"] = "0.90"
            if new_name:
                item["out_name"] = new_name
            item["supplier_missing"] = _is_supplier_missing(supplier_name)
            item["supplier_broken"] = _is_supplier_broken(supplier_name)
            item["needs_review"] = _is_review_needed(item)
            break
    _save_last_results(results)


def _update_last_results_date(file_id: str, new_name: str, date_iso: str) -> None:
    if not file_id:
        return
    results = _load_last_results()
    if not results:
        return
    for item in results:
        if item.get("file_id") == file_id:
            item["date"] = date_iso
            item["date_source"] = "manual"
            if new_name:
                item["out_name"] = new_name
            item["date_missing"] = _is_date_missing(date_iso, False)
            item["needs_review"] = _is_review_needed(item)
            break
    _save_last_results(results)


def _safe_pdf_name(filename: str) -> str:
    safe_name = secure_filename(filename)
    if not safe_name:
        return ""
    if not _allowed_file(filename):
        return ""
    return safe_name


def _normalize_supplier_input(valAe: str) -> str:
    cleaned = (valAe or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"[^a-zA-Z0-9 ._&-]+", "", cleaned)
    cleaned = cleaned.strip("._- ")
    if len(cleaned) > 60:
        cleaned = cleaned[:60].rstrip()
    return cleaned


def _normalize_date_input(date_input: str, date_format_hint: str = "") -> Optional[datetime]:
    raw = (date_input or "").strip()
    if not raw:
        return None
    formats = []
    if date_format_hint in MANUAL_DATE_FORMATS:
        formats.append(date_format_hint)
    formats.extend(fmt for fmt in MANUAL_DATE_FORMATS if fmt not in formats)
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _find_pdf_path(filename: str) -> Optional[Path]:
    return resolve_pdf_path(filename)


def resolve_pdf_path(filename: str) -> Optional[Path]:
    if not filename:
        return None
    candidates = []
    if _allowed_file(filename):
        candidates.append(filename)
    safe_name = _safe_pdf_name(filename)
    if safe_name and safe_name not in candidates:
        candidates.append(safe_name)
    if not candidates:
        return None
    # Search known roots first; deep scan is optional for performance reasons.
    roots = _allowed_roots()
    for root in roots:
        for name in candidates:
            candidate = root / name
            if candidate.exists():
                return candidate
    if os.getenv("DOCARO_DEEP_SCAN") == "1":
        for root in roots:
            if not root.exists():
                continue
            for name in candidates:
                for candidate in root.rglob(name):
                    if candidate.is_file():
                        return candidate
    return None


def _allowed_roots() -> list[Path]:
    return [
        TMP_DIR,
        INBOX_DIR,
        OUT_DIR,
        DATA_DIR / "fertig",
        BASE_DIR / "daten_eingang",
        BASE_DIR / "daten_fertig",
    ]


def _is_allowed_pdf_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in _allowed_roots():
        try:
            resolved.relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        return True
    return False


def _resolve_file_path(file_id: str) -> Optional[Path]:
    entry = _get_session_file_entry(file_id)
    tried = set()
    if entry:
        path_str = entry.get("path") or ""
        if path_str:
            candidate = Path(path_str)
            if candidate.exists() and _is_allowed_pdf_path(candidate):
                return candidate
        filename = entry.get("filename") or ""
        if filename:
            tried.add(filename)
    result = _result_for_file_id(file_id) or {}
    for key in ("out_name", "filename", "original", "original_name"):
        valAe = result.get(key) or ""
        if valAe:
            tried.add(valAe)
    for name in list(tried):
        safe_name = secure_filename(name)
        if safe_name:
            tried.add(safe_name)
    for name in tried:
        fallback = resolve_pdf_path(name)
        if fallback:
            _set_session_file_entry(file_id, fallback, fallback.name)
            return fallback
    return None


def _get_session_file_entry(file_id: str) -> Optional[dict]:
    data = _load_session_files()
    sid = _get_session_id()
    return data.get(sid, {}).get(file_id)


@contextmanager
def _locked_file(path: Path, mode: str = "a+", retries: int = 20, delay: float = 0.05):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, mode)
    locked = False
    try:
        for _ in range(retries):
            try:
                if msvcrt:
                    lock_mode = msvcrt.LK_LOCK
                    if "r" in mode and "+" not in mode and "w" not in mode and "a" not in mode:
                        lock_mode = msvcrt.LK_RLCK
                    msvcrt.locking(handle.fileno(), lock_mode, 1)
                elif fcntl:
                    lock_mode = fcntl.LOCK_EX
                    if "r" in mode and "+" not in mode and "w" not in mode and "a" not in mode:
                        lock_mode = fcntl.LOCK_SH
                    fcntl.flock(handle.fileno(), lock_mode)
                locked = True
                break
            except OSError:
                time.sleep(delay)
        if not locked:
            raise RuntimeError(f"Lock konnte nicht gesetzt werden: {path}")
        yield handle
    finally:
        if locked:
            try:
                if msvcrt:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                elif fcntl:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def _apply_supplier_corrections(results):
    if results is None:
        return results
    corrections = _load_supplier_corrections()
    if not corrections:
        return results
    changed = False
    for item in results:
        file_id = item.get("file_id")
        if not file_id:
            continue
        corrected = corrections.get(file_id)
        if corrected and item.get("supplier") != corrected:
            item["supplier"] = corrected
            item["supplier_source"] = "manual"
            item["supplier_confidence"] = "1.00"
            changed = True
    if changed:
        _save_last_results(results)
    return results


def _trim_history() -> None:
    if not HISTORY_PATH.exists():
        return
    cutoff = datetime.now() - timedelta(days=max(LOG_RETENTION_DAYS, 1))
    kept = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = entry.get("timestamp") or ""
        try:
            ts_dt = datetime.fromisoformat(ts)
        except ValueError:
            kept.append(entry)
            continue
        if ts_dt >= cutoff:
            kept.append(entry)
    payload = "\n".join(json.dumps(entry, ensure_ascii=True) for entry in kept)
    HISTORY_PATH.write_text((payload + "\n") if payload else "", encoding="utf-8")


def _rename_pdf_with_name(pdf_path: Path, filename: str) -> Tuple[Optional[Path], str]:
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        target_path = get_unique_path(OUT_DIR, filename)
        if pdf_path.resolve() == target_path.resolve():
            return pdf_path, ""
        pdf_path.replace(target_path)
        return target_path, ""
    except OSError as exc:
        return None, str(exc)


def _set_result_error(file_id: str, message: str) -> None:
    results = _load_last_results() or []
    for item in results:
        if item.get("file_id") == file_id:
            item["error"] = message
            break
    _save_last_results(results)


def _result_for_filename(filename: str):
    results = _load_last_results() or []
    for item in results:
        if item.get("out_name") == filename:
            return item
    return None


def _result_for_file_id(file_id: str):
    results = _load_last_results() or []
    for item in results:
        if item.get("file_id") == file_id:
            return item
    return None


def _is_review_needed(item: dict) -> bool:
    if item.get("date_missing"):
        return True
    if item.get("supplier_missing"):
        return True
    if item.get("supplier_broken"):
        return True
    if item.get("supplier_source") == "heuristic":
        return True
    try:
        confidence = float(item.get("supplier_confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    return confidence < 0.85


def _review_list():
    results = _load_last_results() or []
    results = _attach_file_ids(results) or []
    results = _apply_result_flags(results) or []
    return [item for item in results if item.get("needs_review")]


@app.get("/view/<file_id>")
def view_pdf(file_id: str):
    result = _result_for_file_id(file_id)
    if not result:
        return _render_view_pdf(file_id, pdf_missing=True)
    if not _resolve_file_path(file_id):
        _set_result_error(file_id, "pdf_open_failed: file_not_found")
        return _render_view_pdf(file_id, pdf_missing=True)
    return _render_view_pdf(file_id)


def _build_view_context(
    file_id: str,
    date_error: str = "",
    date_valAe: str = "",
    date_fmt: str = "",
    pdf_missing: bool = False,
) -> dict:
    result = _result_for_file_id(file_id) or {}
    supplier = result.get("supplier") or "Unbekannt"
    supplier_guess_line = result.get("supplier_guess_line") or ""
    supplier_source = result.get("supplier_source") or ""
    supplier_confidence = result.get("supplier_confidence") or ""
    filename = result.get("out_name") or result.get("filename") or file_id
    date_valAe = date_valAe or result.get("date") or ""
    date_fmt = date_fmt if date_fmt in MANUAL_DATE_FORMATS else INTERNAL_DATE_FORMAT
    review_items = _review_list()
    review_total = len(review_items)
    review_index = 0
    if review_total:
        for idx, item in enumerate(review_items, start=1):
            if item.get("file_id") == file_id:
                review_index = idx
                break
    title = f"Docaro | {supplier} | {filename}"
    return {
        "title": title,
        "filename": filename,
        "file_id": file_id,
        "supplier": supplier,
        "supplier_guess_line": supplier_guess_line,
        "supplier_source": supplier_source,
        "supplier_confidence": supplier_confidence,
        "review_index": review_index,
        "review_total": review_total,
        "date_valAe": date_valAe,
        "date_error": date_error,
        "date_fmt": date_fmt,
        "pdf_missing": pdf_missing,
    }


def _render_view_pdf(
    file_id: str,
    date_error: str = "",
    date_valAe: str = "",
    date_fmt: str = "",
    pdf_missing: bool = False,
):
    return render_template(
        "view_pdf.html",
        **_build_view_context(
            file_id,
            date_error=date_error,
            date_valAe=date_valAe,
            date_fmt=date_fmt,
            pdf_missing=pdf_missing,
        ),
    )


@app.post("/confirm_date_from_view")
def confirm_date_from_view():
    file_id = request.form.get("file_id", "").strip()
    if not file_id:
        abort(404)
    result = _result_for_file_id(file_id)
    if not result:
        abort(404)
    result = result or {}
    filename = result.get("out_name") or ""

    pdf_path = _resolve_file_path(file_id) or resolve_pdf_path(filename)
    if not pdf_path:
        _set_result_error(file_id, "pdf_open_failed: file_not_found")
        return _render_view_pdf(file_id, pdf_missing=True), 404

    date_input = request.form.get("date_input", "").strip()
    date_fmt = request.form.get("date_fmt", "").strip()
    date_obj = _normalize_date_input(date_input, date_fmt)
    if not date_obj:
        return _render_view_pdf(
            file_id,
            date_error="Ungültiges Datum. Bitte TT.MM.JJJJ, TT.MM.JJ oder YYYY-MM-DD eingeben.",
            date_valAe=date_input,
            date_fmt=date_fmt,
        )

    if date_fmt not in ALLOWED_DATE_FORMATS:
        date_fmt = INTERNAL_DATE_FORMAT

    supplier = (result.get("supplier") or "").strip() or "Unbekannt"

    new_filename = build_new_filename(supplier, date_obj, date_format=date_fmt)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if pdf_path.name == new_filename and pdf_path.parent == OUT_DIR:
        target_path = pdf_path
    else:
        target_path = get_unique_path(OUT_DIR, new_filename)
        try:
            pdf_path.replace(target_path)
        except OSError:
            return _render_view_pdf(file_id, date_error="Datei konnte nicht umbenannt werden.")

    date_iso = date_obj.strftime(INTERNAL_DATE_FORMAT)
    _set_session_file_entry(file_id, target_path, target_path.name)
    _update_last_results_date(file_id, target_path.name, date_iso)
    if target_path and target_path.name != filename:
        flash(f"Umbenannt zu: {target_path.name}")
    _append_history(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "file_id": file_id,
            "original_path": str(pdf_path),
            "new_path": str(target_path),
            "filename_before": filename,
            "filename_after": target_path.name,
            "supplier_before": supplier,
            "supplier_after": supplier,
            "date_before": result.get("date") or "",
            "date_after": date_iso,
            "action_type": "confirm_date",
        }
    )
    flash("Datum gespeichert.")
    return redirect(url_for("review_next", current=file_id))


@app.post("/confirm_date")
def confirm_date():
    file_id = request.form.get("file_id", "").strip()
    if not file_id:
        abort(404)
    result = _result_for_file_id(file_id)
    if not result:
        abort(404)
    result = result or {}
    filename = result.get("out_name") or ""
    pdf_path = _resolve_file_path(file_id) or resolve_pdf_path(filename)
    if not pdf_path:
        _set_result_error(file_id, "pdf_open_failed: file_not_found")
        message = "Datei nicht gefunden."
        if _is_ajax_request():
            return jsonify({"ok": False, "message": message}), 404
        flash(message)
        return redirect(url_for("index"))

    date_input = request.form.get("date_input", "").strip()
    date_fmt = request.form.get("date_fmt", "").strip()
    date_obj = _normalize_date_input(date_input, date_fmt)
    if not date_obj:
        message = "Ungültiges Datum. Bitte TT.MM.JJJJ, TT.MM.JJ oder YYYY-MM-DD eingeben."
        if _is_ajax_request():
            return jsonify({"ok": False, "message": message}), 400
        flash(message)
        return redirect(url_for("index"))

    if date_fmt not in ALLOWED_DATE_FORMATS:
        date_fmt = INTERNAL_DATE_FORMAT

    supplier = (result.get("supplier") or "").strip() or "Unbekannt"

    new_filename = build_new_filename(supplier, date_obj, date_format=date_fmt)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if pdf_path.name == new_filename and pdf_path.parent == OUT_DIR:
        target_path = pdf_path
    else:
        target_path = get_unique_path(OUT_DIR, new_filename)
        try:
            pdf_path.replace(target_path)
        except OSError:
            flash("Datei konnte nicht umbenannt werden.")
            return redirect(url_for("index"))

    date_iso = date_obj.strftime(INTERNAL_DATE_FORMAT)
    _set_session_file_entry(file_id, target_path, target_path.name)
    _update_last_results_date(file_id, target_path.name, date_iso)
    message = "Datum gespeichert."
    if target_path and target_path.name != filename:
        message = f"Umbenannt zu: {target_path.name}"
    _append_history(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "file_id": file_id,
            "original_path": str(pdf_path),
            "new_path": str(target_path),
            "filename_before": filename,
            "filename_after": target_path.name,
            "supplier_before": supplier,
            "supplier_after": supplier,
            "date_before": result.get("date") or "",
            "date_after": date_iso,
            "action_type": "confirm_date",
        }
    )
    if _is_ajax_request():
        return jsonify(_row_payload(file_id, message=message))
    flash(message)
    return redirect(url_for("index"))


@app.get("/pdf/<path:filename>")
def pdf_file(filename: str):
    safe_name = _safe_pdf_name(filename)
    if not safe_name:
        abort(404)
    pdf_path = resolve_pdf_path(safe_name)
    if not pdf_path:
        abort(404)
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False)


@app.get("/raw/<file_id>")
def raw_pdf(file_id: str):
    result = _result_for_file_id(file_id)
    if not result:
        return (
            "<!doctype html><html><body><p>Datei nicht gefunden.</p></body></html>",
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )
    filename = result.get("out_name") or ""
    pdf_path = _resolve_file_path(file_id) or resolve_pdf_path(filename)
    if not pdf_path:
        _set_result_error(file_id, "pdf_open_failed: file_not_found")
        return (
            "<!doctype html><html><body><p>Datei nicht gefunden.</p></body></html>",
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )
    response = send_file(pdf_path, mimetype="application/pdf", as_attachment=False, download_name=filename or file_id)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/undo_last")
def undo_last():
    entry = _latest_history_entry()
    if not entry:
        flash("Keine Änderung zum Rückgängigmachen.")
        return redirect(url_for("index"))

    file_id = entry.get("file_id") or ""
    original_path = Path(entry.get("original_path") or "")
    new_path = Path(entry.get("new_path") or "")
    filename_before = entry.get("filename_before") or ""
    filename_after = entry.get("filename_after") or ""
    supplier_before = entry.get("supplier_before") or ""
    date_before = entry.get("date_before") or ""

    if new_path and new_path.exists() and original_path and original_path != new_path:
        target = original_path
        if target.exists():
            target = get_unique_path(target.parent, target.name)
        try:
            new_path.replace(target)
            filename_before = target.name
        except OSError:
            flash("Rückgängig fehlgeschlagen.")
            return redirect(url_for("index"))

    results = _load_last_results() or []
    for item in results:
        if (file_id and item.get("file_id") == file_id) or item.get("out_name") == filename_after:
            item["out_name"] = filename_before or item.get("out_name")
            item["supplier"] = supplier_before
            item["supplier_source"] = "manual" if supplier_before else ""
            item["supplier_confidence"] = ""
            item["date"] = date_before
            item["date_source"] = "manual" if date_before else ""
            item["supplier_missing"] = _is_supplier_missing(item.get("supplier"))
            item["date_missing"] = _is_date_missing(item.get("date"), False)
            item["needs_review"] = _is_review_needed(item)
            break
    _save_last_results(results)

    if file_id and filename_before:
        target_path = original_path if original_path.exists() else resolve_pdf_path(filename_before)
        if target_path:
            _set_session_file_entry(file_id, target_path, filename_before)

    _append_history(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "file_id": file_id,
            "original_path": str(new_path),
            "new_path": str(original_path),
            "filename_before": filename_after,
            "filename_after": filename_before,
            "supplier_before": entry.get("supplier_after") or "",
            "supplier_after": supplier_before,
            "date_before": entry.get("date_after") or "",
            "date_after": date_before,
            "action_type": "undo",
        }
    )
    flash("Letzte Änderung rückgängig gemacht.")
    return redirect(url_for("index"))


@app.get("/review/next")
def review_next():
    current_raw = request.args.get("current", "").strip()
    current = current_raw if current_raw else ""
    review_items = _review_list()
    if not review_items:
        flash("Keine weiteren unbekannten PDFs - fertig!")
        return redirect(url_for("upload_overview"))

    file_ids = [item.get("file_id") for item in review_items if item.get("file_id")]
    next_id = file_ids[0] if file_ids else ""
    if current and current in file_ids:
        idx = file_ids.index(current)
        next_id = file_ids[(idx + 1) % len(file_ids)]
    if not next_id:
        flash("Keine weiteren unbekannten PDFs - fertig!")
        return redirect(url_for("upload_overview"))
    return redirect(url_for("view_pdf", file_id=next_id))


def _find_supplier_entry(suppliers, name: str):
    target_key = normalize_text(name)
    for entry in suppliers:
        entry_name = str(entry.get("name", "")).strip()
        if normalize_text(entry_name) == target_key:
            return entry
    return None


def _merge_aliases(target, aliases):
    existing = target.setdefault("aliases", [])
    for alias in aliases:
        if alias and all(normalize_text(a) != normalize_text(alias) for a in existing):
            existing.append(alias)


@app.get("/suppliers")
def suppliers():
    data = load_suppliers_db()
    suppliers_list = sorted(data.get("suppliers", []), key=lambda item: item.get("name", "").lower())
    return render_template("suppliers.html", suppliers=suppliers_list)


@app.post("/suppliers/rename")
def suppliers_rename():
    old_name = request.form.get("old_name", "").strip()
    new_name = request.form.get("new_name", "").strip()
    if len(old_name) < 2 or len(new_name) < 2:
        flash("Lieferantenname ungültig.")
        return redirect(url_for("suppliers"))

    data = load_suppliers_db()
    suppliers_list = data.get("suppliers", [])
    target = _find_supplier_entry(suppliers_list, old_name)
    if not target:
        flash("Lieferant nicht gefunden.")
        return redirect(url_for("suppliers"))

    existing = _find_supplier_entry(suppliers_list, new_name)
    if existing and existing is not target:
        _merge_aliases(existing, target.get("aliases", []))
        suppliers_list.remove(target)
    else:
        target["name"] = new_name

    data["suppliers"] = suppliers_list
    save_suppliers_db(data)
    flash("Lieferant aktualisiert.")
    return redirect(url_for("suppliers"))


@app.post("/suppliers/alias/add")
def suppliers_alias_add():
    supplier_name = request.form.get("supplier_name", "").strip()
    alias = request.form.get("alias", "").strip()
    if len(supplier_name) < 2 or len(alias) < 2:
        flash("Alias ungAeltig.")
        return redirect(url_for("suppliers"))

    data = load_suppliers_db()
    suppliers_list = data.get("suppliers", [])
    target = _find_supplier_entry(suppliers_list, supplier_name)
    if not target:
        flash("Lieferant nicht gefunden.")
        return redirect(url_for("suppliers"))

    _merge_aliases(target, [alias])
    data["suppliers"] = suppliers_list
    save_suppliers_db(data)
    flash("Alias gespeichert.")
    return redirect(url_for("suppliers"))


@app.post("/suppliers/alias/remove")
def suppliers_alias_remove():
    supplier_name = request.form.get("supplier_name", "").strip()
    alias = request.form.get("alias", "").strip()
    if len(supplier_name) < 2 or not alias:
        flash("Alias ungAeltig.")
        return redirect(url_for("suppliers"))

    data = load_suppliers_db()
    suppliers_list = data.get("suppliers", [])
    target = _find_supplier_entry(suppliers_list, supplier_name)
    if not target:
        flash("Lieferant nicht gefunden.")
        return redirect(url_for("suppliers"))

    aliases = target.get("aliases", [])
    target["aliases"] = [a for a in aliases if normalize_text(a) != normalize_text(alias)]
    data["suppliers"] = suppliers_list
    save_suppliers_db(data)
    flash("Alias entfernt.")
    return redirect(url_for("suppliers"))


@app.post("/suppliers/delete")
def suppliers_delete():
    supplier_name = request.form.get("supplier_name", "").strip()
    if len(supplier_name) < 2:
        flash("Lieferant ungültig.")
        return redirect(url_for("suppliers"))

    data = load_suppliers_db()
    suppliers_list = data.get("suppliers", [])
    target = _find_supplier_entry(suppliers_list, supplier_name)
    if not target:
        flash("Lieferant nicht gefunden.")
        return redirect(url_for("suppliers"))

    suppliers_list.remove(target)
    data["suppliers"] = suppliers_list
    save_suppliers_db(data)
    flash("Lieferant gelöscht.")
    return redirect(url_for("suppliers"))


@app.get("/download/<path:filename>")
def download(filename: str):
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        abort(404)
    if not _allowed_file(safe_name):
        abort(404)
    if safe_name not in _session_filenames():
        abort(404)
    pdf_path = resolve_pdf_path(safe_name)
    if not pdf_path:
        abort(404)
    return send_file(pdf_path, as_attachment=True, download_name=safe_name)


@app.get("/download_all.zip")
def download_all():
    filenames = sorted(_session_filenames())
    if not filenames:
        abort(404)
    pdfs = []
    for name in filenames:
        path = resolve_pdf_path(name)
        if path:
            pdfs.append(path)
    if not pdfs:
        abort(404)

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for pdf in pdfs:
            zf.write(pdf, arcname=pdf.name)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name="docaro_fertig.zip",
    )


if __name__ == "__main__":
    # Start from repo root with: python app/app.py
    app.run(debug=DEBUG_MODE, use_reloader=False)
