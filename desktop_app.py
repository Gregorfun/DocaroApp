"""
DocaroApp Desktop
Startet Flask + RQ-Worker im selben Prozess (fakeredis), oeffnet ein natives Fenster via PyWebView.
Kein Redis-Server, kein Browser noetig.
"""

from __future__ import annotations

import os
import sys
import time
import socket
import threading
import logging
import traceback
from pathlib import Path

# --- Pfade konfigurieren bevor irgendetwas importiert wird ---
CODE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else CODE_DIR
APP_DIR = CODE_DIR / "app"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

os.environ.setdefault("DOCARO_RUNTIME_BASE_DIR", str(RUNTIME_DIR))

LOG_DIR = RUNTIME_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DESKTOP_LOG_PATH = LOG_DIR / "desktop_app.log"


def _configure_desktop_tesseract() -> None:
    base_candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base_candidates.append(Path(meipass))
    base_candidates.extend([RUNTIME_DIR, CODE_DIR, CODE_DIR / "_internal"])

    for base in base_candidates:
        bundle_dir = base / "Tesseract OCR Windows installer"
        exe_path = bundle_dir / "tesseract.exe"
        tessdata_dir = bundle_dir / "tessdata"
        if exe_path.exists():
            os.environ.setdefault("DOCARO_TESSERACT_CMD", str(exe_path))
            if tessdata_dir.exists():
                os.environ.setdefault("TESSDATA_PREFIX", str(tessdata_dir))
            break


_configure_desktop_tesseract()

# --- Umgebungsvariablen für Desktop-Modus ---
os.environ.setdefault("DOCARO_SERVER_PORT", "5001")
os.environ.setdefault("DOCARO_RQ_DASHBOARD_ENABLED", "0")  # kein RQ-Dashboard nötig
os.environ.setdefault("DOCARO_DESKTOP_MODE", "1")
os.environ.setdefault("DOCARO_AUTH_REQUIRED", "0")
os.environ.setdefault("DOCARO_ALLOW_SELF_REGISTER", "0")

# --- fakeredis vor redis-Importen patchen ---
import fakeredis

_fake_server = fakeredis.FakeServer()

import redis as _redis_module
from rq import SimpleWorker

_orig_from_url = _redis_module.Redis.from_url.__func__ if hasattr(_redis_module.Redis.from_url, "__func__") else None


def _fake_from_url(url, **kwargs):
    return fakeredis.FakeRedis(server=_fake_server, decode_responses=False)


_redis_module.Redis.from_url = staticmethod(_fake_from_url)

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(DESKTOP_LOG_PATH, encoding="utf-8")],
    force=True,
)
logger = logging.getLogger("docaro.desktop")


class DesktopSimpleWorker(SimpleWorker):
    """SimpleWorker variant for background threads without signal handlers."""

    def _install_signal_handlers(self):
        return None


def _install_exception_logging() -> None:
    def _log_excepthook(exc_type, exc_value, exc_traceback):
        logger.error("Unbehandelte Ausnahme", exc_info=(exc_type, exc_value, exc_traceback))

    def _thread_excepthook(args):
        logger.error(
            "Unbehandelte Thread-Ausnahme in %s",
            getattr(args, "thread", None).name if getattr(args, "thread", None) else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _log_excepthook
    threading.excepthook = _thread_excepthook


_install_exception_logging()

PORT = int(os.environ.get("DOCARO_SERVER_PORT", "5001"))


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait_for_flask(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _start_flask() -> None:
    """Flask-App im Hintergrund-Thread starten."""
    try:
        logger.info("Starte Flask-Thread")
        os.chdir(RUNTIME_DIR)
        from app.app import app
        logger.info("Flask-App importiert, starte Server auf Port %s", PORT)
        app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False, threaded=True)
    except Exception as exc:
        logger.error("Flask-Start fehlgeschlagen: %s", exc)


def _start_rq_worker() -> None:
    """RQ SimpleWorker im Hintergrund-Thread – verarbeitet Jobs direkt im Prozess."""
    try:
        logger.info("Starte RQ-Worker-Thread")
        time.sleep(3)
        from app.app import q
        worker = DesktopSimpleWorker(queues=[q], connection=q.connection)
        logger.info("RQ-Worker initialisiert")
        worker.work(burst=False, max_jobs=None)
    except Exception as exc:
        logger.warning("RQ-Worker nicht gestartet: %s", exc)


def main() -> None:
    logger.info("Desktop-App Start: CODE_DIR=%s RUNTIME_DIR=%s APP_DIR=%s", CODE_DIR, RUNTIME_DIR, APP_DIR)
    if not _port_free(PORT):
        logger.warning("Port %s bereits belegt – verbinde mit laufender Instanz.", PORT)
    else:
        logger.info("Port %s frei, starte eingebettete Dienste", PORT)
        flask_thread = threading.Thread(target=_start_flask, daemon=True, name="flask")
        flask_thread.start()

        worker_thread = threading.Thread(target=_start_rq_worker, daemon=True, name="rq-worker")
        worker_thread.start()

        logger.info("Warte auf Flask-Start...")
        if not _wait_for_flask(PORT):
            logger.error("Flask konnte nicht gestartet werden.")
            sys.exit(1)

    logger.info("Flask bereit auf Port %s.", PORT)

    logger.info("Importiere WebView")
    import webview

    logger.info("Erzeuge Desktop-Fenster")
    window = webview.create_window(
        title="DocaroApp",
        url=f"http://127.0.0.1:{PORT}/",
        width=1200,
        height=820,
        min_size=(900, 600),
        text_select=True,
    )

    logger.info("Starte WebView-Loop")
    webview.start(debug=False)


if __name__ == "__main__":
    main()
