# ruff: noqa: E402
import os
import sys
import logging
import threading
import time
from pathlib import Path
from redis import Redis
from rq import Worker, Queue

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Prepend project root to sys.path so imports work regardless of install path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from core.metrics import (
    count_step_error,
    start_metrics_http_server_from_env,
    update_queue_depths,
)  # noqa: E402
from core.observability import init_sentry  # noqa: E402

listen = ["high", "default", "low"]
os.environ.setdefault("DOCARO_WORKER", "1")
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

conn = Redis.from_url(redis_url)
queue_max_depth = int(os.getenv("DOCARO_QUEUE_MAX_DEPTH", "200"))


def _start_queue_metrics_thread() -> None:
    """Periodically publish queue depth metrics for Prometheus."""
    listen_queues = tuple(listen)
    interval = float(os.getenv("DOCARO_QUEUE_METRICS_INTERVAL_SECONDS", "5") or "5")

    def _loop() -> None:
        while True:
            try:
                update_queue_depths(conn, listen_queues)
            except Exception as exc:
                count_step_error("queue_depth", exc)
            time.sleep(max(1.0, interval))

    thread = threading.Thread(target=_loop, name="docaro-queue-metrics", daemon=True)
    thread.start()
    logger.info("Queue-Metrics Thread gestartet (interval=%ss)", interval)


def _start_inbox_scheduler_thread() -> None:
    """Startet einen einfachen Interval-Scheduler für 'Eingang verarbeiten'.

    Läuft im Worker-Prozess, damit es genau eine Instanz gibt (systemd Service).
    """
    try:
        from config import Config
        from app.app import (
            _get_auto_sort_settings,
            _is_processing,
            _resolve_inbox_dir,
            _set_processing,
            _set_progress,
            background_process_folder,
            q,
        )
    except Exception as exc:
        logger.warning("Inbox-Scheduler konnte nicht initialisiert werden: %s", exc)
        return

    cfg = Config()
    # Keep consistent with the dashboard's default for /process_inbox
    date_fmt = "%d-%m-%Y"

    def _loop() -> None:
        last_check = 0.0
        while True:
            try:
                settings = _get_auto_sort_settings(refresh=True)
                interval_minutes = int(getattr(settings, "inbox_interval_minutes", 0) or 0)
                inbox_dir_setting = getattr(settings, "inbox_dir", cfg.INBOX_DIR) or cfg.INBOX_DIR
                inbox_dir_raw_str = str(inbox_dir_setting)
                if os.name != "nt":
                    # On Linux, Windows local drive paths are not accessible.
                    try:
                        from app.app import _looks_like_windows_drive_path

                        if _looks_like_windows_drive_path(inbox_dir_raw_str):
                            logger.warning(
                                "Inbox-Autojob übersprungen: Windows-Pfad auf Linux nicht erreichbar (%s). "
                                "Bitte SMB/CIFS mounten und Linux-Pfad verwenden.",
                                inbox_dir_raw_str,
                            )
                            time.sleep(10)
                            continue
                    except Exception:
                        pass

                inbox_dir_raw = Path(inbox_dir_setting)
                inbox_dir = _resolve_inbox_dir(inbox_dir_raw)

                if interval_minutes <= 0:
                    time.sleep(10)
                    continue

                now = time.monotonic()
                if now - last_check < float(interval_minutes) * 60.0:
                    time.sleep(2)
                    continue
                last_check = now

                if _is_processing():
                    continue

                inbox_dir.mkdir(parents=True, exist_ok=True)
                pdfs = sorted(p for p in inbox_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
                if not pdfs:
                    continue

                _set_progress(total=len(pdfs), done=0)
                _set_processing(True)
                try:
                    current_depth = int(q.count)
                    if current_depth >= queue_max_depth:
                        logger.warning(
                            "Inbox-Autojob übersprungen: Queue ausgelastet (%s >= %s)",
                            current_depth,
                            queue_max_depth,
                        )
                        _set_processing(False)
                        time.sleep(5)
                        continue
                    q.enqueue(
                        background_process_folder,
                        args=(inbox_dir, date_fmt),
                        kwargs={"cleanup_input_dir": False, "log_context": "inbox:auto_worker"},
                        job_timeout="1h",
                        result_ttl=86400,
                    )
                    logger.info(
                        "Inbox-Autojob enqueued (%s PDFs, interval=%sm, dir=%s)",
                        len(pdfs),
                        interval_minutes,
                        inbox_dir,
                    )
                except Exception:
                    _set_processing(False)
                    raise
            except Exception as exc:
                logger.warning("Inbox-Scheduler Loop Fehler: %s", exc)
                time.sleep(10)

    thread = threading.Thread(target=_loop, name="docaro-inbox-scheduler", daemon=True)
    thread.start()
    logger.info("Inbox-Scheduler Thread gestartet")


if __name__ == "__main__":
    logger.info(f"Starting worker with Redis URL: {redis_url}")
    try:
        init_sentry("worker")
        start_metrics_http_server_from_env(default_port=9108)
        _start_queue_metrics_thread()
        _start_inbox_scheduler_thread()
        # Explicitly pass connection to Queues and Worker to avoid context manager issues
        queues = [Queue(name, connection=conn) for name in listen]
        worker = Worker(queues, connection=conn)
        worker.work()
    except Exception as e:
        logger.error(f"Failed to start worker: {e}")
        # Print full traceback to logs
        import traceback

        traceback.print_exc()
        sys.exit(1)
