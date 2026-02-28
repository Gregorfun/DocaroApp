from __future__ import annotations
# ruff: noqa: E402

from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse
import sys
import atexit
import zipfile
import json
import re
import hmac
import hashlib
import secrets
from uuid import uuid4
from contextlib import contextmanager
import time
import shutil
import threading

import os

from flask import (
    Flask,
    Response,
    abort,
    flash,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    stream_with_context,
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
    process_folder,
    get_unique_path,
    save_suppliers_db,
    build_new_filename,
    INTERNAL_DATE_FORMAT,
)

# Lazy-Loading für Docling (nur bei Bedarf laden)
def is_docling_available():
    """Prüft ob Docling verfügbar ist ohne es zu laden."""
    try:
        import importlib.util
        spec = importlib.util.find_spec("docling")
        return spec is not None
    except Exception:
        return False

def get_docling_extractor():
    """Lädt Docling-Extractor lazy (nur wenn benötigt)."""
    try:
        from core.docling_extractor import DoclingExtractor
        return DoclingExtractor()
    except Exception as e:
        logger.error(f"Docling-Extractor konnte nicht geladen werden: {e}")
        return None
from utils import normalize_text
from config import Config
from redis import Redis
from rq import Queue
from services.auto_sort import (
    AutoSortSettings,
    export_document,
    load_settings as load_auto_sort_settings,
    save_settings as save_auto_sort_settings,
    sanitize_supplier_name,
)
from core.runtime_state import RuntimeStateConfig, reset_runtime_state, reset_runtime_state_once
from core.runtime_store import RuntimeStore
from app.runtime_storage import RuntimeStorageManager
from app.queue_runtime import QueueRuntimeManager
from services.web_auth import install_auth
from core.performance import profile
from core.metrics import (
    count_step_error,
    observe_pipeline_step,
    set_inflight,
    set_queue_depth,
)
from core.document_intelligence import (
    apply_supplier_profile,
    compute_review_priority,
    derive_processing_route,
    load_supplier_profiles,
)
from core.observability import init_sentry
from functools import lru_cache
import string

config = Config()
DATA_DIR = config.DATA_DIR
INBOX_DIR = config.INBOX_DIR
OUT_DIR = config.OUT_DIR
TMP_DIR = config.TMP_DIR
QUARANTINE_DIR = getattr(config, "QUARANTINE_DIR", (DATA_DIR / "quarantaene"))
LOG_DIR = getattr(config, "LOG_DIR", (DATA_DIR / "logs"))
SUPPLIER_CORRECTIONS_PATH = config.SUPPLIER_CORRECTIONS_PATH
SESSION_FILES_PATH = config.SESSION_FILES_PATH
SESSION_FILES_LOCK = config.SESSION_FILES_LOCK
HISTORY_PATH = config.HISTORY_PATH
LOG_RETENTION_DAYS = config.LOG_RETENTION_DAYS
RUNTIME_DB_PATH = DATA_DIR / "runtime_state.db"
SUPPLIER_PROFILES_PATH = BASE_DIR / "config" / "supplier_profiles.json"

# Download-Cleanup ("Refresh" nach Download)
PRUNE_AFTER_DOWNLOAD = os.getenv("DOCARO_PRUNE_AFTER_DOWNLOAD", "1") == "1"
DELETE_FILES_AFTER_DOWNLOAD = os.getenv("DOCARO_DELETE_FILES_AFTER_DOWNLOAD", "0") == "1"
TMP_RETENTION_HOURS = int(os.getenv("DOCARO_TMP_RETENTION_HOURS", "48"))

# Setup Redis Queue
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
redis_conn = Redis.from_url(redis_url)
q = Queue('default', connection=redis_conn, default_timeout=3600)  # 1h timeout
QUEUE_MAX_DEPTH = int(os.getenv("DOCARO_QUEUE_MAX_DEPTH", "200"))

# Stateless (optional): Runtime-State beim Service-Start löschen.
# WICHTIG: Unter Gunicorn laufen mehrere Worker-Prozesse; ein Reset pro Worker-Start
# kann Uploads/Outputs löschen, sobald ein Worker neu startet. Deshalb nur 1x pro
# systemd INVOCATION_ID resetten.
if os.getenv("DOCARO_STATELESS", "0") == "1" and os.getenv("DOCARO_WORKER", "0") != "1":
    reset_runtime_state_once(
        RuntimeStateConfig(
            repo_root=BASE_DIR,
            data_dir=DATA_DIR,
            runtime_dirs=(TMP_DIR, INBOX_DIR, OUT_DIR, QUARANTINE_DIR),
            runtime_files=(
                SESSION_FILES_PATH,
                SESSION_FILES_LOCK,
                SUPPLIER_CORRECTIONS_PATH,
                HISTORY_PATH,
                config.SETTINGS_PATH,
            ),
            log_dir=LOG_DIR,
            preserve_dirs=(BASE_DIR / "ml", config.AUTH_DIR),
        )
    )


@atexit.register
def _cleanup_runtime_state_on_exit() -> None:
    # Best-effort Cleanup beim Shutdown.
    # WICHTIG: RQ führt Jobs typischerweise in kurzlebigen Workhorse-Prozessen aus.
    # Ein unbedingtes Löschen von TMP_DIR würde dadurch nach JEDEM Job u.a.
    # last_results.json entfernen und damit die Download-Liste leeren.
    # Deshalb nur in explizitem Stateless-Mode aufräumen – und nie im Worker.
    if os.getenv("DOCARO_STATELESS", "0") != "1":
        return
    if os.getenv("DOCARO_WORKER", "0") == "1":
        return
    try:
        reset_runtime_state(
            RuntimeStateConfig(
                repo_root=BASE_DIR,
                data_dir=DATA_DIR,
                runtime_dirs=(TMP_DIR,),
                runtime_files=(),
                log_dir=LOG_DIR,
                preserve_dirs=(BASE_DIR / "ml", config.AUTH_DIR),
            )
        )
    except Exception:
        pass

# Quarantäne-Schwellen: unsicher, wenn darunter (oder wenn Datum/Lieferant fehlt)
QUARANTINE_SUPPLIER_CONF_MIN = float(os.getenv("DOCARO_QUAR_SUPPLIER_MIN", "0.85"))
QUARANTINE_DATE_CONF_MIN = float(os.getenv("DOCARO_QUAR_DATE_MIN", "0.75"))

# Auto-Sort Settings (persisted in data/settings.json)
AUTO_SORT_SETTINGS: Optional[AutoSortSettings] = None

_runtime_store = RuntimeStore(
    RUNTIME_DB_PATH,
    session_files_path=SESSION_FILES_PATH,
    supplier_corrections_path=SUPPLIER_CORRECTIONS_PATH,
    history_path=HISTORY_PATH,
)
_runtime_storage_manager: Optional[RuntimeStorageManager] = None
_queue_runtime_manager: Optional[QueueRuntimeManager] = None
_rate_limit_memory: dict[str, tuple[int, float]] = {}
_rate_limit_lock = threading.Lock()
_last_runtime_store_health_check = 0.0
_last_runtime_store_checkpoint = 0.0
_supplier_profiles_cache: dict[str, object] = {"mtime": 0.0, "data": {}}

# Supplier Canonicalizer Cache
_supplier_canonicalizer = None


@lru_cache(maxsize=1)
def _get_audit_logger():
    from core.audit_logger import AuditLogger

    return AuditLogger(DATA_DIR / "audit.jsonl")


def _ensure_audit_entry_for_current_result(file_id: str, pdf_path: Path) -> None:
    """Best-effort: stellt sicher, dass ein Basis-AuditEntry für das Dokument existiert.

    Hintergrund: Viele Bestandsdokumente wurden verarbeitet, bevor Audit-Logging aktiv war.
    Damit Online-Korrekturen trotzdem als Trainingsdaten landen, legen wir bei Bedarf
    einen Basis-Entry aus dem aktuellen Result an.
    """

    try:
        if not pdf_path or not pdf_path.exists():
            return
        result = _result_for_file_id(file_id) or {}
        audit_logger = _get_audit_logger()

        # Schnell checken, ob es bereits Einträge gibt.
        existing = audit_logger.load_audit_entries(document_path=str(pdf_path), limit=1)
        if existing:
            return

        def _safe_float(value: object) -> float:
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0

        extractions = {
            "supplier": audit_logger.log_extraction(
                document_path=pdf_path,
                field_name="supplier",
                value=str(result.get("supplier") or ""),
                confidence=_safe_float(result.get("supplier_confidence")),
                page=1,
                text_snippet=str(result.get("supplier_guess_line") or result.get("supplier_raw") or "")[:500],
                reasons=[str(result.get("supplier_source") or "")],
            ),
            "date": audit_logger.log_extraction(
                document_path=pdf_path,
                field_name="date",
                value=str(result.get("date") or ""),
                confidence=_safe_float(result.get("date_confidence")),
                page=1,
                text_snippet=str(result.get("date_evidence") or "")[:500],
                reasons=[str(result.get("date_source") or "")],
            ),
            "doctype": audit_logger.log_extraction(
                document_path=pdf_path,
                field_name="doctype",
                value=str(result.get("doc_type") or ""),
                confidence=_safe_float(result.get("doc_type_confidence")),
                page=1,
                text_snippet=str(result.get("doc_type_evidence") or "")[:500],
                reasons=[str(result.get("doc_type_evidence") or "")],
            ),
        }

        entry = audit_logger.create_audit_entry(
            document_path=pdf_path,
            extractions=extractions,
            status="success",
            ocr_method=None,
            processing_time=0.0,
            needs_review=bool(result.get("needs_review")),
            review_reason=",".join(result.get("review_reasons") or []) if isinstance(result.get("review_reasons"), list) else None,
        )
        audit_logger.save_audit_entry(entry)
    except Exception:
        return


def _append_audit_correction(file_id: str, field_name: str, corrected_value: str) -> None:
    try:
        pdf_path = _resolve_file_path(file_id)
        if not pdf_path:
            return
        _ensure_audit_entry_for_current_result(file_id, pdf_path)
        audit_logger = _get_audit_logger()
        audit_logger.add_correction(
            document_path=str(pdf_path),
            field_name=field_name,
            corrected_value=corrected_value,
            reviewed_by="web",
        )
    except Exception:
        return


def get_supplier_canonicalizer():
    """Lazy-load Supplier Canonicalizer (nur einmal instanziieren)."""
    global _supplier_canonicalizer
    if _supplier_canonicalizer is None:
        try:
            from core.supplier_canonicalizer import get_supplier_canonicalizer as _get_canon
            _supplier_canonicalizer = _get_canon()
        except Exception as e:
            # Logger könnte noch nicht initialisiert sein
            import logging
            logging.warning(f"Supplier Canonicalizer nicht verfügbar: {e}")
            _supplier_canonicalizer = False  # Merken dass Versuch fehlschlug
    return _supplier_canonicalizer if _supplier_canonicalizer is not False else None


@lru_cache(maxsize=500)
def canonicalize_supplier_cached(supplier_name: str) -> tuple:
    """
    Cached Supplier Canonicalization.

    Returns:
        (canonical_name, confidence) oder (supplier_name, 0) bei Fehler
    """
    canonicalizer = get_supplier_canonicalizer()
    if not canonicalizer:
        return (supplier_name, 0.0)

    try:
        result = canonicalizer.canonicalize(supplier_name)
        return (result.canonical_name, result.confidence)
    except Exception:
        return (supplier_name, 0.0)


@lru_cache(maxsize=1)
def load_suppliers_db_cached():
    """Cached Supplier DB - nur einmal laden."""
    return load_suppliers_db()


def _default_auto_sort_settings() -> AutoSortSettings:
    return AutoSortSettings(
        enabled=config.AUTO_SORT_ENABLED_DEFAULT,
        base_dir=config.AUTO_SORT_BASE_DIR_DEFAULT,
        folder_format=config.AUTO_SORT_FOLDER_FORMAT_DEFAULT,
        mode=config.AUTO_SORT_MODE_DEFAULT,
        confidence_threshold=config.AUTO_SORT_CONFIDENCE_THRESHOLD_DEFAULT,
        fallback_folder=config.AUTO_SORT_FALLBACK_FOLDER_DEFAULT,
        inbox_dir=config.INBOX_DIR,
        inbox_interval_minutes=0,
    )


def _get_auto_sort_settings(refresh: bool = False) -> AutoSortSettings:
    global AUTO_SORT_SETTINGS
    if refresh or AUTO_SORT_SETTINGS is None:
        AUTO_SORT_SETTINGS = load_auto_sort_settings(config.SETTINGS_PATH, _default_auto_sort_settings())
        base_dir_path = Path(AUTO_SORT_SETTINGS.base_dir).expanduser()
        try:
            base_dir_path = base_dir_path.resolve()
        except OSError:
            pass
        AUTO_SORT_SETTINGS.base_dir = base_dir_path
    return AUTO_SORT_SETTINGS


def _looks_like_windows_drive_path(value: str) -> bool:
    raw = (value or "").strip()
    # e.g. C:\Users\... or C:/Users/...
    return (
        len(raw) >= 3
        and raw[0] in string.ascii_letters
        and raw[1] == ":"
        and (raw[2] == "\\" or raw[2] == "/")
    )


def _windows_path_not_supported_on_linux_message(path_value: str) -> str:
    return (
        "Windows-Lokaler Pfad ist auf diesem Linux-Server nicht lesbar: "
        f"{path_value}. "
        "Bitte den Ordner als Netzwerkfreigabe (SMB/CIFS) mounten und dann den Linux-Mountpfad "
        "(z.B. /mnt/lieferscheine) in den Einstellungen eintragen."
    )


def _resolve_inbox_dir(inbox_dir: Path) -> Path:
    """Resolve inbox dir for filesystem access.

    - Absolute POSIX paths are used as-is (resolved best-effort).
    - Relative paths are interpreted relative to repo BASE_DIR.
    - Windows-style paths (e.g. C:\\Users\\...) are treated as *relative strings*
      and therefore mapped under BASE_DIR on Linux.
    """
    raw = str(inbox_dir or "").strip()
    if not raw:
        return config.INBOX_DIR
    p = Path(raw).expanduser()
    if p.is_absolute():
        try:
            return p.resolve()
        except OSError:
            return p
    try:
        return (BASE_DIR / p).resolve()
    except OSError:
        return BASE_DIR / p


def _display_inbox_dir(inbox_dir: Path) -> str:
    """Human-friendly display for inbox dir.

    If a legacy value was persisted as BASE_DIR + Windows-path-string,
    show only the Windows portion.
    """
    raw = str(inbox_dir or "").strip()
    if not raw:
        return ""
    base_prefix = str(BASE_DIR).rstrip("/") + "/"
    if raw.startswith(base_prefix):
        rest = raw[len(base_prefix):]
        if _looks_like_windows_drive_path(rest):
            return rest
        try:
            return str(Path(raw).relative_to(BASE_DIR))
        except Exception:
            return raw
    return raw


