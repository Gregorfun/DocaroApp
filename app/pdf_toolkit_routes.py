"""
PDF-Toolkit Routes: Zusammenführen, Teilen, Komprimieren, OCR.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import time
import zipfile
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint,
    has_request_context,
    jsonify,
    render_template,
    request,
    send_file,
    session,
)
from werkzeug.utils import secure_filename

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import Config

config = Config()
_LOGGER = logging.getLogger(__name__)

pdf_toolkit_bp = Blueprint("pdf_toolkit", __name__, url_prefix="/pdf-toolkit")

# Temporäre Ergebnisse im Speicher (UUID → bytes + Dateiname)
_result_store: dict[str, tuple[bytes, str]] = {}
RESULT_TTL_SECONDS = int(os.getenv("DOCARO_PDF_TOOLKIT_RESULT_TTL_SECONDS", "3600"))
MAX_RESULT_FILES = int(os.getenv("DOCARO_PDF_TOOLKIT_MAX_RESULTS", "40"))
OCR_LANGUAGE_OPTIONS = (
    ("deu+eng", "Deutsch + Englisch", frozenset({"deu", "eng"})),
    ("deu", "Nur Deutsch", frozenset({"deu"})),
    ("eng", "Nur Englisch", frozenset({"eng"})),
    ("fra", "Franzoesisch", frozenset({"fra"})),
    ("spa", "Spanisch", frozenset({"spa"})),
    ("ita", "Italienisch", frozenset({"ita"})),
)


def _user_scope() -> str:
    if not has_request_context():
        return "system"
    user_id = session.get("user_id")
    if user_id is not None and str(user_id).strip():
        return f"user_{user_id}"
    email = (session.get("user_email") or "").strip().lower()
    return f"user_{email}" if email else "system"


def _tmp_dir() -> Path:
    scope = _user_scope()
    safe = "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in scope).strip("_") or "system"
    p = config.DATA_DIR / "users" / safe / "pdf_toolkit"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _result_dir() -> Path:
    path = _tmp_dir() / "results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _configure_tesseract_binary() -> None:
    try:
        import pytesseract
    except Exception:
        return

    configured = (os.getenv("DOCARO_TESSERACT_CMD") or "").strip()
    if configured and Path(configured).exists():
        pytesseract.pytesseract.tesseract_cmd = configured
        return

    bundled = BASE_DIR / "Tesseract OCR Windows installer" / "tesseract.exe"
    if bundled.exists():
        pytesseract.pytesseract.tesseract_cmd = str(bundled)


@lru_cache(maxsize=1)
def _installed_ocr_languages() -> frozenset[str]:
    try:
        import pytesseract

        _configure_tesseract_binary()
        return frozenset(
            lang.strip().lower()
            for lang in pytesseract.get_languages(config="")
            if lang and lang.strip()
        )
    except Exception as exc:
        _LOGGER.warning("OCR-Sprachen konnten nicht ermittelt werden: %s", exc)
        return frozenset()


def _available_ocr_options() -> list[dict[str, str]]:
    installed = _installed_ocr_languages()
    options: list[dict[str, str]] = []
    for value, label, required in OCR_LANGUAGE_OPTIONS:
        if required.issubset(installed):
            options.append({"value": value, "label": label})
    return options


def _normalize_ocr_lang(value: str | None) -> str:
    lang = (value or "").strip().lower()
    if lang == "eng+deu":
        return "deu+eng"
    return lang


def _result_meta_path(token: str) -> Path:
    return _result_dir() / f"{token}.json"


def _guess_mimetype(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".zip":
        return "application/zip"
    if suffix == ".pdf":
        return "application/pdf"
    return "application/octet-stream"


def _prune_result_files() -> None:
    result_dir = _result_dir()
    now = time.time()
    entries: list[tuple[float, str, Path, Path]] = []

    for meta_path in result_dir.glob("*.json"):
        token = meta_path.stem
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        data_name = str(payload.get("data_name") or "")
        data_path = result_dir / data_name if data_name else None
        created_at = float(payload.get("created_at") or meta_path.stat().st_mtime)

        expired = (now - created_at) > RESULT_TTL_SECONDS
        missing_data = not data_path or not data_path.exists()
        if expired or missing_data:
            try:
                meta_path.unlink(missing_ok=True)
            except OSError:
                pass
            if data_path:
                try:
                    data_path.unlink(missing_ok=True)
                except OSError:
                    pass
            _result_store.pop(token, None)
            continue

        entries.append((created_at, token, meta_path, data_path))

    if len(entries) <= MAX_RESULT_FILES:
        return

    entries.sort(key=lambda item: item[0])
    for _, token, meta_path, data_path in entries[:-MAX_RESULT_FILES]:
        try:
            meta_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            data_path.unlink(missing_ok=True)
        except OSError:
            pass
        _result_store.pop(token, None)


def _load_result(token: str) -> tuple[Path | None, str, str]:
    meta_path = _result_meta_path(token)
    if not meta_path.exists():
        return None, "", ""
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None, "", ""

    data_name = str(payload.get("data_name") or "")
    filename = str(payload.get("filename") or "")
    mimetype = str(payload.get("mimetype") or _guess_mimetype(filename))
    if not data_name or not filename:
        return None, "", ""

    data_path = _result_dir() / data_name
    if not data_path.exists():
        return None, "", ""
    return data_path, filename, mimetype


def _save_result(data: bytes, filename: str) -> tuple[str, Path]:
    token = uuid4().hex
    safe_name = secure_filename(filename or "result.bin") or "result.bin"
    result_dir = _result_dir()
    data_name = f"{token}{Path(safe_name).suffix.lower() or '.bin'}"
    data_path = result_dir / data_name
    data_path.write_bytes(data)
    meta = {
        "filename": safe_name,
        "mimetype": _guess_mimetype(safe_name),
        "data_name": data_name,
        "created_at": time.time(),
    }
    _result_meta_path(token).write_text(json.dumps(meta), encoding="utf-8")
    _result_store[token] = (data, safe_name)
    # Begrenze Store-Größe (max 20 Einträge)
    if len(_result_store) > 20:
        oldest = next(iter(_result_store))
        del _result_store[oldest]
    _prune_result_files()
    return token, data_path


def _record_recent(
    *,
    kind: str,
    filename: str,
    data_path: Path,
    token: str,
    extra: dict | None = None,
) -> None:
    try:
        from core import recent_store

        recent_store.add_recent(
            config.DATA_DIR,
            _user_scope(),
            kind=kind,
            filename=filename,
            path=str(data_path),
            download_token=token,
            extra=extra or {},
        )
    except Exception as exc:  # pragma: no cover - best effort
        _LOGGER.debug("recent_store add failed: %s", exc)


@pdf_toolkit_bp.route("/")
def toolkit_page():
    options = _available_ocr_options()
    available_values = {item["value"] for item in options}
    unavailable_labels = [
        label for value, label, _ in OCR_LANGUAGE_OPTIONS if value not in available_values
    ]

    status_message = ""
    if not options:
        status_message = "Keine installierten OCR-Sprachdaten gefunden. OCR ist aktuell nicht verfuegbar."
    elif unavailable_labels:
        status_message = "Nicht installierte OCR-Sprachen wurden ausgeblendet: " + ", ".join(unavailable_labels)

    return render_template(
        "pdf_toolkit.html",
        ocr_lang_options=options,
        ocr_status_message=status_message,
        ocr_enabled=bool(options),
    )


@pdf_toolkit_bp.route("/merge", methods=["POST"])
def merge():
    files = request.files.getlist("files")
    if len(files) < 2:
        return jsonify({"error": "Mindestens 2 PDFs erforderlich."}), 400

    tmp = _tmp_dir() / uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    try:
        for f in files:
            name = secure_filename(f.filename or "upload.pdf")
            dest = tmp / name
            # Verhindere Namenskollisionen
            if dest.exists():
                dest = tmp / f"{dest.stem}_{uuid4().hex[:6]}{dest.suffix}"
            f.save(str(dest))
            saved.append(dest)

        out = tmp / "zusammengefuehrt.pdf"
        from core.pdf_toolkit import merge_pdfs
        merge_pdfs(saved, out)

        data = out.read_bytes()
        token, data_path = _save_result(data, "zusammengefuehrt.pdf")
        _record_recent(kind="merge", filename="zusammengefuehrt.pdf", data_path=data_path, token=token)
        return jsonify({
            "token": token,
            "filename": "zusammengefuehrt.pdf",
            "path": str(data_path),
        })
    except Exception as exc:
        _LOGGER.exception("Merge fehlgeschlagen: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


@pdf_toolkit_bp.route("/split", methods=["POST"])
def split():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Keine Datei übergeben."}), 400

    mode = request.form.get("mode", "pages")  # 'pages' oder 'ranges'
    ranges_raw = request.form.get("ranges", "").strip()

    tmp = _tmp_dir() / uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        src = tmp / "input.pdf"
        f.save(str(src))

        parsed_ranges = None
        if mode == "ranges" and ranges_raw:
            parsed_ranges = _parse_ranges(ranges_raw)
            if parsed_ranges is None:
                return jsonify({"error": "Ungültige Seitenbereiche. Beispiel: 1-3, 5-7"}), 400

        out_dir = tmp / "split"
        from core.pdf_toolkit import split_pdf
        parts = split_pdf(src, out_dir, ranges=parsed_ranges)

        if not parts:
            return jsonify({"error": "Keine Seiten gefunden."}), 500

        # Mehrere Dateien → ZIP
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in parts:
                zf.write(p, p.name)
        buf.seek(0)
        token, data_path = _save_result(buf.read(), "aufgeteilt.zip")
        _record_recent(
            kind="split",
            filename="aufgeteilt.zip",
            data_path=data_path,
            token=token,
            extra={"parts": len(parts)},
        )
        return jsonify({
            "token": token,
            "filename": "aufgeteilt.zip",
            "parts": len(parts),
            "path": str(data_path),
        })
    except Exception as exc:
        _LOGGER.exception("Split fehlgeschlagen: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


@pdf_toolkit_bp.route("/compress", methods=["POST"])
def compress():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Keine Datei übergeben."}), 400

    quality = request.form.get("quality", "medium")
    if quality not in ("low", "medium", "high"):
        quality = "medium"

    tmp = _tmp_dir() / uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        name = secure_filename(f.filename or "dokument.pdf")
        src = tmp / "input.pdf"
        f.save(str(src))

        out = tmp / f"komprimiert_{name}"
        from core.pdf_toolkit import compress_pdf
        compress_pdf(src, out, quality=quality)

        original_kb = src.stat().st_size // 1024
        compressed_kb = out.stat().st_size // 1024
        savings = max(0, round((1 - compressed_kb / max(original_kb, 1)) * 100))

        stem = Path(name).stem
        dl_name = f"{stem}_komprimiert.pdf"
        data = out.read_bytes()
        token, data_path = _save_result(data, dl_name)
        _record_recent(
            kind="compress",
            filename=dl_name,
            data_path=data_path,
            token=token,
            extra={"savings_pct": savings},
        )
        return jsonify({
            "token": token,
            "filename": dl_name,
            "original_kb": original_kb,
            "compressed_kb": compressed_kb,
            "savings_pct": savings,
            "path": str(data_path),
        })
    except Exception as exc:
        _LOGGER.exception("Compress fehlgeschlagen: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


@pdf_toolkit_bp.route("/ocr", methods=["POST"])
def ocr():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Keine Datei übergeben."}), 400

    available_options = _available_ocr_options()
    if not available_options:
        return jsonify({"error": "Keine installierten OCR-Sprachdaten verfuegbar."}), 503

    available_langs = {item["value"] for item in available_options}
    lang = _normalize_ocr_lang(request.form.get("lang"))
    if not lang:
        lang = available_options[0]["value"]
    if lang not in available_langs:
        return jsonify({
            "error": "OCR-Sprache ist nicht installiert. Verfuegbar: " + ", ".join(sorted(available_langs))
        }), 400

    tmp = _tmp_dir() / uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        name = secure_filename(f.filename or "dokument.pdf")
        src = tmp / "input.pdf"
        f.save(str(src))

        out = tmp / f"ocr_{name}"
        from core.pdf_toolkit import ocr_pdf
        ocr_pdf(src, out, lang=lang)

        stem = Path(name).stem
        dl_name = f"{stem}_ocr.pdf"
        data = out.read_bytes()
        token, data_path = _save_result(data, dl_name)
        _record_recent(
            kind="ocr",
            filename=dl_name,
            data_path=data_path,
            token=token,
            extra={"lang": lang},
        )
        return jsonify({
            "token": token,
            "filename": dl_name,
            "path": str(data_path),
        })
    except Exception as exc:
        _LOGGER.exception("OCR fehlgeschlagen: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


@pdf_toolkit_bp.route("/download/<token>")
def download(token: str):
    entry = _result_store.get(token)
    if entry:
        data, filename = entry
        return send_file(
            io.BytesIO(data),
            download_name=filename,
            as_attachment=True,
            mimetype=_guess_mimetype(filename),
        )

    data_path, filename, mimetype = _load_result(token)
    if not data_path:
        return "Datei nicht mehr verfügbar.", 404
    return send_file(data_path, download_name=filename, as_attachment=True, mimetype=mimetype)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _parse_ranges(raw: str) -> list[tuple[int, int]] | None:
    """'1-3, 5, 7-9' → [(1,3),(5,5),(7,9)] oder None bei Fehler."""
    results = []
    try:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                a, b = int(a.strip()), int(b.strip())
                if a < 1 or b < a:
                    return None
                results.append((a, b))
            else:
                n = int(part)
                if n < 1:
                    return None
                results.append((n, n))
    except ValueError:
        return None
    return results or None
