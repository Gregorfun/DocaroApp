from __future__ import annotations

import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from typing import Iterable, Iterator

_LOGGER = logging.getLogger(__name__)

_PROMETHEUS_AVAILABLE = False

try:
    from prometheus_client import Counter, Gauge, Histogram, CONTENT_TYPE_LATEST, generate_latest, start_http_server

    _PROMETHEUS_AVAILABLE = True
except Exception as exc:  # pragma: no cover - optional dependency fallback
    Counter = Gauge = Histogram = None  # type: ignore[assignment]
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"  # type: ignore[assignment]
    generate_latest = None  # type: ignore[assignment]
    start_http_server = None  # type: ignore[assignment]
    _LOGGER.warning("prometheus_client not available, metrics disabled: %s", exc)


if _PROMETHEUS_AVAILABLE:
    _LATENCY_BUCKETS = (
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1,
        2,
        5,
        10,
        20,
        30,
        60,
        120,
    )

    PIPELINE_STEP_DURATION = Histogram(
        "docaro_pipeline_step_duration_seconds",
        "Duration of pipeline processing steps",
        labelnames=("step",),
        buckets=_LATENCY_BUCKETS,
    )

    PDF_RENDER_DURATION = Histogram(
        "docaro_pdf_render_duration_seconds",
        "Duration of PDF rendering",
        buckets=_LATENCY_BUCKETS,
    )

    OCR_DURATION = Histogram(
        "docaro_ocr_duration_seconds",
        "Duration of OCR processing",
        buckets=_LATENCY_BUCKETS,
    )

    PIPELINE_STEP_ERRORS = Counter(
        "docaro_pipeline_step_errors_total",
        "Errors grouped by pipeline step and error type",
        labelnames=("step", "error_type"),
    )

    PIPELINE_JOBS_TOTAL = Counter(
        "docaro_pipeline_jobs_total",
        "Number of processed pipeline jobs by status",
        labelnames=("status",),
    )

    PIPELINE_QUEUE_DEPTH = Gauge(
        "docaro_pipeline_queue_depth",
        "Current queue depth by queue name",
        labelnames=("queue",),
    )

    PIPELINE_INFLIGHT = Gauge(
        "docaro_pipeline_inflight_jobs",
        "Current number of in-flight jobs by component",
        labelnames=("component",),
    )


def metrics_enabled() -> bool:
    return _PROMETHEUS_AVAILABLE and os.getenv("DOCARO_METRICS_ENABLED", "1") == "1"


def normalize_error_type(error: object) -> str:
    if isinstance(error, BaseException):
        raw = type(error).__name__
    else:
        raw = str(error or "unknown")
    raw = raw.strip().lower() or "unknown"
    raw = raw.split(":", 1)[0]
    raw = raw.replace(" ", "_")
    raw = re.sub(r"[^a-z0-9_]+", "", raw)
    return (raw or "unknown")[:40]


def observe_pipeline_step(step: str, duration_seconds: float) -> None:
    if not metrics_enabled():
        return
    PIPELINE_STEP_DURATION.labels(step=step).observe(max(0.0, float(duration_seconds)))


def observe_pdf_render(duration_seconds: float) -> None:
    if not metrics_enabled():
        return
    PDF_RENDER_DURATION.observe(max(0.0, float(duration_seconds)))


def observe_ocr(duration_seconds: float) -> None:
    if not metrics_enabled():
        return
    OCR_DURATION.observe(max(0.0, float(duration_seconds)))


def count_step_error(step: str, error: object) -> None:
    if not metrics_enabled():
        return
    PIPELINE_STEP_ERRORS.labels(step=step, error_type=normalize_error_type(error)).inc()


def count_job(status: str) -> None:
    if not metrics_enabled():
        return
    PIPELINE_JOBS_TOTAL.labels(status=(status or "unknown").lower()).inc()


def set_queue_depth(queue: str, depth: int) -> None:
    if not metrics_enabled():
        return
    PIPELINE_QUEUE_DEPTH.labels(queue=queue).set(max(0, int(depth)))


def set_inflight(component: str, count: int) -> None:
    if not metrics_enabled():
        return
    PIPELINE_INFLIGHT.labels(component=component).set(max(0, int(count)))


def update_queue_depths(redis_conn: object, queue_names: Iterable[str]) -> None:
    if not metrics_enabled():
        return
    try:
        from rq import Queue
    except Exception as exc:
        _LOGGER.debug("rq import failed for queue metrics: %s", exc)
        return

    for queue_name in queue_names:
        try:
            depth = Queue(queue_name, connection=redis_conn).count
        except Exception as exc:
            count_step_error("queue_depth", exc)
            _LOGGER.debug("queue depth read failed for %s: %s", queue_name, exc)
            continue
        set_queue_depth(queue_name, depth)


@contextmanager
def track_step(step: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        count_step_error(step, exc)
        raise
    finally:
        observe_pipeline_step(step, time.perf_counter() - start)


_metrics_server_lock = threading.Lock()
_metrics_server_started = False


def start_metrics_http_server_from_env(default_port: int) -> None:
    if not metrics_enabled():
        return
    try:
        port = int(os.getenv("DOCARO_WORKER_METRICS_PORT", str(default_port)))
    except ValueError:
        port = default_port
    start_metrics_http_server(port)


def start_metrics_http_server(port: int) -> None:
    global _metrics_server_started
    if not metrics_enabled():
        return

    with _metrics_server_lock:
        if _metrics_server_started:
            return
        try:
            start_http_server(int(port))
            _metrics_server_started = True
            _LOGGER.info("Prometheus metrics server listening on :%s", port)
        except Exception as exc:
            _LOGGER.warning("Failed to start metrics server on port %s: %s", port, exc)


def metrics_payload() -> tuple[bytes, str]:
    if not metrics_enabled() or generate_latest is None:
        return b"", CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST
