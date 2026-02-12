from __future__ import annotations

import logging
import os
from typing import Any

_LOGGER = logging.getLogger(__name__)
_SENTRY_INITIALIZED = False


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def init_sentry(component: str) -> bool:
    """Initialize Sentry once per process.

    Enabled when DOCARO_SENTRY_DSN is set and DOCARO_SENTRY_ENABLED != 0.
    """
    global _SENTRY_INITIALIZED
    if _SENTRY_INITIALIZED:
        return True

    if os.getenv("DOCARO_SENTRY_ENABLED", "1") != "1":
        return False

    dsn = (os.getenv("DOCARO_SENTRY_DSN") or "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.rq import RqIntegration
    except Exception as exc:
        _LOGGER.warning("Sentry SDK import failed: %s", exc)
        return False

    integrations: list[Any] = [
        RqIntegration(),
        LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
    ]

    try:
        from sentry_sdk.integrations.flask import FlaskIntegration

        integrations.append(FlaskIntegration())
    except Exception:
        pass

    environment = os.getenv("DOCARO_SENTRY_ENVIRONMENT") or (
        "development" if os.getenv("DOCARO_DEBUG", "0") == "1" else "production"
    )
    release = os.getenv("DOCARO_RELEASE") or os.getenv("GIT_COMMIT") or "docaro-unknown"

    traces_sample_rate = _env_float("DOCARO_SENTRY_TRACES_SAMPLE_RATE", 0.0)
    profiles_sample_rate = _env_float("DOCARO_SENTRY_PROFILES_SAMPLE_RATE", 0.0)

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            integrations=integrations,
            traces_sample_rate=max(0.0, min(1.0, traces_sample_rate)),
            profiles_sample_rate=max(0.0, min(1.0, profiles_sample_rate)),
            attach_stacktrace=True,
            send_default_pii=False,
        )
        sentry_sdk.set_tag("component", component)
        _SENTRY_INITIALIZED = True
        _LOGGER.info("Sentry initialized (component=%s, environment=%s, release=%s)", component, environment, release)
        return True
    except Exception as exc:
        _LOGGER.warning("Sentry init failed: %s", exc)
        return False