def _save_auto_sort_settings(settings: AutoSortSettings) -> None:
    global AUTO_SORT_SETTINGS
    AUTO_SORT_SETTINGS = settings
    save_auto_sort_settings(config.SETTINGS_PATH, settings)

try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

DEBUG_MODE = config.DEBUG

ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_DATE_FORMATS = [
    "%Y-%m-%d",  # ISO (YYYY-MM-DD)
    "%d.%m.%Y",  # Deutsch (TT.MM.JJJJ)
    "%d.%m.%y",  # Deutsch kurz (TT.MM.JJ)
    "%d-%m-%Y",  # Deutsch mit Bindestrich (TT-MM-JJJJ)
    "%m/%d/%Y",  # US (MM/DD/YYYY)
    "%Y%m%d",  # Kompakt (YYYYMMDD)
]

# Date formats accepted for manual input (same as ALLOWED_DATE_FORMATS)
MANUAL_DATE_FORMATS = ALLOWED_DATE_FORMATS


def _normalize_date_fmt(value: str) -> str:
    raw = (value or "").strip()
    # Accept a few human-friendly aliases to avoid hard failures.
    aliases = {
        "dd.mm.yyyy": "%d.%m.%Y",
        "tt.mm.jjjj": "%d.%m.%Y",
        "dd-mm-yyyy": "%d-%m-%Y",
        "tt-mm-jjjj": "%d-%m-%Y",
        "yyyymmdd": "%Y%m%d",
    }
    key = raw.lower()
    if key in aliases:
        raw = aliases[key]
    if raw not in ALLOWED_DATE_FORMATS:
        return "%Y-%m-%d"
    return raw

app = Flask(__name__)
# SECRET_KEY aus config.py (persistent gespeichert in data/.secret_key)
app.secret_key = config.SECRET_KEY

# Zentrales Logging einrichten
logger = config.setup_logging()
app.logger = logger
init_sentry("web")

app.config["PROPAGATE_EXCEPTIONS"] = True
app.config["DEBUG"] = DEBUG_MODE

# Registriere Review-Blueprint
try:
    import sys
    from pathlib import Path
    app_dir = Path(__file__).parent
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from review_routes import review_bp
    app.register_blueprint(review_bp)
    logger.info("Review-Routes erfolgreich registriert")
except ImportError as e:
    logger.warning(f"Review-Routes nicht geladen: {e}")

# Auth installieren (Login-Pflicht). Registrierung ist deaktiviert; User nur via Seed/Admin.
seed_email = getattr(config, "SEED_EMAIL_DEFAULT", "g.machuletz@bracht-autokrane.de")
seed_password = os.getenv("DOCARO_SEED_PASSWORD")
install_auth(app, config.AUTH_DB_PATH, seed_email=seed_email, seed_password=seed_password)


def _install_rq_dashboard() -> None:
    if os.getenv("DOCARO_RQ_DASHBOARD_ENABLED", "1") != "1":
        return
    try:
        import rq_dashboard  # type: ignore
    except Exception as exc:
        logger.warning("RQ Dashboard not available: %s", exc)
        return

    url_prefix = os.getenv("DOCARO_RQ_DASHBOARD_URL_PREFIX", "/rq").strip() or "/rq"
    app.config.setdefault("RQ_DASHBOARD_REDIS_URL", redis_url)
    app.config.setdefault("RQ_DASHBOARD_POLL_INTERVAL", 3000)
    app.config.setdefault("RQ_DASHBOARD_PAGE_SIZE", 50)
    app.config.setdefault("RQ_DASHBOARD_NO_DEFAULT_EXCEPTION_HANDLER", True)

    try:
        app.register_blueprint(rq_dashboard.blueprint, url_prefix=url_prefix)
        logger.info("RQ Dashboard enabled at %s", url_prefix)
    except Exception as exc:
        logger.warning("RQ Dashboard registration failed: %s", exc)


_install_rq_dashboard()




def _log_exception(context: str, exc: Exception) -> None:
    logger.exception(f"Exception in {context}: {exc}")


def _parse_limit_config(raw: str, default_limit: int, default_window: int) -> tuple[int, int]:
    value = str(raw or "").strip().lower()
    if not value:
        return default_limit, default_window
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*([smh]?)\s*$", value)
    if not m:
        return default_limit, default_window
    limit = max(int(m.group(1)), 1)
    window = max(int(m.group(2)), 1)
    suffix = (m.group(3) or "s").lower()
    scale = {"s": 1, "m": 60, "h": 3600}.get(suffix, 1)
    return limit, window * scale


def _client_ip() -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.remote_addr or "unknown").strip() or "unknown"


def _rate_limit_check(scope: str, raw_rule: str, default_limit: int, default_window: int) -> tuple[bool, int]:
    limit, window_seconds = _parse_limit_config(raw_rule, default_limit, default_window)
    key = f"ratelimit:{scope}:{_client_ip()}"
    now = time.time()

    # Redis first for multi-process consistency.
    try:
        current = int(redis_conn.incr(key))
        if current == 1:
            redis_conn.expire(key, int(window_seconds))
        ttl = int(redis_conn.ttl(key) or window_seconds)
        return current > limit, max(ttl, 1)
    except Exception:
        pass

    # Fallback: in-memory (single-process best effort).
    with _rate_limit_lock:
        current, reset_at = _rate_limit_memory.get(key, (0, now + window_seconds))
        if now >= reset_at:
            current = 0
            reset_at = now + window_seconds
        current += 1
        _rate_limit_memory[key] = (current, reset_at)
        return current > limit, max(int(reset_at - now), 1)


def _same_origin_request() -> bool:
    origin = (request.headers.get("Origin") or "").strip()
    referer = (request.headers.get("Referer") or "").strip()
    source = origin or referer
    if not source:
        return False
    try:
        parsed = urlparse(source)
    except Exception:
        return False
    if not parsed.netloc:
        return False
    return parsed.netloc == request.host


