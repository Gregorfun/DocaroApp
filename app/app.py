from __future__ import annotations

from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
import sys
import atexit
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
    has_request_context,
)
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
import threading

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
from services.auto_sort import (
    AutoSortSettings,
    decide_auto_sort,
    export_document,
    load_settings as load_auto_sort_settings,
    save_settings as save_auto_sort_settings,
    sanitize_supplier_name,
)
from core.runtime_state import RuntimeStateConfig, reset_runtime_state
from services.web_auth import install_auth
from core.performance import profile
from functools import lru_cache

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

# Stateless: Beim Start immer Runtime-State löschen (keine Dokument-/Dashboard-Persistenz)
reset_runtime_state(
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
    # Best-effort Cleanup beim Shutdown (Start-Reset ist die Hauptgarantie)
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

# Session Files Cache (mtime-based)
_session_cache = {"data": None, "mtime": 0}

# Supplier Canonicalizer Cache
_supplier_canonicalizer = None


def get_supplier_canonicalizer():
    """Lazy-load Supplier Canonicalizer (nur einmal instanziieren)."""
    global _supplier_canonicalizer
    if _supplier_canonicalizer is None:
        try:
            from core.supplier_canonicalizer import get_supplier_canonicalizer as _get_canon
            _supplier_canonicalizer = _get_canon()
        except Exception as e:
            logger.warning(f"Supplier Canonicalizer nicht verfügbar: {e}")
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
    "%m/%d/%Y",  # US (MM/DD/YYYY)
]

# Date formats accepted for manual input (same as ALLOWED_DATE_FORMATS)
MANUAL_DATE_FORMATS = ALLOWED_DATE_FORMATS

app = Flask(__name__)
# Fallback Secret Key, falls nicht gesetzt, damit Sessions zuverlässig funktionieren
app.secret_key = config.SECRET_KEY or secrets.token_hex(16)

# Zentrales Logging einrichten
logger = config.setup_logging()
app.logger = logger

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




def _log_exception(context: str, exc: Exception) -> None:
    logger.exception(f"Exception in {context}: {exc}")