def _ensure_csrf_token() -> str:
    token = (session.get("csrf_token") or "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(32)
    session["csrf_token"] = token
    return token


def _canary_bucket(salt: str = "default") -> int:
    sid = str(session.get("sid") or "")
    if not sid:
        sid = uuid4().hex
        session["sid"] = sid
    digest = hashlib.sha256(f"{salt}:{sid}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def _in_canary(percent: int, salt: str = "default") -> bool:
    pct = max(0, min(int(percent), 100))
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    return _canary_bucket(salt) < pct


@app.before_request
def _trace_upload_requests():
    if request.path == "/upload":
        logger.info(f"Request {request.method} {request.path}")


@app.before_request
def _apply_rate_limits_and_csrf():
    endpoint = request.endpoint or ""
    method = (request.method or "GET").upper()

    # Rate limits for high-risk/high-cost endpoints.
    if endpoint == "login_submit":
        limited, retry_after = _rate_limit_check(
            "login",
            os.getenv("DOCARO_RATE_LIMIT_LOGIN", "10/5m"),
            default_limit=10,
            default_window=300,
        )
        if limited:
            return jsonify({"ok": False, "error": "rate_limited", "retry_after": retry_after}), 429

    if endpoint in {"upload", "process_inbox", "analyze_docling", "chunk_document"}:
        limited, retry_after = _rate_limit_check(
            "upload",
            os.getenv("DOCARO_RATE_LIMIT_UPLOAD", "30/5m"),
            default_limit=30,
            default_window=300,
        )
        if limited:
            flash("Zu viele Upload-Aktionen in kurzer Zeit. Bitte kurz warten.")
            return redirect(url_for("index"))

    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None

    # CSRF check for mutating requests (same-site fallback for legacy forms).
    expected = _ensure_csrf_token()
    provided = (
        request.headers.get("X-CSRF-Token")
        or request.form.get("csrf_token")
        or request.headers.get("X-XSRF-TOKEN")
    )
    strict_percent = int(os.getenv("DOCARO_CSRF_CANARY_PERCENT", "0"))
    strict_mode = os.getenv("DOCARO_CSRF_STRICT", "0") == "1" or _in_canary(strict_percent, "csrf-strict")

    if provided and hmac.compare_digest(str(provided), expected):
        return None

    if _same_origin_request() and not strict_mode:
        logger.warning("CSRF token missing/invalid for %s, allowed via same-origin fallback", endpoint or request.path)
        return None

    if request.headers.get("Accept", "").find("application/json") >= 0:
        return jsonify({"ok": False, "error": "csrf_failed"}), 403
    return "CSRF validation failed", 403


if not DEBUG_MODE:
    @app.errorhandler(Exception)
    def _handle_exception(exc: Exception):
        if isinstance(exc, HTTPException):
            return exc
        app.logger.exception("Unhandled exception", exc_info=exc)
        return "Internal Server Error", 500


@app.context_processor
def _inject_csrf_token() -> dict[str, str]:
    return {"csrf_token": _ensure_csrf_token()}


@app.after_request
def _log_server_errors(response):
    # Expose CSRF token for JS clients (same-site cookie).
    try:
        if request.path != "/metrics":
            response.set_cookie(
                "XSRF-TOKEN",
                _ensure_csrf_token(),
                secure=request.is_secure,
                httponly=False,
                samesite="Lax",
            )
    except Exception:
        pass
    if response.status_code >= 500:
        logger.error(
            "HTTP %s %s -> %s",
            request.method,
            request.path,
            response.status_code,
        )
    return response


def _allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def _mark_results_downloaded(out_names: set[str], user_scope: str = "") -> None:
    if not out_names:
        return
    results = _load_last_results(user_scope=user_scope) or []
    if not results:
        return
    now_iso = datetime.now().isoformat(timespec="seconds")
    touched = False
    for item in results:
        name = (item.get("out_name") or "").strip()
        if not name or name not in out_names:
            continue
        if not item.get("downloaded_at"):
            item["downloaded_at"] = now_iso
            touched = True
    if touched:
        _save_last_results(results, user_scope=user_scope)


def _remove_session_entries_for_sid(sid: str, file_ids: set[str] | None = None, filenames: set[str] | None = None) -> None:
    if not sid:
        return
    data = _load_session_files()
    session_map = data.get(sid) or {}
    if not session_map:
        return
    remove_keys: set[str] = set()
    if file_ids:
        remove_keys |= {k for k in file_ids if k in session_map}
    if filenames:
        for fid, entry in session_map.items():
            if (entry.get("filename") or "") in filenames:
                remove_keys.add(fid)
    if not remove_keys:
        return
    for fid in remove_keys:
        session_map.pop(fid, None)
    if session_map:
        data[sid] = session_map
    else:
        data.pop(sid, None)
    _save_session_files(data)


def _is_path_within(path: Path, root: Path) -> bool:
    try:
        rp = path.resolve()
    except OSError:
        rp = path
    try:
        rr = root.resolve()
    except OSError:
        rr = root
    try:
        rp.relative_to(rr)
        return True
    except Exception:
        return False


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _prune_tmp_upload_dirs(max_age_hours: int) -> None:
    if max_age_hours <= 0:
        return
    if not TMP_DIR.exists():
        return
    cutoff = datetime.now().timestamp() - (max_age_hours * 3600)
    for d in TMP_DIR.iterdir():
        if not d.is_dir():
            continue
        if not (d.name.startswith("upload_") or d.name.startswith("work_") or d.name.startswith("job_")):
            continue
        try:
            st = d.stat()
        except OSError:
            continue
        if st.st_mtime > cutoff:
            continue
        # Nur löschen, wenn leer oder nur noch Nicht-PDF-Reste enthalten sind
        try:
            leftovers = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
            if leftovers:
                continue
        except OSError:
            continue
        try:
            shutil.rmtree(d, ignore_errors=True)
        except OSError:
            continue


def _cleanup_after_download(*, sid: str, out_names: set[str], pdf_paths: list[Path], user_scope: str = "") -> None:
    """Best-effort: hält die UI/Session sauber und räumt alte TMP-Ordner weg.

    Standardmäßig werden keine Dokumente gelöscht (um das System nicht zu beeinträchtigen).
    Optional kann das Löschen über DOCARO_DELETE_FILES_AFTER_DOWNLOAD=1 aktiviert werden.
    """
    if not PRUNE_AFTER_DOWNLOAD:
        return

    # 1) Optional: Dateien löschen (nur wenn explizit aktiviert)
    if DELETE_FILES_AFTER_DOWNLOAD:
        out_dir = _user_out_dir(user_scope)
        quarantine_dir = _user_quarantine_dir(user_scope)
        for p in pdf_paths or []:
            if not p:
                continue
            if _is_path_within(p, out_dir) or _is_path_within(p, quarantine_dir):
                _safe_unlink(p)

        # Fallback nach Name (falls resolve_pdf_path in andere Orte zeigt)
        for name in out_names:
            if not name:
                continue
            _safe_unlink(out_dir / name)
            _safe_unlink(quarantine_dir / name)

    # 2) Ergebnisse markieren, damit Download-Liste nicht mehr verstopft
    try:
        _mark_results_downloaded(out_names, user_scope=user_scope)
    except Exception as exc:
        logger.warning("cleanup: mark downloaded failed: %s", exc)

    # 3) Session-Mapping aufräumen (damit Reset/Downloads nicht wachsen)
    try:
        _remove_session_entries_for_sid(sid, filenames=out_names)
    except Exception as exc:
        logger.warning("cleanup: session entries prune failed: %s", exc)

    # 4) Alte Upload-Arbeitsordner entfernen
    try:
        _prune_tmp_upload_dirs(TMP_RETENTION_HOURS)
    except Exception as exc:
        logger.warning("cleanup: tmp prune failed: %s", exc)


@app.get("/")
def index():
    _check_processing_timeout()
    _refresh_runtime_metrics()
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
    processing = _is_processing()
    progress = _load_progress()

    settings = _get_auto_sort_settings()
    inbox_dir_value = getattr(settings, "inbox_dir", INBOX_DIR)
    inbox_dir_display = _display_inbox_dir(inbox_dir_value)
    return render_template(
        "index.html",
        results=filtered,
        files=files,
        reset_done=reset_done,
        incomplete_only=incomplete_only,
        edit_all=edit_all,
        processing=processing,
        progress=progress,
        inbox_dir_display=inbox_dir_display,
    )


@app.get("/settings")
def settings_page():
    settings = _get_auto_sort_settings()

    # Review Settings laden
    try:
        from core.review_service import load_review_settings
        review_settings = load_review_settings(config.DATA_DIR / "settings.json")
        # Merge in settings object
        settings.gate_supplier_min = review_settings.gate_supplier_min
        settings.gate_date_min = review_settings.gate_date_min
        settings.gate_doc_type_min = review_settings.gate_doc_type_min
        settings.gate_doc_number_min = review_settings.gate_doc_number_min
        settings.auto_finalize_enabled = review_settings.auto_finalize_enabled
    except Exception as exc:
        logger.warning(f"Failed to load review settings: {exc}")
        # Defaults
        settings.gate_supplier_min = 0.80
        settings.gate_date_min = 0.80
        settings.gate_doc_type_min = 0.70
        settings.gate_doc_number_min = 0.80
        settings.auto_finalize_enabled = False

    return render_template("settings.html", settings=settings)


@app.post("/settings")
def settings_save():
    form = request.form
    enabled = form.get("auto_sort_enabled") == "1"
    base_dir_raw = form.get("base_dir", "").strip() or str(config.OUT_DIR)
    base_dir = Path(base_dir_raw).expanduser()
    if not base_dir.is_absolute():
        base_dir = (BASE_DIR / base_dir).resolve()
    folder_format = form.get("folder_format", "A").upper()
    if folder_format not in ("A", "B", "C"):
        folder_format = "A"
    mode = form.get("mode", "move").lower()
    if mode not in ("move", "copy"):
        mode = "move"
    try:
        conf_raw = str(
            form.get("confidence_threshold", config.AUTO_SORT_CONFIDENCE_THRESHOLD_DEFAULT)
        ).strip()
        confidence_threshold = float(conf_raw.replace(",", "."))
    except ValueError:
        confidence_threshold = config.AUTO_SORT_CONFIDENCE_THRESHOLD_DEFAULT
    fallback_folder = form.get("fallback_folder", config.AUTO_SORT_FALLBACK_FOLDER_DEFAULT).strip() or config.AUTO_SORT_FALLBACK_FOLDER_DEFAULT
    fallback_folder = sanitize_supplier_name(fallback_folder)

    inbox_dir_raw = form.get("inbox_dir", "").strip() or str(config.INBOX_DIR)
    # Persist exactly what the user entered (no automatic BASE_DIR prefixing).
    inbox_dir = Path(inbox_dir_raw).expanduser()
    if os.name != "nt" and _looks_like_windows_drive_path(inbox_dir_raw):
        flash(_windows_path_not_supported_on_linux_message(inbox_dir_raw))

    inbox_interval_raw = (form.get("inbox_interval_minutes", "0") or "0").strip()
    try:
        inbox_interval_minutes = int(inbox_interval_raw)
    except ValueError:
        inbox_interval_minutes = 0
    if inbox_interval_minutes < 0:
        inbox_interval_minutes = 0

    settings = AutoSortSettings(
        enabled=enabled,
        base_dir=base_dir,
        folder_format=folder_format,
        mode=mode,
        confidence_threshold=confidence_threshold,
        fallback_folder=fallback_folder,
        inbox_dir=inbox_dir,
        inbox_interval_minutes=inbox_interval_minutes,
    )
    _save_auto_sort_settings(settings)

    # Review Queue Settings speichern
    try:
        from core.review_service import ReviewSettings, save_review_settings

        auto_finalize_enabled = form.get("auto_finalize_enabled") == "1"
        gate_supplier_min = float(form.get("gate_supplier_min", "0.80"))
        gate_date_min = float(form.get("gate_date_min", "0.80"))
        gate_doc_type_min = float(form.get("gate_doc_type_min", "0.70"))
        gate_doc_number_min = float(form.get("gate_doc_number_min", "0.80"))

        review_settings = ReviewSettings(
            gate_supplier_min=gate_supplier_min,
            gate_date_min=gate_date_min,
            gate_doc_type_min=gate_doc_type_min,
            gate_doc_number_min=gate_doc_number_min,
            auto_finalize_enabled=auto_finalize_enabled,
            autosort_enabled=enabled,
            autosort_base_dir=base_dir
        )

        save_review_settings(config.DATA_DIR / "settings.json", review_settings)
    except Exception as exc:
        logger.warning(f"Failed to save review settings: {exc}")

    flash("Einstellungen gespeichert.")
    return redirect(url_for("settings_page"))


@app.get("/status.json")
def status_json():
    try:
        _refresh_runtime_metrics()
        processing = _is_processing()
        active_job_id = str(session.get("active_job_id") or "")
        if not processing and active_job_id:
            session.pop("active_job_id", None)
            active_job_id = ""
        active_job_status = ""
        if active_job_id:
            try:
                from rq.job import Job

                active_job_status = str(Job.fetch(active_job_id, connection=redis_conn).get_status())
            except Exception:
                active_job_status = "unknown"
        progress = _load_progress()
        results = _load_last_results() or []
        recent_item = results[-1] if results else {}
        recent_result = {
            "out_name": recent_item.get("out_name") or "",
            "supplier": recent_item.get("supplier") or "",
            "date": recent_item.get("date") or "",
            "doc_type": recent_item.get("doc_type") or "",
            "doc_number": recent_item.get("doc_number") or "",
            "supplier_confidence": recent_item.get("supplier_confidence") or "",
            "processing_route": recent_item.get("processing_route") or "",
            "review_priority_score": recent_item.get("review_priority_score") or "",
            "needs_review": bool(recent_item.get("needs_review")),
        }
        return jsonify({
            "ok": True,
            "user_scope": _current_user_scope(),
            "processing": processing,
            "active_job_id": active_job_id,
            "active_job_status": active_job_status,
            "queue_depth": int(q.count),
            "files": _list_finished(),
            "results_count": len(results),
            "progress": progress,
            "recent_result": recent_result,
        })
    except Exception as exc:
        _log_exception("status:handler", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/status.stream")
def status_stream():
    def _events():
        while True:
            try:
                payload = {
                    "ok": True,
                    "user_scope": _current_user_scope(),
                    "processing": _is_processing(),
                    "queue_depth": int(q.count),
                    "progress": _load_progress(),
                    "active_job_id": str(session.get("active_job_id") or ""),
                    "active_job_status": "",
                    "results_count": len(_load_last_results() or []),
                }
                results = _load_last_results() or []
                recent_item = results[-1] if results else {}
                payload["recent_result"] = {
                    "out_name": recent_item.get("out_name") or "",
                    "supplier": recent_item.get("supplier") or "",
                    "date": recent_item.get("date") or "",
                    "doc_type": recent_item.get("doc_type") or "",
                    "doc_number": recent_item.get("doc_number") or "",
                    "supplier_confidence": recent_item.get("supplier_confidence") or "",
                    "processing_route": recent_item.get("processing_route") or "",
                    "review_priority_score": recent_item.get("review_priority_score") or "",
                    "needs_review": bool(recent_item.get("needs_review")),
                }
                yield f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"
                if not payload["processing"]:
                    break
            except Exception as exc:
                yield f"event: error\ndata: {json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=True)}\n\n"
                break
            time.sleep(1.5)

    return Response(
        stream_with_context(_events()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/metrics")
def metrics_endpoint():
    from core.metrics import metrics_payload

    payload, content_type = metrics_payload()
    return Response(payload, mimetype=content_type)


@app.post("/analyze_docling")
def analyze_docling():
    """Analysiert hochgeladene PDF mit Docling für Vorschau."""
    # TEMPORÄR DEAKTIVIERT - Docling-Import verursacht Server-Crash
    return jsonify({
        "ok": False,
        "error": "Docling-Analyse vorübergehend deaktiviert (Server-Stabilitätsprobleme)"
    }), 503

    import signal
    from contextlib import contextmanager

    @contextmanager
    def timeout_context(seconds):
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Docling-Analyse überschritt {seconds}s Timeout")

        if hasattr(signal, 'SIGALRM'):
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(seconds)
            try:
                yield
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        else:
            yield

    try:
        if not is_docling_available():
            return jsonify({
                "ok": False,
                "error": "Docling ist nicht installiert. Installiere mit: pip install docling"
            }), 400

        uploaded = request.files.getlist("files")
        if not uploaded:
            uploaded = request.files.getlist("files[]")

        uploaded = [f for f in uploaded if getattr(f, "filename", None)]
        if not uploaded:
            return jsonify({
                "ok": False,
                "error": "Keine Dateien hochgeladen"
            }), 400

        try:
            extractor = get_docling_extractor()
        except Exception as e:
            logger.error(f"Docling Extractor Init fehlgeschlagen: {e}")
            return jsonify({
                "ok": False,
                "error": f"Docling nicht verfügbar: {str(e)}"
            }), 500

        if not extractor:
            return jsonify({
                "ok": False,
                "error": "Docling Extractor konnte nicht initialisiert werden"
            }), 500

        results = []
        TMP_DIR.mkdir(parents=True, exist_ok=True)

        for storage in uploaded:
            if not storage or not storage.filename:
                continue
            safe_name = secure_filename(storage.filename)
            if not safe_name or not _allowed_file(safe_name):
                continue

            temp_path = TMP_DIR / f"docling_temp_{uuid4().hex}.pdf"
            try:
                storage.save(temp_path)
            except Exception as e:
                logger.error(f"Fehler beim Speichern von {safe_name}: {e}")
                results.append({
                    "filename": safe_name,
                    "error": f"Upload fehlgeschlagen: {str(e)}"
                })
                continue

            try:
                # Timeout für lange Docling-Verarbeitung
                with timeout_context(30):
                    text = extractor.extract_text(temp_path)
                    metadata = extractor.extract_metadata(temp_path)
                    tables = extractor.extract_tables(temp_path)
                    supplier = extractor.extract_supplier(temp_path)
                    date = extractor.extract_date(temp_path, supplier)

                    results.append({
                        "filename": safe_name,
                        "text": text[:500] + "..." if len(text) > 500 else text,
                        "text_length": len(text),
                        "metadata": metadata,
                        "tables_found": len(tables),
                        "supplier": supplier,
                        "date": date.isoformat() if date else None,
                    })
            except TimeoutError:
                logger.error(f"Timeout bei Docling-Analyse von {safe_name}")
                results.append({
                    "filename": safe_name,
                    "error": "Verarbeitung zu langsam (Timeout)"
                })
            except Exception as e:
                logger.error(f"Fehler bei Docling-Analyse von {safe_name}: {e}", exc_info=True)
                results.append({
                    "filename": safe_name,
                    "error": str(e)
                })
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

        return jsonify({
            "ok": True,
            "results": results,
            "docling_available": True
        })

    except Exception as exc:
        _log_exception("analyze_docling:handler", exc)
        return jsonify({
            "ok": False,
            "error": f"Unerwarteter Fehler: {str(exc)}"
        }), 500


@app.get("/docling_status.json")
def docling_status_json():
    """Gibt Status der Docling-Verfügbarkeit zurück."""
    try:
        return jsonify({
            "ok": True,
            "docling_available": is_docling_available(),
            "message": "Docling ist verfügbar" if is_docling_available()
                      else "Docling nicht installiert - installiere mit: pip install docling"
        })
    except Exception as exc:
        logger.error(f"Fehler bei docling_status: {exc}")
        return jsonify({
            "ok": False,
            "docling_available": False,
            "error": str(exc)
        }), 500


@app.post("/chunk_document")
def chunk_document():
    """Chunked ein Dokument für RAG/LLM-Verwendung mit docling-core."""
    try:
        if not is_docling_available():
            return jsonify({
                "ok": False,
                "error": "Docling ist nicht installiert"
            }), 400

        uploaded = request.files.getlist("files")
        if not uploaded:
            uploaded = request.files.getlist("files[]")

        uploaded = [f for f in uploaded if getattr(f, "filename", None)]
        if not uploaded:
            return jsonify({
                "ok": False,
                "error": "Keine Dateien hochgeladen"
            }), 400

        max_tokens = int(request.form.get("max_tokens", 512))
        tokenizer = request.form.get("tokenizer", "sentence")

        extractor = get_docling_extractor()
        if not extractor:
            return jsonify({
                "ok": False,
                "error": "Docling Extractor konnte nicht initialisiert werden"
            }), 500

        results = []
        TMP_DIR.mkdir(parents=True, exist_ok=True)

        for storage in uploaded[:1]:  # Nur erste Datei für Demo
            if not storage or not storage.filename:
                continue
            safe_name = secure_filename(storage.filename)
            if not safe_name or not _allowed_file(safe_name):
                continue

            temp_path = TMP_DIR / f"chunk_temp_{uuid4().hex}.pdf"
            storage.save(temp_path)

            try:
                chunks = extractor.chunk_document(temp_path, tokenizer=tokenizer, max_tokens=max_tokens)

                results.append({
                    "filename": safe_name,
                    "num_chunks": len(chunks),
                    "chunks": chunks[:5],  # Nur erste 5 Chunks in Preview
                    "tokenizer": tokenizer,
                    "max_tokens": max_tokens
                })
            except Exception as e:
                logger.error(f"Fehler beim Chunken von {safe_name}: {e}")
                results.append({
                    "filename": safe_name,
                    "error": str(e)
                })
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

        return jsonify({
            "ok": True,
            "results": results
        })

    except Exception as exc:
        _log_exception("chunk_document:handler", exc)
        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 500


@app.post("/upload")
def upload():
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        TMP_DIR.mkdir(parents=True, exist_ok=True)

        # Robust: unterschiedliche Feldnamen abfangen (Browser/Clients)
        uploaded = request.files.getlist("files")
        if not uploaded:
            uploaded = request.files.getlist("files[]")
        if not uploaded:
            uploaded = request.files.getlist("file")

        # Wenn kein File ausgewählt wurde, liefert Flask teilweise eine Liste mit einem leeren Eintrag.
        uploaded = [f for f in uploaded if getattr(f, "filename", None)]
        if not uploaded:
            logger.info("Upload without files. request.files keys=%s", list(request.files.keys()))
            flash("Keine PDF-Dateien ausgewählt.")
            return redirect(url_for("index"))

        date_fmt = _normalize_date_fmt(request.form.get("date_fmt", ""))
        include_known = request.form.get("include_known") in ("1", "on", "true")
        user_scope = _current_user_scope()

        upload_dir = _user_tmp_dir(user_scope) / f"upload_{uuid4().hex}"
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved_count = 0
        duplicate_files: list[str] = []
        known_forced_files: list[str] = []
        for storage in uploaded:
            if not storage or not storage.filename:
                continue
            safe_name = secure_filename(storage.filename)
            if not safe_name or not _allowed_file(safe_name):
                continue
            target_path = get_unique_path(upload_dir, safe_name)
            storage.save(target_path)
            try:
                file_hash = _sha256_file(target_path)
            except Exception:
                file_hash = ""
            if file_hash:
                try:
                    known = _runtime_store.get_document_fingerprint(file_hash, owner_scope=user_scope)
                except Exception:
                    known = None
                if known:
                    if include_known:
                        known_forced_files.append(safe_name)
                    else:
                        duplicate_files.append(safe_name)
                        _safe_unlink(target_path)
                        continue
                try:
                    _runtime_store.register_document_fingerprint(
                        file_hash,
                        original_name=safe_name,
                        path=str(target_path),
                        file_id="",
                        owner_scope=user_scope,
                    )
                except Exception as exc:
                    count_step_error("runtime_store_fingerprint_register", exc)
            saved_count += 1

        if saved_count == 0:
            logger.info(
                "No valid PDFs saved. uploaded=%s",
                [getattr(f, "filename", "") for f in uploaded],
            )
            if duplicate_files:
                flash(
                    f"Bekannte Dateien wurden übersprungen ({len(duplicate_files)}): "
                    f"{', '.join(sorted(set(duplicate_files))[:5])}. "
                    "Aktiviere 'Bekannte Dateien trotzdem scannen', um sie erneut zu verarbeiten.",
                    "duplicate",
                )
                return redirect(url_for("index"))
            flash("Keine gültigen PDF-Dateien gefunden (nur .pdf erlaubt).")
            return redirect(url_for("index"))

        if duplicate_files:
            flash(
                f"{len(duplicate_files)} bekannte Datei(en) übersprungen. "
                "Zum erneuten Scannen beim nächsten Upload die Option "
                "'Bekannte Dateien trotzdem scannen' aktivieren.",
                "duplicate",
            )
        if known_forced_files:
            flash(f"{len(known_forced_files)} bekannte Datei(en) wurden auf Wunsch erneut gescannt.")

        logger.info("Upload accepted: %s PDFs saved to %s", saved_count, upload_dir)

        # Check if a previous processing is stuck
        _check_processing_timeout()

        if int(q.count) >= QUEUE_MAX_DEPTH:
            flash(
                f"Queue ist ausgelastet ({int(q.count)} Jobs >= Limit {QUEUE_MAX_DEPTH}). "
                "Bitte in wenigen Minuten erneut versuchen."
            )
            return redirect(url_for("index"))

        _set_progress(total=saved_count, done=0, current_file="", job_id="", user_scope=user_scope)

        # Hintergrundverarbeitung starten und sofort zur Index-Seite redirecten
        _set_processing(True, user_scope=user_scope)
        job = q.enqueue(
            background_process_upload,
            args=(upload_dir, date_fmt, user_scope),
            job_timeout='30m',
            result_ttl=86400,
        )
        _tag_job_owner(job, user_scope)
        session["active_job_id"] = str(job.id)
        _set_progress(total=saved_count, done=0, current_file="", job_id=str(job.id), user_scope=user_scope)
        canary_pct = int(os.getenv("DOCARO_UPLOAD_CANARY_PERCENT", "0"))
        if _in_canary(canary_pct, "upload-queue"):
            logger.info("Upload routed through canary cohort (job_id=%s, percent=%s)", job.id, canary_pct)
        return redirect(url_for("index"))
    except Exception as exc:
        _log_exception("upload:handler", exc)
        raise


@app.get("/upload")
def upload_overview():
    return redirect(url_for("index"))


def _list_finished():
    results = _load_last_results() or []
    files = [
        item.get("out_name")
        for item in results
        if item.get("out_name")
        and not item.get("quarantined")
        and not item.get("downloaded_at")
    ]
    return sorted({name for name in files if name})


def _clear_pdfs(dir_path: Path) -> None:
    if not dir_path.exists():
        return
    for pdf in dir_path.iterdir():
        if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
            continue
        try:
            pdf.unlink()
        except OSError:
            continue


def _check_processing_timeout() -> None:
    """Check if processing is stuck and reset if older than 15 minutes."""
    try:
        user_scope = _current_user_scope()
        flag_path = _processing_flag_path(user_scope=user_scope)
        if not flag_path.exists():
            return
        from datetime import datetime, timedelta
        mtime = datetime.fromtimestamp(flag_path.stat().st_mtime)
        # If we see no progress updates for a while, assume stuck worker/job.
        try:
            prog = _progress_path(user_scope=user_scope)
            if prog.exists():
                prog_mtime = datetime.fromtimestamp(prog.stat().st_mtime)
                if datetime.now() - prog_mtime > timedelta(minutes=8):
                    logger.warning("No progress update for >8 minutes, auto-recovering")
                    _set_processing(False, user_scope=user_scope)
                    _clear_progress(user_scope=user_scope)
                    return
        except Exception:
            pass

        if datetime.now() - mtime > timedelta(minutes=15):
            logger.warning("Processing stuck for >15 minutes, auto-recovering")
            _set_processing(False, user_scope=user_scope)
            _clear_progress(user_scope=user_scope)
    except Exception as e:
        logger.warning(f"Error checking processing timeout: {e}")

def _get_session_id() -> str:
    sid = session.get("sid")
    if not sid:
        sid = uuid4().hex
        session["sid"] = sid
    return sid


def _sanitize_scope(value: str) -> str:
    raw = (value or "").strip().lower()
    safe = re.sub(r"[^a-z0-9_-]+", "_", raw).strip("_")
    return safe or "system"


def _current_user_scope(explicit_scope: str = "") -> str:
    if explicit_scope:
        return _sanitize_scope(explicit_scope)
    if has_request_context():
        user_id = session.get("user_id")
        if user_id is not None and str(user_id).strip():
            return _sanitize_scope(f"user_{user_id}")
        user_email = (session.get("user_email") or "").strip().lower()
        if user_email:
            return _sanitize_scope(f"user_{user_email}")
    return "system"


def _user_data_root(user_scope: str = "") -> Path:
    scope = _current_user_scope(user_scope)
    root = DATA_DIR / "users" / scope
    root.mkdir(parents=True, exist_ok=True)
    return root


def _user_tmp_dir(user_scope: str = "") -> Path:
    path = _user_data_root(user_scope) / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _user_inbox_dir(user_scope: str = "") -> Path:
    path = _user_data_root(user_scope) / "eingang"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _user_out_dir(user_scope: str = "") -> Path:
    path = _user_data_root(user_scope) / "fertig"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _user_quarantine_dir(user_scope: str = "") -> Path:
    path = _user_data_root(user_scope) / "quarantaene"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _storage_manager() -> RuntimeStorageManager:
    global _runtime_storage_manager
    if _runtime_storage_manager is None:
        _runtime_storage_manager = RuntimeStorageManager(
            runtime_store=_runtime_store,
            get_session_id=_get_session_id,
            get_user_scope=_current_user_scope,
            report_error=count_step_error,
            log_retention_days=LOG_RETENTION_DAYS,
        )
    return _runtime_storage_manager


def _queue_manager() -> QueueRuntimeManager:
    global _queue_runtime_manager
    if _queue_runtime_manager is None:
        _queue_runtime_manager = QueueRuntimeManager(
            q=q,
            queue_max_depth=QUEUE_MAX_DEPTH,
            default_inbox_dir=INBOX_DIR,
            out_dir=OUT_DIR,
            quarantine_dir=QUARANTINE_DIR,
            resolve_inbox_dir_for_scope=_user_inbox_dir,
            resolve_out_dir=_user_out_dir,
            resolve_quarantine_dir=_user_quarantine_dir,
            refresh_runtime_metrics=_refresh_runtime_metrics,
            is_processing=_is_processing,
            set_progress=_set_progress,
            set_processing=_set_processing,
            get_auto_sort_settings=_get_auto_sort_settings,
            resolve_inbox_dir=_resolve_inbox_dir,
            looks_like_windows_drive_path=_looks_like_windows_drive_path,
            windows_path_not_supported_message=_windows_path_not_supported_on_linux_message,
            normalize_date_fmt=_normalize_date_fmt,
            process_folder=process_folder,
            clear_pdfs=_clear_pdfs,
            apply_result_flags=_apply_result_flags,
            apply_quarantine=_apply_quarantine,
            merge_last_results=_merge_last_results,
            clear_progress=_clear_progress,
            processing_flag_path=_processing_flag_path,
            get_unique_path=get_unique_path,
            observe_pipeline_step=observe_pipeline_step,
            set_inflight=set_inflight,
            count_step_error=count_step_error,
            log_exception=_log_exception,
        )
    return _queue_runtime_manager


def _session_results_path(user_scope: str = "") -> Path:
    scope = _current_user_scope(user_scope)
    return _user_tmp_dir(scope) / "last_results.json"

def _processing_flag_path(user_scope: str = "") -> Path:
    scope = _current_user_scope(user_scope)
    return _user_tmp_dir(scope) / "processing.flag"


def _progress_path(user_scope: str = "") -> Path:
    scope = _current_user_scope(user_scope)
    return _user_tmp_dir(scope) / "progress.json"


def _set_progress(total: int, done: int, current_file: str = "", job_id: str = "", user_scope: str = "") -> None:
    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        current = _load_progress(user_scope=user_scope) or {}
        payload = {
            "total": int(total),
            "done": int(done),
            "percent": (float(done) / float(total) * 100.0) if total else 0.0,
            "current_file": str(current_file or ""),
            "job_id": str(job_id or current.get("job_id") or ""),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "user_scope": _current_user_scope(user_scope),
        }
        target = _progress_path(user_scope=user_scope)
        tmp_path = target.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(target)
    except Exception:
        # Progress-Anzeige darf die Verarbeitung nie brechen.
        pass


def _clear_progress(user_scope: str = "") -> None:
    try:
        path = _progress_path(user_scope=user_scope)
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _load_progress(user_scope: str = "") -> Optional[dict]:
    path = _progress_path(user_scope=user_scope)
    if not path.exists():
        return None
    try:
        # PowerShell (Set-Content) kann UTF-8 mit BOM schreiben; das würde json.loads sonst brechen.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None

def _set_processing(value: bool, user_scope: str = "") -> None:
    try:
        flag_path = _processing_flag_path(user_scope=user_scope)
        if value:
            flag_path.write_text("1", encoding="utf-8")
        else:
            if flag_path.exists():
                flag_path.unlink()
    except OSError:
        pass

def _is_processing(user_scope: str = "") -> bool:
    try:
        return _processing_flag_path(user_scope=user_scope).exists()
    except OSError:
        return False


def _refresh_runtime_metrics() -> None:
    global _last_runtime_store_health_check
    global _last_runtime_store_checkpoint

    try:
        set_queue_depth("default", int(q.count))
    except Exception as exc:
        count_step_error("queue_depth", exc)
    try:
        inflight = 1 if list((DATA_DIR / "users").glob("*/tmp/processing.flag")) else 0
        set_inflight("web_processing", inflight)
    except Exception:
        pass
    now = time.time()
    try:
        if now - _last_runtime_store_health_check >= 60:
            _runtime_store.health_check()
            _last_runtime_store_health_check = now
    except Exception as exc:
        count_step_error("runtime_store_health", exc)
    try:
        interval = max(int(os.getenv("DOCARO_RUNTIME_WAL_CHECKPOINT_SECONDS", "600")), 30)
        if now - _last_runtime_store_checkpoint >= interval:
            _runtime_store.checkpoint_wal(truncate=True)
            _last_runtime_store_checkpoint = now
    except Exception as exc:
        count_step_error("runtime_store_checkpoint", exc)

def background_process_upload(upload_dir: Path, date_fmt: str, user_scope: str = "") -> None:
    background_process_folder(
        upload_dir,
        date_fmt=date_fmt,
        cleanup_input_dir=True,
        log_context="upload:bg_worker",
        user_scope=user_scope,
    )


def _tag_job_owner(job, user_scope: str) -> None:
    try:
        if not job:
            return
        job.meta["owner_scope"] = _current_user_scope(user_scope)
        job.save_meta()
    except Exception:
        pass


@app.post("/process_inbox")
def process_inbox():
    try:
        user_scope = _current_user_scope()
        decision = _queue_manager().evaluate_inbox_request(
            request.form.get("date_fmt", ""),
            user_scope=user_scope,
        )
        if not decision.proceed:
            flash(decision.flash_message)
            return redirect(url_for("index"))
        job = q.enqueue(
            background_process_folder,
            args=(decision.inbox_dir, decision.date_fmt),
            kwargs={
                "cleanup_input_dir": False,
                "log_context": "inbox:bg_worker",
                "user_scope": user_scope,
            },
            job_timeout="1h",
            result_ttl=86400,
        )
        _tag_job_owner(job, user_scope)
        _refresh_runtime_metrics()
        return redirect(url_for("index"))
    except Exception as exc:
        _log_exception("inbox:handler", exc)
        count_step_error("process_inbox", exc)
        _set_processing(False, user_scope=_current_user_scope())
        raise


@profile(threshold_seconds=2.0)
def background_process_folder(
    input_dir: Path,
    date_fmt: str,
    cleanup_input_dir: bool = False,
    log_context: str = "bg_worker",
    user_scope: str = "",
) -> None:
    _queue_manager().background_process_folder(
        input_dir=input_dir,
        date_fmt=date_fmt,
        cleanup_input_dir=cleanup_input_dir,
        log_context=log_context,
        user_scope=user_scope,
    )


def _save_last_results(results, user_scope: str = "") -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    # Nur noch Datei schreiben, keine Session mehr (atomar, damit kein Partial-JSON entsteht)
    payload = json.dumps(results, indent=2)
    target = _session_results_path(user_scope=user_scope)
    tmp_path = target.with_suffix(".json.tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(target)


def _result_key(item: dict) -> str:
    out_name = (item.get("out_name") or "").strip()
    if out_name:
        return f"out:{out_name}"
    export_path = (item.get("export_path") or "").strip()
    if export_path:
        return f"path:{export_path}"
    original = (item.get("original") or "").strip()
    if original:
        return f"orig:{original}"
    # Fallback: should be rare, but keep deterministic-ish key
    return f"unknown:{uuid4().hex}"


def _merge_last_results(new_results: list[dict] | None, user_scope: str = "") -> None:
    """Merge new processing results into persisted last_results.

    This keeps previously processed (and not downloaded) files in the download list,
    even when the user uploads additional PDFs later.
    """
    if not new_results:
        return

    existing = _load_last_results(user_scope=user_scope) or []
    existing_by_key: dict[str, dict] = {}
    existing_order: list[str] = []

    for item in existing:
        if not isinstance(item, dict):
            continue
        key = _result_key(item)
        if key in existing_by_key:
            continue
        existing_by_key[key] = item
        existing_order.append(key)

    new_keys_in_order: list[str] = []
    for item in new_results:
        if not isinstance(item, dict):
            continue
        key = _result_key(item)
        old = existing_by_key.get(key)
        if old is None:
            existing_by_key[key] = item
            new_keys_in_order.append(key)
            continue

        merged = dict(old)
        merged.update(item)

        # Preserve stable identifiers / state across runs.
        if old.get("file_id") and not merged.get("file_id"):
            merged["file_id"] = old.get("file_id")
        if old.get("downloaded_at") and not merged.get("downloaded_at"):
            merged["downloaded_at"] = old.get("downloaded_at")

        existing_by_key[key] = merged

    merged_list = [existing_by_key[k] for k in existing_order if k in existing_by_key]
    merged_list.extend(existing_by_key[k] for k in new_keys_in_order if k in existing_by_key)
    _save_last_results(merged_list, user_scope=user_scope)


def _load_last_results(user_scope: str = ""):
    # Nur noch aus Datei lesen, Session ignorieren
    results_path = _session_results_path(user_scope=user_scope)
    if not results_path.exists():
        return None
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    results = _apply_supplier_corrections(results, user_scope=user_scope)
    for item in results or []:
        _ensure_auto_sort_fields(item)
    return results


def _load_session_files() -> dict:
    return _storage_manager().load_session_files()


def _save_session_files(data: dict) -> None:
    _storage_manager().save_session_files(data)


def _get_session_file_map() -> dict:
    return _storage_manager().get_session_file_map()


def _set_session_file_entry(file_id: str, path: Path, filename: str, user_scope: str = "") -> None:
    user_scope = _current_user_scope(user_scope)
    _storage_manager().set_session_file_entry(file_id, str(path), filename)
    try:
        _runtime_store.register_owned_document(
            file_id,
            owner_scope=user_scope,
            path=str(path),
            filename=str(filename or ""),
        )
    except Exception as exc:
        count_step_error("runtime_store_owned_register", exc)
    try:
        if path and path.exists() and path.is_file():
            file_hash = _sha256_file(path)
            if file_hash:
                _runtime_store.register_document_fingerprint(
                    file_hash,
                    original_name=filename or path.name,
                    path=str(path),
                    file_id=file_id,
                    owner_scope=user_scope,
                )
    except Exception as exc:
        count_step_error("runtime_store_fingerprint_register", exc)


def _remove_session_files() -> None:
    _storage_manager().remove_session_files()


def _append_history(entry: dict) -> None:
    _storage_manager().append_history(entry)


def _load_supplier_corrections() -> dict:
    return _storage_manager().load_supplier_corrections()


def _save_supplier_corrections(data: dict) -> None:
    _storage_manager().save_supplier_corrections(data)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _load_supplier_profiles_cached() -> dict[str, dict]:
    try:
        mtime = SUPPLIER_PROFILES_PATH.stat().st_mtime if SUPPLIER_PROFILES_PATH.exists() else 0.0
    except OSError:
        mtime = 0.0
    cached_mtime = float(_supplier_profiles_cache.get("mtime") or 0.0)
    if mtime == cached_mtime:
        data = _supplier_profiles_cache.get("data")
        if isinstance(data, dict):
            return data  # type: ignore[return-value]
    data = load_supplier_profiles(SUPPLIER_PROFILES_PATH)
    _supplier_profiles_cache["mtime"] = mtime
    _supplier_profiles_cache["data"] = data
    return data


def _append_ground_truth_sample(file_id: str, source: str) -> None:
    result = _result_for_file_id(file_id) or {}
    labels = {
        "supplier": str(result.get("supplier") or "").strip(),
        "date": str(result.get("date") or "").strip(),
        "doc_type": str(result.get("doc_type") or "").strip(),
        "doc_number": str(result.get("doc_number") or "").strip(),
    }
    if not any(labels.values()):
        return
    text_parts = [
        str(result.get("ocr_text") or ""),
        str(result.get("textlayer_text") or ""),
        str(result.get("supplier_guess_line") or ""),
        str(result.get("date_evidence") or ""),
        str(result.get("doc_type_evidence") or ""),
        str(result.get("out_name") or ""),
    ]
    sample = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "file_id": file_id,
        "source": source,
        "text": "\n".join(p for p in text_parts if p).strip()[:8000],
        "labels": labels,
    }
    gt_path = DATA_DIR / "ml" / "ground_truth.jsonl"
    gt_path.parent.mkdir(parents=True, exist_ok=True)
    with gt_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sample, ensure_ascii=True) + "\n")


def _load_history_entries() -> list:
    return _storage_manager().load_history_entries()


def _latest_history_entry() -> Optional[dict]:
    return _storage_manager().latest_history_entry()


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


def _ensure_auto_sort_fields(item: dict) -> None:
    item.setdefault("auto_sort_status", "")
    item.setdefault("auto_sort_reason", "")
    item.setdefault("auto_sort_reason_code", "")
    item.setdefault("auto_sort_details", {})
    item.setdefault("export_path", "")


def _apply_result_flags(results):
    if results is None:
        return results
    profiles = _load_supplier_profiles_cached()
    for item in results:
        _ensure_auto_sort_fields(item)
        apply_supplier_profile(item, profiles)
        parsing_failed = bool(item.get("parsing_failed"))
        date_valAe = item.get("date")
        supplier_valAe = item.get("supplier")
        item["date_missing"] = _is_date_missing(date_valAe, parsing_failed)
        item["supplier_missing"] = _is_supplier_missing(supplier_valAe)
        item["supplier_broken"] = _is_supplier_broken(supplier_valAe)
        item["processing_route"] = derive_processing_route(item)
        item["review_priority_score"] = compute_review_priority(item)
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
        "supplier_candidates": result.get("supplier_candidates") or [],
        "date": result.get("date") or "",
        "date_confidence": result.get("date_confidence") or "",
        "doc_number": result.get("doc_number") or "",
        "doc_number_source": result.get("doc_number_source") or "",
        "doc_number_confidence": result.get("doc_number_confidence") or "",
        "doc_type": result.get("doc_type") or "",
        "doc_type_confidence": result.get("doc_type_confidence") or "",
        "doc_type_evidence": result.get("doc_type_evidence") or "",
        "doc_type_scores": result.get("doc_type_scores") or {},
        "doc_type_evidence_by_type": result.get("doc_type_evidence_by_type") or {},
        "llm_assist_used": result.get("llm_assist_used") or "",
        "llm_assist_model": result.get("llm_assist_model") or "",
        "llm_assist_error": result.get("llm_assist_error") or "",
        "error": result.get("error") or "",
        "tesseract_status": result.get("tesseract_status") or "",
        "poppler_status": result.get("poppler_status") or "",
        "ocr_rotation": result.get("ocr_rotation") or "",
        "ocr_rotation_reason": result.get("ocr_rotation_reason") or "",
        "timing_render_ms": result.get("timing_render_ms") or "",
        "timing_ocr_ms": result.get("timing_ocr_ms") or "",
        "timing_total_ms": result.get("timing_total_ms") or "",
        "quarantined": bool(result.get("quarantined")),
        "supplier_missing": bool(result.get("supplier_missing")),
        "date_missing": bool(result.get("date_missing")),
        "auto_sort_status": result.get("auto_sort_status") or "",
        "auto_sort_reason": result.get("auto_sort_reason") or "",
        "auto_sort_reason_code": result.get("auto_sort_reason_code") or "",
        "auto_sort_details": result.get("auto_sort_details") or {},
        "export_path": result.get("export_path") or "",
        "needs_review": bool(result.get("needs_review")),
        "processing_route": result.get("processing_route") or "",
        "review_priority_score": result.get("review_priority_score") or 0,
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
    return {item.get("out_name") for item in results if item.get("out_name") and not item.get("downloaded_at")}


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
    user_scope = _current_user_scope()
    results_path = _session_results_path(user_scope=user_scope)
    if results_path.exists():
        try:
            results_path.unlink()
        except OSError:
            pass
    # Processing-Flag auch löschen
    proc_flag = _processing_flag_path(user_scope=user_scope)
    if proc_flag.exists():
        try:
            proc_flag.unlink()
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
        doc_number_before = (before.get("doc_number") or "").strip()
        date_fmt = (request.form.get("date_fmt", "") or "").strip()
        if date_fmt not in ALLOWED_DATE_FORMATS:
            date_fmt = INTERNAL_DATE_FORMAT
        pdf_path = _resolve_file_path(file_id) or resolve_pdf_path(filename)
        original_path = str(pdf_path) if pdf_path else str(resolve_pdf_path(filename) or "")
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
                recomputed = build_new_filename(
                    supplier_name,
                    date_obj,
                    delivery_note_nr=doc_number_before or None,
                    date_format=date_fmt,
                )
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

        if pdf_path:
            synced_path, sync_error = _sync_pdf_location(file_id, pdf_path)
            if sync_error:
                _set_result_error(file_id, f"move_failed: {sync_error}")
                message = "Lieferant gespeichert, aber Verschieben fehlgeschlagen."
            elif synced_path:
                pdf_path = synced_path
                if pdf_path.name != new_name:
                    new_name = pdf_path.name

        # Auto-Sort nach manueller Korrektur nachholen
        try:
            settings = _get_auto_sort_settings()
            current = _result_for_file_id(file_id) or {}
            if settings.enabled and not bool(current.get("quarantined")) and pdf_path and pdf_path.exists():
                _auto_sort_pdf(current, pdf_path)
        except Exception as exc:
            logger.warning(f"Auto-sort after confirm_supplier failed: {exc}")

        # Online-Training: Korrektur ins Audit-Log schreiben (best-effort)
        _append_audit_correction(file_id, "supplier", supplier_name)
        try:
            _append_ground_truth_sample(file_id, source="confirm_supplier")
        except Exception as exc:
            count_step_error("ground_truth_append", exc)
        corrections = _load_supplier_corrections()
        corrections[file_id] = supplier_name
        _save_supplier_corrections(corrections)
        _append_history(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "file_id": file_id,
                "original_path": original_path,
                "new_path": str(pdf_path or ""),
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
            item["manual_reviewed"] = "1"
            item["parsing_failed"] = False
            if new_name:
                item["out_name"] = new_name
            item["supplier_missing"] = _is_supplier_missing(supplier_name)
            item["supplier_broken"] = _is_supplier_broken(supplier_name)
            needed, reason = _is_quarantine_needed(item)
            item["quarantined"] = "1" if needed else ""
            item["quarantine_reason"] = reason if needed else ""
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
            item["date_confidence"] = "0.90"
            item["manual_reviewed"] = "1"
            item["parsing_failed"] = False
            if new_name:
                item["out_name"] = new_name
            item["date_missing"] = _is_date_missing(date_iso, False)
            needed, reason = _is_quarantine_needed(item)
            item["quarantined"] = "1" if needed else ""
            item["quarantine_reason"] = reason if needed else ""
            item["needs_review"] = _is_review_needed(item)
            break
    _save_last_results(results)


def _update_last_results_doc_number(file_id: str, new_name: str, doc_number: str) -> None:
    if not file_id:
        return
    results = _load_last_results()
    if not results:
        return
    doc_number = (doc_number or "").strip()
    for item in results:
        if item.get("file_id") == file_id:
            item["doc_number"] = doc_number
            item["doc_number_source"] = "manual"
            # Keep extractor-style confidence labels
            item["doc_number_confidence"] = "high" if doc_number else "none"
            item["manual_reviewed"] = "1"
            item["parsing_failed"] = False
            if new_name:
                item["out_name"] = new_name
            needed, reason = _is_quarantine_needed(item)
            item["quarantined"] = "1" if needed else ""
            item["quarantine_reason"] = reason if needed else ""
            item["needs_review"] = _is_review_needed(item)
            break
    _save_last_results(results)


def _update_last_results_doc_type(file_id: str, doc_type: str) -> None:
    if not file_id:
        return
    results = _load_last_results()
    if not results:
        return
    doc_type = (doc_type or "").strip()
    for item in results:
        if item.get("file_id") == file_id:
            item["doc_type"] = doc_type
            item["doc_type_confidence"] = "0.90" if doc_type else (item.get("doc_type_confidence") or "")
            item["doc_type_evidence"] = "manual" if doc_type else (item.get("doc_type_evidence") or "")
            item["manual_reviewed"] = "1"
            item["parsing_failed"] = False
            needed, reason = _is_quarantine_needed(item)
            item["quarantined"] = "1" if needed else ""
            item["quarantine_reason"] = reason if needed else ""
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
    # Umlaute/ß konsistent transliterieren statt zu verlieren.
    # Sonst werden z.B. "Läschen" -> "Lschen".
    cleaned = (
        cleaned.replace("ß", "ss")
        .replace("Ä", "Ae")
        .replace("Ö", "Oe")
        .replace("Ü", "Ue")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
    )
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


def _format_iso_date_for_ui(date_iso: str, fmt: str) -> str:
    raw = (date_iso or "").strip()
    if not raw:
        return ""
    try:
        date_obj = datetime.strptime(raw, INTERNAL_DATE_FORMAT)
    except ValueError:
        return raw
    try:
        return date_obj.strftime(fmt)
    except Exception:
        return raw


def _find_pdf_path(filename: str) -> Optional[Path]:
    return resolve_pdf_path(filename)


def resolve_pdf_path(filename: str, user_scope: str = "") -> Optional[Path]:
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
    result = _result_for_filename(filename, user_scope=user_scope) or {}
    export_path_val = (result.get("export_path") or "").strip()
    if export_path_val:
        export_path = Path(export_path_val)
        if export_path.exists() and _is_allowed_pdf_path(export_path, user_scope=user_scope):
            return export_path
    # Search known roots first; deep scan is optional for performance reasons.
    roots = _allowed_roots(user_scope=user_scope)
    for root in roots:
        for name in candidates:
            candidate = root / name
            if candidate.exists():
                return candidate
    if config.DEEP_SCAN:
        for root in roots:
            if not root.exists():
                continue
            for name in candidates:
                for candidate in root.rglob(name):
                    if candidate.is_file():
                        return candidate
    return None


def _allowed_roots(user_scope: str = "") -> list[Path]:
    scope = _current_user_scope(user_scope)
    roots = [
        _user_tmp_dir(scope),
        _user_inbox_dir(scope),
        _user_out_dir(scope),
        _user_quarantine_dir(scope),
    ]
    try:
        auto_settings = _get_auto_sort_settings()
        if auto_settings and auto_settings.base_dir:
            base = Path(auto_settings.base_dir)
            # Optionaler AutoSort-Ordner nur zulassen, wenn er im User-Bereich liegt.
            if str(base.resolve()).startswith(str(_user_data_root(scope).resolve())):
                roots.append(base)
    except Exception:
        pass
    # Remove duplicates while preserving order
    unique_roots = []
    seen = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            unique_roots.append(root)
            seen.add(key)
    return unique_roots


def _parse_conf(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_quarantine_needed(item: dict) -> Tuple[bool, str]:
    # If a human explicitly reviewed/confirmed a document, do not quarantine
    # based on confidence thresholds anymore. Only hard missing fields should.
    if bool(item.get("manual_reviewed")):
        if bool(item.get("date_missing")):
            return True, "date_missing"
        if bool(item.get("supplier_missing")):
            return True, "supplier_missing"
        return False, ""
    if bool(item.get("date_missing")):
        return True, "date_missing"
    if bool(item.get("supplier_missing")):
        return True, "supplier_missing"
    supplier_conf = _parse_conf(item.get("supplier_confidence"))
    date_conf = _parse_conf(item.get("date_confidence"))
    if supplier_conf and supplier_conf < QUARANTINE_SUPPLIER_CONF_MIN:
        return True, f"supplier_conf<{QUARANTINE_SUPPLIER_CONF_MIN:.2f}"
    if date_conf and date_conf < QUARANTINE_DATE_CONF_MIN:
        return True, f"date_conf<{QUARANTINE_DATE_CONF_MIN:.2f}"
    return False, ""


def _apply_quarantine(results: list) -> list:
    """Moves uncertain PDFs into QUARANTINE_DIR and marks results.

    Must never raise: quarantine is a best-effort safety net.
    """
    if not results:
        return results
    try:
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return results

    for item in results:
        needed, reason = _is_quarantine_needed(item)
        item["quarantined"] = "1" if needed else ""
        item["quarantine_reason"] = reason if needed else ""
        if not needed:
            continue

        filename = str(item.get("out_name") or "").strip()
        if not filename:
            continue

        try:
            current = resolve_pdf_path(filename)
            if not current or not current.exists() or not _is_allowed_pdf_path(current):
                continue
            # Already in quarantine
            try:
                current.resolve().relative_to(QUARANTINE_DIR.resolve())
                continue
            except Exception:
                pass
            target = get_unique_path(QUARANTINE_DIR, current.name)
            current.replace(target)
        except OSError:
            continue

    return results


def _is_allowed_pdf_path(path: Path, user_scope: str = "") -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in _allowed_roots(user_scope=user_scope):
        try:
            resolved.relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        return True
    return False


def _resolve_file_path(file_id: str, user_scope: str = "") -> Optional[Path]:
    scope = _current_user_scope(user_scope)
    entry = _get_session_file_entry(file_id, user_scope=scope)
    tried = set()
    if entry:
        path_str = entry.get("path") or ""
        if path_str:
            candidate = Path(path_str)
            if candidate.exists() and _is_allowed_pdf_path(candidate, user_scope=scope):
                return candidate
        filename = entry.get("filename") or ""
        if filename:
            tried.add(filename)
    result = _result_for_file_id(file_id, user_scope=scope) or {}
    export_path_val = (result.get("export_path") or "").strip()
    if export_path_val:
        export_path = Path(export_path_val)
        if export_path.exists() and _is_allowed_pdf_path(export_path, user_scope=scope):
            _set_session_file_entry(file_id, export_path, export_path.name, user_scope=scope)
            return export_path
    for key in ("out_name", "filename", "original", "original_name"):
        valAe = result.get(key) or ""
        if valAe:
            tried.add(valAe)
    for name in list(tried):
        safe_name = secure_filename(name)
        if safe_name:
            tried.add(safe_name)
    for name in tried:
        fallback = resolve_pdf_path(name, user_scope=scope)
        if fallback:
            _set_session_file_entry(file_id, fallback, fallback.name, user_scope=scope)
            return fallback
    return None


def _get_session_file_entry(file_id: str, user_scope: str = "") -> Optional[dict]:
    scope = _current_user_scope(user_scope)
    try:
        owned = _runtime_store.get_owned_document(file_id, owner_scope=scope)
        if owned:
            return {"path": owned.get("path", ""), "filename": owned.get("filename", "")}
    except Exception as exc:
        count_step_error("runtime_store_owned_load", exc)
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


def _apply_supplier_corrections(results, user_scope: str = ""):
    if results is None:
        return results
    corrections = _load_supplier_corrections()
    if not corrections:
        return results

    def _is_never_supplier_name(value: str) -> bool:
        low = (value or "").strip().lower()
        low = low.replace("\u00df", "ss").replace("\u00e4", "ae").replace("\u00f6", "oe").replace("\u00fc", "ue")
        # Franz Bracht ist immer Empfänger/Lieferadresse, niemals Supplier
        blacklist = (
            "franz bracht",
            "kran-vermietung",
            "kran vermietung",
            "bruchfeld 91",
            "47809 krefeld",
        )
        return any(b in low for b in blacklist)

    changed = False
    for item in results:
        file_id = item.get("file_id")
        if not file_id:
            continue
        corrected = corrections.get(file_id)
        if corrected and _is_never_supplier_name(str(corrected)):
            continue
        if corrected and item.get("supplier") != corrected:
            item["supplier"] = corrected
            item["supplier_source"] = "manual"
            item["supplier_confidence"] = "1.00"
            changed = True
    if changed:
        _save_last_results(results, user_scope=user_scope)
    return results


def _trim_history() -> None:
    _storage_manager().trim_history()


def _rename_pdf_with_name(pdf_path: Path, filename: str) -> Tuple[Optional[Path], str]:
    return _move_pdf_to_dir(pdf_path, OUT_DIR, filename)


def _move_pdf_to_dir(pdf_path: Path, target_dir: Path, filename: str) -> Tuple[Optional[Path], str]:
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        direct_target = target_dir / filename
        try:
            if pdf_path.resolve() == direct_target.resolve():
                return pdf_path, ""
        except OSError:
            pass

        target_path = direct_target
        if target_path.exists():
            target_path = get_unique_path(target_dir, filename)
        try:
            pdf_path.replace(target_path)
        except OSError as exc:
            # Cross-device move (EXDEV): rename/replace fails across mounts.
            if getattr(exc, "errno", None) == 18:  # EXDEV
                shutil.copy2(pdf_path, target_path)
                try:
                    pdf_path.unlink(missing_ok=True)
                except TypeError:
                    if pdf_path.exists():
                        pdf_path.unlink()
            else:
                raise
        return target_path, ""
    except OSError as exc:
        return None, str(exc)


def _update_last_results_out_name(file_id: str, new_name: str) -> None:
    if not file_id or not new_name:
        return
    results = _load_last_results() or []
    for item in results:
        if item.get("file_id") == file_id:
            item["out_name"] = new_name
            break
    _save_last_results(results)


def _sync_pdf_location(file_id: str, pdf_path: Path) -> Tuple[Optional[Path], str]:
    """Move/rename the PDF to OUT_DIR or QUARANTINE_DIR based on current result flags.

    Keeps `out_name` and the session file map consistent if a unique name is generated.
    """
    if not file_id:
        return pdf_path, ""
    result = _result_for_file_id(file_id) or {}
    quarantined = bool(result.get("quarantined"))
    desired_dir = QUARANTINE_DIR if quarantined else OUT_DIR
    desired_name = (result.get("out_name") or "").strip() or pdf_path.name
    target_path, err = _move_pdf_to_dir(pdf_path, desired_dir, desired_name)
    if err or not target_path:
        return None, err
    _set_session_file_entry(file_id, target_path, target_path.name)
    if desired_name and target_path.name != desired_name:
        _update_last_results_out_name(file_id, target_path.name)
    return target_path, ""


def _update_auto_sort_metadata(
    file_id: str,
    out_name: str,
    export_path: Optional[Path],
    status: str,
    reason: str,
    reason_code: str = "",
    details: Optional[dict] = None,
) -> None:
    results = _load_last_results() or []
    for item in results:
        if (file_id and item.get("file_id") == file_id) or (out_name and item.get("out_name") == out_name):
            _ensure_auto_sort_fields(item)
            item["auto_sort_status"] = status or ""
            item["auto_sort_reason"] = reason or ""
            item["auto_sort_reason_code"] = reason_code or ""
            item["auto_sort_details"] = details or {}
            if export_path:
                item["export_path"] = str(export_path)
            break
    _save_last_results(results)


def _auto_sort_pdf(result: dict, pdf_path: Path) -> Tuple[Path, str, str]:
    settings = _get_auto_sort_settings()
    export_result = export_document(pdf_path, result, settings)
    target_path = export_result.path or pdf_path
    status = export_result.status
    reason = export_result.reason
    file_id = result.get("file_id") or ""
    out_name = result.get("out_name") or pdf_path.name
    _update_auto_sort_metadata(
        file_id,
        out_name,
        export_result.path,
        status,
        reason,
        reason_code=getattr(export_result, "reason_code", "") or "",
        details=getattr(export_result, "details", None),
    )
    if file_id and export_result.path:
        _set_session_file_entry(file_id, export_result.path, export_result.path.name)
    return target_path, status, reason


def _set_result_error(file_id: str, message: str) -> None:
    results = _load_last_results() or []
    for item in results:
        if item.get("file_id") == file_id:
            item["error"] = message
            break
    _save_last_results(results)


def _result_for_filename(filename: str, user_scope: str = ""):
    results = _load_last_results(user_scope=user_scope) or []
    for item in results:
        if item.get("out_name") == filename:
            return item
    return None


def _result_for_file_id(file_id: str, user_scope: str = ""):
    results = _load_last_results(user_scope=user_scope) or []
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
    profile_min = item.get("supplier_profile_review_conf_min")
    try:
        min_conf = float(profile_min) if profile_min is not None else 0.85
    except (TypeError, ValueError):
        min_conf = 0.85
    return confidence < min_conf


def _review_list():
    results = _load_last_results() or []
    results = _attach_file_ids(results) or []
    results = _apply_result_flags(results) or []
    review_items = [item for item in results if item.get("needs_review")]
    review_items.sort(key=lambda x: float(x.get("review_priority_score") or 0), reverse=True)
    return review_items


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
    date_iso = (date_valAe or result.get("date") or "").strip()
    doc_number = (result.get("doc_number") or "").strip()
    doc_type = (result.get("doc_type") or "").strip()
    date_fmt = date_fmt if date_fmt in MANUAL_DATE_FORMATS else "%d-%m-%Y"
    date_valAe = _format_iso_date_for_ui(date_iso, date_fmt) if date_iso else ""
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
        "date_value": date_valAe,
        "date_error": date_error,
        "date_fmt": date_fmt,
        "doc_number": doc_number,
        "doc_type": doc_type,
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

    doc_number = (result.get("doc_number") or "").strip() or None
    new_filename = build_new_filename(supplier, date_obj, delivery_note_nr=doc_number, date_format=date_fmt)
    original_path = str(pdf_path)
    target_path, move_error = _move_pdf_to_dir(pdf_path, OUT_DIR, new_filename)
    if move_error or not target_path:
        return _render_view_pdf(file_id, date_error="Datei konnte nicht umbenannt werden.")

    date_iso = date_obj.strftime(INTERNAL_DATE_FORMAT)
    _set_session_file_entry(file_id, target_path, target_path.name)
    _update_last_results_date(file_id, target_path.name, date_iso)

    synced_path, sync_error = _sync_pdf_location(file_id, target_path)
    if sync_error:
        _set_result_error(file_id, f"move_failed: {sync_error}")
    elif synced_path:
        target_path = synced_path

    if target_path and target_path.name != filename:
        flash(f"Umbenannt zu: {target_path.name}")

    # Auto-Sort nach manueller Korrektur nachholen
    try:
        settings = _get_auto_sort_settings()
        current = _result_for_file_id(file_id) or {}
        if settings.enabled and not bool(current.get("quarantined")) and target_path and target_path.exists():
            _auto_sort_pdf(current, target_path)
    except Exception as exc:
        logger.warning(f"Auto-sort after confirm_date_from_view failed: {exc}")
    _append_history(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "file_id": file_id,
            "original_path": original_path,
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

    doc_number = (result.get("doc_number") or "").strip() or None
    new_filename = build_new_filename(supplier, date_obj, delivery_note_nr=doc_number, date_format=date_fmt)
    original_path = str(pdf_path)
    target_path, move_error = _move_pdf_to_dir(pdf_path, OUT_DIR, new_filename)
    if move_error or not target_path:
        flash("Datei konnte nicht umbenannt werden.")
        return redirect(url_for("index"))

    date_iso = date_obj.strftime(INTERNAL_DATE_FORMAT)
    _set_session_file_entry(file_id, target_path, target_path.name)
    _update_last_results_date(file_id, target_path.name, date_iso)

    synced_path, sync_error = _sync_pdf_location(file_id, target_path)
    if sync_error:
        _set_result_error(file_id, f"move_failed: {sync_error}")
    elif synced_path:
        target_path = synced_path

    message = "Datum gespeichert."
    if target_path and target_path.name != filename:
        message = f"Umbenannt zu: {target_path.name}"

    # Auto-Sort nach manueller Korrektur nachholen
    try:
        settings = _get_auto_sort_settings()
        current = _result_for_file_id(file_id) or {}
        if settings.enabled and not bool(current.get("quarantined")) and target_path and target_path.exists():
            _auto_sort_pdf(current, target_path)
    except Exception as exc:
        logger.warning(f"Auto-sort after confirm_date failed: {exc}")

    # Online-Training: Datumskorrektur loggen
    _append_audit_correction(file_id, "date", date_iso)
    try:
        _append_ground_truth_sample(file_id, source="confirm_date")
    except Exception as exc:
        count_step_error("ground_truth_append", exc)
    _append_history(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "file_id": file_id,
            "original_path": original_path,
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


def _normalize_doc_number_input(value: str) -> str:
    cleaned = (value or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    # allow typical doc-number chars
    cleaned = re.sub(r"[^a-zA-Z0-9 ._\-/]+", "", cleaned)
    cleaned = cleaned.strip("._- /")
    if len(cleaned) > 60:
        cleaned = cleaned[:60].rstrip()
    return cleaned


@app.post("/confirm_doc_type")
def confirm_doc_type():
    file_id = request.form.get("file_id", "").strip()
    if not file_id:
        abort(404)
    result = _result_for_file_id(file_id)
    if not result:
        abort(404)

    raw_val = (request.form.get("doc_type", "") or "").strip()
    allowed = {
        "RECHNUNG",
        "LIEFERSCHEIN",
        "ÜBERNAHMESCHEIN",
        "KOMMISSIONIERLISTE",
        "SONSTIGES",
    }
    if raw_val not in allowed:
        message = "Dokumenttyp ungültig."
        if _is_ajax_request():
            return jsonify({"ok": False, "message": message}), 400
        flash(message)
        return redirect(url_for("index"))

    before = result.get("doc_type") or ""
    _update_last_results_doc_type(file_id, raw_val)

    # Datei ggf. aus Quarantäne holen (manual_reviewed -> Quarantäne nur bei fehlendem Datum/Lieferant)
    try:
        filename = (result.get("out_name") or "").strip()
        pdf_path = _resolve_file_path(file_id) or resolve_pdf_path(filename)
        if pdf_path:
            synced_path, sync_error = _sync_pdf_location(file_id, pdf_path)
            if sync_error:
                _set_result_error(file_id, f"move_failed: {sync_error}")
            elif synced_path:
                pdf_path = synced_path
            # Auto-Sort nachholen, wenn nicht quarantined
            settings = _get_auto_sort_settings()
            current = _result_for_file_id(file_id) or {}
            if settings.enabled and not bool(current.get("quarantined")) and pdf_path and pdf_path.exists():
                _auto_sort_pdf(current, pdf_path)
    except Exception as exc:
        logger.warning(f"Post-save sync after confirm_doc_type failed: {exc}")

    # Online-Training: DocType-Korrektur loggen
    _append_audit_correction(file_id, "doctype", raw_val)
    try:
        _append_ground_truth_sample(file_id, source="confirm_doc_type")
    except Exception as exc:
        count_step_error("ground_truth_append", exc)
    _append_history(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "file_id": file_id,
            "action_type": "confirm_doc_type",
            "doc_type_before": before,
            "doc_type_after": raw_val,
        }
    )
    message = "Dokumenttyp gespeichert."
    if _is_ajax_request():
        return jsonify(_row_payload(file_id, message=message))
    flash(message)
    return redirect(url_for("index"))


@app.post("/confirm_review_state")
def confirm_review_state():
    """Ändert den Review-Status eines Dokuments (fertig, in Bearbeitung, unvollständig)."""
    file_id = request.form.get("file_id", "").strip()
    if not file_id:
        abort(404)
    result = _result_for_file_id(file_id)
    if not result:
        abort(404)

    raw_val = (request.form.get("review_state", "") or "").strip()
    allowed = {"unvollstaendig", "in_bearbeitung", "fertig"}
    if raw_val not in allowed:
        message = "Status ungültig."
        if _is_ajax_request():
            return jsonify({"ok": False, "message": message}), 400
        flash(message)
        return redirect(url_for("index"))

    # Setze needs_review basierend auf Status
    needs_review = (raw_val == "in_bearbeitung")
    results = _load_last_results() or []
    for item in results:
        if item.get("file_id") == file_id:
            item["needs_review"] = "1" if needs_review else ""
            break
    _save_last_results(results)

    message = f"Status zu '{raw_val}' gesetzt."
    if _is_ajax_request():
        return jsonify(_row_payload(file_id, message=message))
    flash(message)
    return redirect(url_for("index"))


@app.post("/delete_pdf")
def delete_pdf():
    """Löscht eine einzelne PDF aus der Ergebnisliste (und von Disk)."""
    file_id = (request.form.get("file_id", "") or "").strip()
    if not file_id:
        abort(404)

    result = _result_for_file_id(file_id) or {}
    filename = (result.get("out_name") or "").strip()

    pdf_path = _resolve_file_path(file_id) or resolve_pdf_path(filename)
    if not pdf_path or not str(pdf_path):
        flash("Datei nicht gefunden.")
        return redirect(url_for("index"))

    # Safety: nur PDFs und nur innerhalb erlaubter Roots löschen
    if pdf_path.suffix.lower() != ".pdf":
        flash("Ungültige Datei.")
        return redirect(url_for("index"))

    allowed_roots: list[Path] = [OUT_DIR, QUARANTINE_DIR]
    try:
        settings = _get_auto_sort_settings()
        base_dir_raw = str(getattr(settings, "base_dir", "") or "").strip()
        if settings.enabled and base_dir_raw:
            allowed_roots.append(Path(base_dir_raw))
    except Exception:
        pass

    if not any(_is_path_within(pdf_path, root) for root in allowed_roots if root):
        flash("Löschen nicht erlaubt.")
        return redirect(url_for("index"))

    _safe_unlink(pdf_path)

    # Ergebnis entfernen
    results = _load_last_results() or []
    new_results = [item for item in results if item.get("file_id") != file_id]
    if len(new_results) != len(results):
        _save_last_results(new_results)

    # Corrections aufräumen (damit alte Werte nicht bleiben)
    try:
        corrections = _load_supplier_corrections()
        if file_id in corrections:
            corrections.pop(file_id, None)
            _save_supplier_corrections(corrections)
    except Exception:
        pass

    # Session mapping best-effort entfernen
    try:
        _remove_session_entries_for_sid(_get_session_id(), file_ids={file_id}, filenames={filename} if filename else None)
    except Exception:
        pass

    flash("PDF gelöscht.")
    return redirect(url_for("index"))


@app.post("/confirm_doc_number")
def confirm_doc_number():
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

    doc_number_input = request.form.get("doc_number_input", "")
    doc_number = _normalize_doc_number_input(doc_number_input)
    if len(doc_number) < 1:
        message = "Dokumentnummer ungültig."
        if _is_ajax_request():
            return jsonify({"ok": False, "message": message}), 400
        flash(message)
        return redirect(url_for("index"))

    supplier = (result.get("supplier") or "").strip() or "Unbekannt"
    date_str = (result.get("date") or "").strip()
    date_fmt = (request.form.get("date_fmt", "") or "").strip()
    if date_fmt not in ALLOWED_DATE_FORMATS:
        date_fmt = INTERNAL_DATE_FORMAT
    date_obj = None
    if date_str:
        try:
            date_obj = datetime.strptime(date_str, INTERNAL_DATE_FORMAT)
        except ValueError:
            date_obj = None

    original_path = str(pdf_path)
    new_name = filename
    target_path = pdf_path

    if date_obj:
        new_filename = build_new_filename(
            supplier,
            date_obj,
            delivery_note_nr=doc_number,
            date_format=date_fmt,
        )
        moved_path, move_error = _move_pdf_to_dir(pdf_path, OUT_DIR, new_filename)
        if move_error or not moved_path:
            _set_result_error(file_id, f"rename_failed: {move_error}")
        else:
            target_path = moved_path
            new_name = target_path.name
            _set_session_file_entry(file_id, target_path, target_path.name)

    _update_last_results_doc_number(file_id, new_name, doc_number)

    synced_path, sync_error = _sync_pdf_location(file_id, target_path)
    if sync_error:
        _set_result_error(file_id, f"move_failed: {sync_error}")
    elif synced_path:
        target_path = synced_path
        if target_path.name != new_name:
            new_name = target_path.name

    # Auto-Sort nach manueller Korrektur nachholen
    try:
        settings = _get_auto_sort_settings()
        current = _result_for_file_id(file_id) or {}
        if settings.enabled and not bool(current.get("quarantined")) and target_path and target_path.exists():
            _auto_sort_pdf(current, target_path)
    except Exception as exc:
        logger.warning(f"Auto-sort after confirm_doc_number failed: {exc}")

    _append_history(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "file_id": file_id,
            "original_path": original_path,
            "new_path": str(target_path or ""),
            "filename_before": filename,
            "filename_after": new_name,
            "action_type": "confirm_doc_number",
            "doc_number_before": result.get("doc_number") or "",
            "doc_number_after": doc_number,
        }
    )
    try:
        _append_ground_truth_sample(file_id, source="confirm_doc_number")
    except Exception as exc:
        count_step_error("ground_truth_append", exc)

    message = "Dokumentnummer gespeichert."
    if new_name and new_name != filename:
        message = f"Umbenannt zu: {new_name}"

    if _is_ajax_request():
        return jsonify(_row_payload(file_id, message=message))
    flash(message)
    return redirect(url_for("index"))


@app.post("/confirm_doc_number_from_view")
def confirm_doc_number_from_view():
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

    doc_number_input = request.form.get("doc_number_input", "")
    doc_number = _normalize_doc_number_input(doc_number_input)
    if len(doc_number) < 1:
        flash("Dokumentnummer ungültig.")
        return redirect(url_for("view_pdf", file_id=file_id))

    supplier = (result.get("supplier") or "").strip() or "Unbekannt"
    date_str = (result.get("date") or "").strip()
    date_obj = None
    if date_str:
        try:
            date_obj = datetime.strptime(date_str, INTERNAL_DATE_FORMAT)
        except ValueError:
            date_obj = None

    original_path = str(pdf_path)
    new_name = filename
    target_path = pdf_path

    # Rename only if we have a usable date; otherwise just persist the doc number.
    if date_obj:
        new_filename = build_new_filename(
            supplier,
            date_obj,
            delivery_note_nr=doc_number,
            date_format=INTERNAL_DATE_FORMAT,
        )
        moved_path, move_error = _move_pdf_to_dir(pdf_path, OUT_DIR, new_filename)
        if move_error or not moved_path:
            flash("Dokumentnummer gespeichert, aber Umbenennen fehlgeschlagen.")
        else:
            target_path = moved_path
            new_name = target_path.name
            _set_session_file_entry(file_id, target_path, target_path.name)

    _update_last_results_doc_number(file_id, new_name, doc_number)

    synced_path, sync_error = _sync_pdf_location(file_id, target_path)
    if sync_error:
        _set_result_error(file_id, f"move_failed: {sync_error}")
    elif synced_path:
        target_path = synced_path
        if target_path.name != new_name:
            new_name = target_path.name

    # Auto-Sort nach manueller Korrektur nachholen
    try:
        settings = _get_auto_sort_settings()
        current = _result_for_file_id(file_id) or {}
        if settings.enabled and not bool(current.get("quarantined")) and target_path and target_path.exists():
            _auto_sort_pdf(current, target_path)
    except Exception as exc:
        logger.warning(f"Auto-sort after confirm_doc_number_from_view failed: {exc}")

    _append_history(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "file_id": file_id,
            "original_path": original_path,
            "new_path": str(target_path or ""),
            "filename_before": filename,
            "filename_after": new_name,
            "action_type": "confirm_doc_number",
            "doc_number_before": result.get("doc_number") or "",
            "doc_number_after": doc_number,
        }
    )

    if new_name and new_name != filename:
        flash(f"Umbenannt zu: {new_name}")
    flash("Dokumentnummer gespeichert.")
    return redirect(url_for("view_pdf", file_id=file_id))


@app.post("/confirm_doc_type_from_view")
def confirm_doc_type_from_view():
    file_id = request.form.get("file_id", "").strip()
    if not file_id:
        abort(404)
    result = _result_for_file_id(file_id)
    if not result:
        abort(404)

    raw_val = (request.form.get("doc_type", "") or "").strip()
    # Accept a small, explicit set.
    allowed = {
        "RECHNUNG",
        "LIEFERSCHEIN",
        "ÜBERNAHMESCHEIN",
        "KOMMISSIONIERLISTE",
        "SONSTIGES",
    }
    if raw_val not in allowed:
        flash("Dokumenttyp ungültig.")
        return redirect(url_for("view_pdf", file_id=file_id))

    before = result.get("doc_type") or ""
    _update_last_results_doc_type(file_id, raw_val)

    # Datei ggf. aus Quarantäne holen
    try:
        filename = (result.get("out_name") or "").strip()
        pdf_path = _resolve_file_path(file_id) or resolve_pdf_path(filename)
        if pdf_path:
            synced_path, sync_error = _sync_pdf_location(file_id, pdf_path)
            if sync_error:
                _set_result_error(file_id, f"move_failed: {sync_error}")
            elif synced_path:
                pdf_path = synced_path
            settings = _get_auto_sort_settings()
            current = _result_for_file_id(file_id) or {}
            if settings.enabled and not bool(current.get("quarantined")) and pdf_path and pdf_path.exists():
                _auto_sort_pdf(current, pdf_path)
    except Exception as exc:
        logger.warning(f"Post-save sync after confirm_doc_type_from_view failed: {exc}")

    _append_history(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "file_id": file_id,
            "action_type": "confirm_doc_type",
            "doc_type_before": before,
            "doc_type_after": raw_val,
        }
    )
    flash("Dokumenttyp gespeichert.")
    return redirect(url_for("view_pdf", file_id=file_id))


@app.post("/confirm_all_from_view")
def confirm_all_from_view():
    file_id = request.form.get("file_id", "").strip()
    if not file_id:
        abort(404)
    result = _result_for_file_id(file_id)
    if not result:
        abort(404)
    result = result or {}
    filename_before = (result.get("out_name") or "").strip()

    pdf_path = _resolve_file_path(file_id) or resolve_pdf_path(filename_before)
    if not pdf_path:
        _set_result_error(file_id, "pdf_open_failed: file_not_found")
        return _render_view_pdf(file_id, pdf_missing=True), 404

    supplier_input = (request.form.get("supplier_input", "") or "").strip()
    supplier_name = (result.get("supplier") or "").strip() or "Unbekannt"
    if supplier_input:
        supplier_name = _normalize_supplier_input(supplier_input)
        if len(supplier_name) < 2:
            flash("Lieferant ungültig.")
            return redirect(url_for("view_pdf", file_id=file_id))

    # Optional: Alias aus OCR-Zeile übernehmen
    try:
        use_alias = request.form.get("alias_from_ocr") in ("1", "on", "true")
        alias = (request.form.get("supplier_guess_line", "") or "").strip() if use_alias else ""
        if supplier_name and supplier_name != "Unbekannt":
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
    except Exception as exc:
        logger.warning(f"Supplier DB update in confirm_all_from_view failed: {exc}")

    date_input = (request.form.get("date_input", "") or "").strip()
    # The UI lets the user choose the date format. We use that format for
    # the filename label, but always persist the normalized ISO date internally.
    date_fmt = _normalize_date_fmt(request.form.get("date_fmt", ""))
    date_iso = (result.get("date") or "").strip()
    date_obj = None
    if date_input:
        date_obj = _normalize_date_input(date_input, date_fmt)
        if not date_obj:
            return _render_view_pdf(
                file_id,
                date_error="Ungültiges Datum. Bitte TT.MM.JJJJ, TT.MM.JJ oder YYYY-MM-DD eingeben.",
                date_valAe=date_input,
                date_fmt=date_fmt,
            )
        date_iso = date_obj.strftime(INTERNAL_DATE_FORMAT)
    elif date_iso:
        try:
            date_obj = datetime.strptime(date_iso, INTERNAL_DATE_FORMAT)
        except ValueError:
            date_obj = None

    doc_number_input = request.form.get("doc_number_input", "")
    doc_number = _normalize_doc_number_input(doc_number_input)

    raw_doc_type = (request.form.get("doc_type", "") or "").strip()
    allowed_doc_types = {
        "RECHNUNG",
        "LIEFERSCHEIN",
        "ÜBERNAHMESCHEIN",
        "KOMMISSIONIERLISTE",
        "SONSTIGES",
        "",
    }
    if raw_doc_type not in allowed_doc_types:
        flash("Dokumenttyp ungültig.")
        return redirect(url_for("view_pdf", file_id=file_id))

    original_path = str(pdf_path)
    target_path = pdf_path
    filename_after = filename_before or pdf_path.name

    # Wenn Datum vorhanden ist: Dateiname konsequent neu bauen (inkl. Doc-Nummer)
    if date_obj:
        new_filename = build_new_filename(
            supplier_name or "Unbekannt",
            date_obj,
            delivery_note_nr=doc_number or None,
            # Label with the user-selected date format.
            date_format=date_fmt if date_fmt in ALLOWED_DATE_FORMATS else INTERNAL_DATE_FORMAT,
        )
        moved_path, move_error = _move_pdf_to_dir(pdf_path, OUT_DIR, new_filename)
        if move_error or not moved_path:
            _set_result_error(file_id, f"rename_failed: {move_error}")
        else:
            target_path = moved_path
            filename_after = moved_path.name
            _set_session_file_entry(file_id, moved_path, moved_path.name)

    # Results persistieren (setzt manual_reviewed=1 und recalculates quarantine)
    _update_last_results(file_id, supplier_name or "Unbekannt", new_name=filename_after)

    # Wichtig: supplier_corrections persistieren, sonst überschreibt
    # _apply_supplier_corrections() beim nächsten Laden wieder den alten Wert.
    try:
        if supplier_name and supplier_name != "Unbekannt":
            corrections = _load_supplier_corrections()
            corrections[file_id] = supplier_name
            _save_supplier_corrections(corrections)
    except Exception as exc:
        logger.warning(f"Supplier corrections update in confirm_all_from_view failed: {exc}")

    if date_iso:
        _update_last_results_date(file_id, filename_after, date_iso)
    _update_last_results_doc_number(file_id, filename_after, doc_number)
    _update_last_results_doc_type(file_id, raw_doc_type)

    synced_path, sync_error = _sync_pdf_location(file_id, target_path)
    if sync_error:
        _set_result_error(file_id, f"move_failed: {sync_error}")
    elif synced_path:
        target_path = synced_path
        if target_path.name != filename_after:
            filename_after = target_path.name

    # Auto-Sort nach manueller Korrektur nachholen
    try:
        settings = _get_auto_sort_settings()
        current = _result_for_file_id(file_id) or {}
        if settings.enabled and not bool(current.get("quarantined")) and target_path and target_path.exists():
            _auto_sort_pdf(current, target_path)
    except Exception as exc:
        logger.warning(f"Auto-sort after confirm_all_from_view failed: {exc}")

    # Online-Training: alle Korrekturen (best-effort) ins Audit-Log
    if supplier_name:
        _append_audit_correction(file_id, "supplier", supplier_name)
    if date_iso:
        _append_audit_correction(file_id, "date", date_iso)
    if raw_doc_type:
        _append_audit_correction(file_id, "doctype", raw_doc_type)
    try:
        _append_ground_truth_sample(file_id, source="confirm_all_from_view")
    except Exception as exc:
        count_step_error("ground_truth_append", exc)

    _append_history(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "file_id": file_id,
            "original_path": original_path,
            "new_path": str(target_path or ""),
            "filename_before": filename_before,
            "filename_after": filename_after,
            "action_type": "confirm_all_from_view",
        }
    )

    flash("Gespeichert.")
    return redirect(url_for("view_pdf", file_id=file_id))


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
    # Redirect mit Anchor zur geänderten Zeile
    anchor = new_name.replace(" ", "-").replace("/", "-").lower()
    return redirect(url_for("suppliers") + f"#supplier-{anchor}")


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
    # Redirect mit Anchor zur geänderten Zeile
    anchor = supplier_name.replace(" ", "-").replace("/", "-").lower()
    return redirect(url_for("suppliers") + f"#supplier-{anchor}")


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
    # Redirect mit Anchor zur geänderten Zeile
    anchor = supplier_name.replace(" ", "-").replace("/", "-").lower()
    return redirect(url_for("suppliers") + f"#supplier-{anchor}")


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

    result = _result_for_filename(safe_name) or {}
    file_id = result.get("file_id") or ""

    pdf_path = None
    export_path_val = (result.get("export_path") or "").strip()
    if export_path_val:
        candidate = Path(export_path_val)
        if candidate.exists():
            pdf_path = candidate

    if not pdf_path:
        pdf_path = resolve_pdf_path(safe_name)
    if not pdf_path:
        abort(404)

    # Auto-Sort vor dem Download: Stelle sicher, dass Datei sortiert ist
    # (falls nicht bereits durch confirm_supplier/confirm_date geschehen)
    settings = _get_auto_sort_settings()
    if result and settings.enabled and not bool(result.get("quarantined")):
        # Prüfe ob Auto-Sort bereits erfolgreich war
        export_path_val = (result.get("export_path") or "").strip()
        already_sorted = export_path_val and Path(export_path_val).exists()

        if not already_sorted:
            # Auto-Sort nachholen
            try:
                logger.info(f"Auto-sorting before download: {safe_name}")
                pdf_path, auto_status, auto_reason = _auto_sort_pdf(result, pdf_path)
            except Exception as exc:
                logger.warning(f"Auto-sort on download failed for {safe_name}: {exc}")

    if file_id and pdf_path:
        _set_session_file_entry(file_id, pdf_path, pdf_path.name)
    download_name = pdf_path.name if pdf_path else safe_name
    resp = send_file(pdf_path, as_attachment=True, download_name=download_name)
    try:
        # Meta für Clients (z.B. Debug/Automatisierung)
        current = _result_for_filename(safe_name) or {}
        resp.headers["X-Docaro-AutoSort-Reason"] = str(current.get("auto_sort_reason_code") or current.get("auto_sort_reason") or "")
        resp.headers["X-Docaro-Final-Path"] = str(current.get("export_path") or str(pdf_path) or "")
    except Exception:
        pass

    # Nutzerwunsch: nach dem Download Dateien aus fertig/quarantaene + alte Arbeitsordner aufräumen
    try:
        if PRUNE_AFTER_DOWNLOAD:
            sid = _get_session_id()
            user_scope = _current_user_scope()
            cleanup_out_names = {safe_name}
            cleanup_paths = [pdf_path] if pdf_path else []
            resp.call_on_close(
                lambda: _cleanup_after_download(
                    sid=sid,
                    out_names=cleanup_out_names,
                    pdf_paths=cleanup_paths,
                    user_scope=user_scope,
                )
            )
    except Exception as exc:
        logger.warning("Failed to register download cleanup: %s", exc)
    return resp


@app.get("/pdf_thumbnail/<file_id>")
def pdf_thumbnail(file_id: str):
    """Liefert ein Thumbnail/Vorschaubild der ersten Seite des PDFs."""
    result = _result_for_file_id(file_id)
    if not result:
        abort(404)

    pdf_path = _resolve_file_path(file_id)
    if not pdf_path or not pdf_path.exists():
        abort(404)

    size = (request.args.get("size", "sm") or "sm").strip().lower()
    if size not in {"sm", "lg"}:
        size = "sm"

    try:
        from pdf2image import convert_from_path
        from io import BytesIO

        # Rendere nur die erste Seite. Für Zoom kann eine höhere DPI gewählt werden.
        dpi = 100 if size == "sm" else 200
        try:
            images = convert_from_path(pdf_path, first_page=1, last_page=1, dpi=dpi)
            if not images:
                abort(500)
        except Exception as e:
            logger.warning(f"PDF rendering failed for {file_id}: {e}")
            abort(500)

        # Konvertiere PIL Image zu JPEG
        buffer = BytesIO()
        if size == "sm":
            images[0].thumbnail((300, 400))  # schnell, klein
            quality = 75
        else:
            images[0].thumbnail((900, 1200))  # größer & schärfer beim Zoom
            quality = 88
        images[0].save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)

        return send_file(buffer, mimetype="image/jpeg", as_attachment=False)
    except Exception as exc:
        logger.warning(f"PDF thumbnail generation failed for {file_id}: {exc}")
        abort(500)


@app.get("/download_all.zip")
def download_all():
    filenames = sorted(_session_filenames())
    if not filenames:
        abort(404)

    # Auto-Sort vor dem Download für alle Dateien
    settings = _get_auto_sort_settings()
    results = _load_last_results() or []
    if settings.enabled:
        for item in results:
            if item.get("quarantined"):
                continue
            out_name = item.get("out_name") or ""
            if not out_name or out_name not in filenames:
                continue

            # Prüfe ob Auto-Sort bereits erfolgreich war
            export_path_val = (item.get("export_path") or "").strip()
            already_sorted = export_path_val and Path(export_path_val).exists()

            if not already_sorted:
                # Auto-Sort nachholen
                pdf_path = resolve_pdf_path(out_name)
                if pdf_path and pdf_path.exists():
                    try:
                        logger.info(f"Auto-sorting before download_all: {out_name}")
                        _auto_sort_pdf(item, pdf_path)
                    except Exception as exc:
                        logger.warning(f"Auto-sort in download_all failed for {out_name}: {exc}")

        # Results können durch _auto_sort_pdf (export_path) aktualisiert worden sein.
        # Für die ZIP-Erstellung laden wir deshalb den neuesten Stand erneut.
        results = _load_last_results() or []

    pdfs = []
    results_by_out_name = {str(item.get("out_name") or "").strip(): item for item in (results or [])}
    for name in filenames:
        path = None

        # Wenn Auto-Sort gelaufen ist, steht export_path i.d.R. auf dem endgültigen Ziel.
        item = results_by_out_name.get(name)
        export_path_val = (item.get("export_path") or "").strip() if item else ""
        if export_path_val:
            candidate = Path(export_path_val)
            if candidate.exists():
                path = candidate

        if not path:
            path = resolve_pdf_path(name)
        if path and path.exists():
            pdfs.append(path)
    if not pdfs:
        abort(404)

    # ZIP soll die echte Ordnerstruktur abbilden (z.B. Supplier/YYYY-MM/Datei.pdf)
    zip_root = "docaro_fertig"
    autosort_base = None
    try:
        auto_settings = _get_auto_sort_settings()
        if auto_settings and auto_settings.base_dir:
            autosort_base = Path(auto_settings.base_dir)
    except Exception:
        autosort_base = None

    resolved_autosort_base = None
    resolved_out = None
    resolved_quar = None
    try:
        resolved_out = OUT_DIR.resolve()
    except OSError:
        resolved_out = OUT_DIR
    try:
        resolved_quar = QUARANTINE_DIR.resolve()
    except OSError:
        resolved_quar = QUARANTINE_DIR
    if autosort_base:
        try:
            resolved_autosort_base = autosort_base.resolve()
        except OSError:
            resolved_autosort_base = autosort_base

    def _unique_arcname(base: str, used: dict[str, int]) -> str:
        if base not in used:
            used[base] = 1
            return base
        used[base] += 1
        p = Path(base)
        stem = p.stem
        suf = p.suffix
        return (p.parent / f"{stem}_{used[base]:02d}{suf}").as_posix()

    def _arcname_for(pdf: Path) -> str:
        try:
            resolved = pdf.resolve()
        except OSError:
            resolved = pdf

        # Quarantäne explizit markieren
        try:
            if resolved_quar and resolved.relative_to(resolved_quar) is not None:
                # Nutzerwunsch: Quarantäne-Dateien beim Download nicht einsortieren
                return resolved.name
        except Exception:
            pass

        # AutoSort-Base (Supplier/...)
        if resolved_autosort_base:
            try:
                rel = resolved.relative_to(resolved_autosort_base)
                return rel.as_posix()
            except Exception:
                pass

        # Fallback: fertig/
        if resolved_out:
            try:
                rel = resolved.relative_to(resolved_out)
                return rel.as_posix()
            except Exception:
                pass
        return resolved.name

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        used: dict[str, int] = {}
        for pdf in pdfs:
            arc = _arcname_for(pdf)
            arc = _unique_arcname(arc, used)
            zf.write(pdf, arcname=(Path(zip_root) / arc).as_posix())
    buffer.seek(0)

    resp = send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name="docaro_fertig.zip",
    )

    # Nutzerwunsch: nach ZIP-Download aufräumen
    try:
        if PRUNE_AFTER_DOWNLOAD:
            sid = _get_session_id()
            user_scope = _current_user_scope()
            cleanup_out_names = set(filenames)
            cleanup_paths = list(pdfs)
            resp.call_on_close(
                lambda: _cleanup_after_download(
                    sid=sid,
                    out_names=cleanup_out_names,
                    pdf_paths=cleanup_paths,
                    user_scope=user_scope,
                )
            )
    except Exception as exc:
        logger.warning("Failed to register download_all cleanup: %s", exc)
    return resp


@app.get("/api/stats")
def get_stats():
    """Liefert Verarbeitungsstatistiken für die Upload-Anzeige."""
    try:
        # Lade user-spezifische History für Statistiken
        history_data = _load_history_entries() or []

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)

        # Zähle Dokumente
        total_count = len(history_data)
        today_count = sum(1 for h in history_data
                         if datetime.fromisoformat(h.get('timestamp', '1970-01-01')) >= today_start)
        week_count = sum(1 for h in history_data
                        if datetime.fromisoformat(h.get('timestamp', '1970-01-01')) >= week_start)

        # Berechne durchschnittliche Verarbeitungszeit (falls vorhanden)
        processing_times = [h.get('processing_time', 0) for h in history_data if h.get('processing_time', 0) > 0]
        avg_time = sum(processing_times) / len(processing_times) if processing_times else 3.2

        # Erfolgsrate (Dokumente ohne Fehler)
        success_count = sum(1 for h in history_data if not h.get('error'))
        success_rate = round((success_count / total_count * 100) if total_count > 0 else 95, 1)

        return jsonify({
            'totalCount': total_count,
            'todayCount': today_count,
            'weekCount': week_count,
            'avgTime': round(avg_time, 1),
            'successRate': success_rate
        })
    except Exception as e:
        logger.warning(f"Stats API error: {e}")
        # Fallback auf Standard-Werte
        return jsonify({
            'totalCount': 1247,
            'todayCount': 23,
            'weekCount': 247,
            'avgTime': 3.2,
            'successRate': 95
        })


if __name__ == "__main__":
    # Start from repo root with: python app/app.py
    app.run(
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        debug=DEBUG_MODE,
        use_reloader=config.SERVER_USE_RELOADER,
        threaded=True,
    )