@app.before_request
def _trace_upload_requests():
    if request.path == "/upload":
        logger.info(f"Request {request.method} {request.path}")


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
        logger.error(
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
    processing = _is_processing()
    progress = _load_progress()
    return render_template(
        "index.html",
        results=filtered,
        files=files,
        reset_done=reset_done,
        incomplete_only=incomplete_only,
        edit_all=edit_all,
        processing=processing,
        progress=progress,
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
        _LOGGER.warning(f"Failed to load review settings: {exc}")
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

    settings = AutoSortSettings(
        enabled=enabled,
        base_dir=base_dir,
        folder_format=folder_format,
        mode=mode,
        confidence_threshold=confidence_threshold,
        fallback_folder=fallback_folder,
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
        _LOGGER.warning(f"Failed to save review settings: {exc}")
    
    flash("Einstellungen gespeichert.")
    return redirect(url_for("settings_page"))


@app.get("/status.json")
def status_json():
    try:
        progress = _load_progress()
        return jsonify({
            "ok": True,
            "processing": _is_processing(),
            "files": _list_finished(),
            "results_count": len(_load_last_results() or []),
            "progress": progress,
        })
    except Exception as exc:
        _log_exception("status:handler", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


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
            except TimeoutError as e:
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

        date_fmt = request.form.get("date_fmt", "").strip()
        if date_fmt not in ALLOWED_DATE_FORMATS:
            date_fmt = "%Y-%m-%d"

        upload_dir = TMP_DIR / f"upload_{uuid4().hex}"
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved_count = 0
        for storage in uploaded:
            if not storage or not storage.filename:
                continue
            safe_name = secure_filename(storage.filename)
            if not safe_name or not _allowed_file(safe_name):
                continue
            target_path = get_unique_path(upload_dir, safe_name)
            storage.save(target_path)
            saved_count += 1

        if saved_count == 0:
            logger.info(
                "No valid PDFs saved. uploaded=%s",
                [getattr(f, "filename", "") for f in uploaded],
            )
            flash("Keine gültigen PDF-Dateien gefunden (nur .pdf erlaubt).")
            return redirect(url_for("index"))

        logger.info("Upload accepted: %s PDFs saved to %s", saved_count, upload_dir)

        _set_progress(total=saved_count, done=0)

        # Hintergrundverarbeitung starten und sofort zur Index-Seite redirecten
        _set_processing(True)
        threading.Thread(
            target=_background_process_upload,
            args=(upload_dir, date_fmt),
            daemon=True,
        ).start()
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
        if item.get("out_name") and not item.get("quarantined")
    ]
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
    # Verwende globale Ergebnisdatei, um Session-Mismatches zu vermeiden
    return TMP_DIR / "last_results.json"

def _processing_flag_path() -> Path:
    # Verwende globale Flag-Datei, damit der Index unabhänging von der Session greift
    return TMP_DIR / "processing.flag"


def _progress_path() -> Path:
    return TMP_DIR / "progress.json"


def _set_progress(total: int, done: int) -> None:
    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "total": int(total),
            "done": int(done),
            "percent": (float(done) / float(total) * 100.0) if total else 0.0,
        }
        tmp_path = _progress_path().with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(_progress_path())
    except Exception:
        # Progress-Anzeige darf die Verarbeitung nie brechen.
        pass


def _clear_progress() -> None:
    try:
        path = _progress_path()
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _load_progress() -> Optional[dict]:
    path = _progress_path()
    if not path.exists():
        return None
    try:
        # PowerShell (Set-Content) kann UTF-8 mit BOM schreiben; das würde json.loads sonst brechen.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None

def _set_processing(value: bool) -> None:
    try:
        if value:
            _processing_flag_path().write_text("1", encoding="utf-8")
        else:
            path = _processing_flag_path()
            if path.exists():
                path.unlink()
    except OSError:
        pass

def _is_processing() -> bool:
    try:
        return _processing_flag_path().exists()
    except OSError:
        return False

def _background_process_upload(upload_dir: Path, date_fmt: str) -> None:
    _background_process_folder(upload_dir, date_fmt=date_fmt, cleanup_input_dir=True, log_context="upload:bg_worker")


@app.post("/process_inbox")
def process_inbox():
    try:
        if _is_processing():
            flash("Es läuft bereits eine Verarbeitung.")
            return redirect(url_for("index"))

        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        pdfs = sorted(INBOX_DIR.glob("*.pdf"))
        if not pdfs:
            flash("Keine PDFs in data/eingang gefunden.")
            return redirect(url_for("index"))

        date_fmt = request.form.get("date_fmt", "").strip()
        if date_fmt not in ALLOWED_DATE_FORMATS:
            date_fmt = "%Y-%m-%d"

        _set_progress(total=len(pdfs), done=0)
        _set_processing(True)
        threading.Thread(
            target=_background_process_folder,
            args=(INBOX_DIR, date_fmt),
            kwargs={"cleanup_input_dir": False, "log_context": "inbox:bg_worker"},
            daemon=True,
        ).start()
        return redirect(url_for("index"))
    except Exception as exc:
        _log_exception("inbox:handler", exc)
        raise


@profile(threshold_seconds=2.0)
def _background_process_folder(
    input_dir: Path,
    date_fmt: str,
    cleanup_input_dir: bool = False,
    log_context: str = "bg_worker",
) -> None:
    try:
        def _progress_cb(done: int, total: int, filename: str) -> None:
            _set_progress(total=total, done=done)

        results = process_folder(input_dir, OUT_DIR, date_format=date_fmt, progress_callback=_progress_cb)
        if cleanup_input_dir:
            _clear_pdfs(input_dir)
        # WICHTIG: Keine Session-Zugriffe im Hintergrund-Thread!
        # IDs und Session-Mapping werden in der Index-Route gesetzt.
        results = _apply_result_flags(results)
        results = _apply_quarantine(results)
        
        # Auto-Sortierung direkt nach Verarbeitung (wenn aktiviert)
        settings = _get_auto_sort_settings()
        if results:
            for item in results:
                _ensure_auto_sort_fields(item)
                decision = decide_auto_sort(item, settings)
                item["auto_sort_reason_code"] = decision.reason_code
                item["auto_sort_details"] = decision.details
                if not settings.enabled:
                    item["auto_sort_status"] = "skipped"
                    item["auto_sort_reason"] = f"Nicht sortiert: {decision.reason_code}"
                    continue

                out_name = item.get("out_name") or ""
                if not out_name or item.get("quarantined"):
                    continue
                pdf_path = resolve_pdf_path(out_name)
                if pdf_path and pdf_path.exists():
                    try:
                        export_result = export_document(pdf_path, item, settings)
                        if export_result.path:
                            item["export_path"] = str(export_result.path)
                        item["auto_sort_status"] = export_result.status
                        item["auto_sort_reason"] = export_result.reason
                        item["auto_sort_reason_code"] = getattr(export_result, "reason_code", "") or decision.reason_code
                        item["auto_sort_details"] = getattr(export_result, "details", None) or decision.details
                    except Exception as exc:
                        logger.warning(f"Auto-sort failed for {out_name}: {exc}")
                        item["auto_sort_status"] = "failed"
                        item["auto_sort_reason"] = str(exc)
                        item["auto_sort_reason_code"] = "AUTOSORT_EXCEPTION"
        
        _save_last_results(results)
    except Exception as exc:
        _log_exception(log_context, exc)
    finally:
        try:
            flag = _processing_flag_path()
            if flag.exists():
                flag.unlink()
        except OSError:
            pass
        _clear_progress()


def _save_last_results(results) -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    # Nur noch Datei schreiben, keine Session mehr
    _session_results_path().write_text(json.dumps(results, indent=2), encoding="utf-8")


def _load_last_results():
    # Nur noch aus Datei lesen, Session ignorieren
    results_path = _session_results_path()
    if not results_path.exists():
        return None
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    results = _apply_supplier_corrections(results)
    for item in results or []:
        _ensure_auto_sort_fields(item)
    return results


def _load_session_files() -> dict:
    """Lädt session_files.json mit mtime-basiertem Cache."""
    global _session_cache
    
    if not SESSION_FILES_PATH.exists():
        return {}
    
    # Cache-Check: Nur neu laden wenn Datei geändert
    try:
        mtime = SESSION_FILES_PATH.stat().st_mtime
        if _session_cache["mtime"] == mtime and _session_cache["data"] is not None:
            return _session_cache["data"]
    except OSError:
        pass
    
    # Neu laden
    with _locked_file(SESSION_FILES_LOCK, mode="a+"):
        try:
            data = json.loads(SESSION_FILES_PATH.read_text(encoding="utf-8"))
            # Cache aktualisieren
            _session_cache["data"] = data
            _session_cache["mtime"] = SESSION_FILES_PATH.stat().st_mtime
            return data
        except json.JSONDecodeError:
            return {}


def _save_session_files(data: dict) -> None:
    """Speichert session_files.json und invalidiert Cache."""
    global _session_cache
    
    SESSION_FILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2)
    with _locked_file(SESSION_FILES_LOCK, mode="a+"):
        tmp_path = SESSION_FILES_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(SESSION_FILES_PATH)
    
    # Cache invalidieren (wird beim nächsten Load neu geladen)
    _session_cache["mtime"] = 0


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


def _ensure_auto_sort_fields(item: dict) -> None:
    item.setdefault("auto_sort_status", "")
    item.setdefault("auto_sort_reason", "")
    item.setdefault("auto_sort_reason_code", "")
    item.setdefault("auto_sort_details", {})
    item.setdefault("export_path", "")


def _apply_result_flags(results):
    if results is None:
        return results
    for item in results:
        _ensure_auto_sort_fields(item)
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
        "supplier_candidates": result.get("supplier_candidates") or [],
        "date": result.get("date") or "",
        "date_confidence": result.get("date_confidence") or "",
        "doc_type": result.get("doc_type") or "",
        "doc_type_confidence": result.get("doc_type_confidence") or "",
        "doc_type_evidence": result.get("doc_type_evidence") or "",
        "doc_type_scores": result.get("doc_type_scores") or {},
        "doc_type_evidence_by_type": result.get("doc_type_evidence_by_type") or {},
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
    if results_path.exists():
        try:
            results_path.unlink()
        except OSError:
            pass
    # Processing-Flag auch löschen
    proc_flag = _processing_flag_path()
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
            if new_name:
                item["out_name"] = new_name
            item["date_missing"] = _is_date_missing(date_iso, False)
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
    result = _result_for_filename(filename) or {}
    export_path_val = (result.get("export_path") or "").strip()
    if export_path_val:
        export_path = Path(export_path_val)
        if export_path.exists() and _is_allowed_pdf_path(export_path):
            return export_path
    # Search known roots first; deep scan is optional for performance reasons.
    roots = _allowed_roots()
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


def _allowed_roots() -> list[Path]:
    roots = [
        TMP_DIR,
        INBOX_DIR,
        OUT_DIR,
        QUARANTINE_DIR,
        DATA_DIR / "fertig",
        BASE_DIR / "daten_eingang",
        BASE_DIR / "daten_fertig",
    ]
    try:
        auto_settings = _get_auto_sort_settings()
        if auto_settings and auto_settings.base_dir:
            roots.append(Path(auto_settings.base_dir))
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
    export_path_val = (result.get("export_path") or "").strip()
    if export_path_val:
        export_path = Path(export_path_val)
        if export_path.exists() and _is_allowed_pdf_path(export_path):
            _set_session_file_entry(file_id, export_path, export_path.name)
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
        pdf_path.replace(target_path)
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

    new_filename = build_new_filename(supplier, date_obj, date_format=date_fmt)
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

    # Auto-Sort sollte bereits nach Verarbeitung erfolgt sein
    # Falls nicht (z.B. alte Dateien), hier nachholen
    settings = _get_auto_sort_settings()
    if result and settings.enabled and (not export_path_val or not Path(export_path_val).exists()):
        try:
            pdf_path, auto_status, auto_reason = _auto_sort_pdf(result, pdf_path)
        except Exception as exc:
            logger.warning(f"Auto-sort on download failed: {exc}")
    
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
    return resp


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
    app.run(
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        debug=DEBUG_MODE,
        use_reloader=config.SERVER_USE_RELOADER,
        threaded=True,
    )
