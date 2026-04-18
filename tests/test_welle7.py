"""Tests fuer Welle 7: Toast, Offline-Banner, Auto-Retry, Empty-State."""

from __future__ import annotations

import os
from pathlib import Path

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"
os.environ["DOCARO_DESKTOP_MODE"] = "1"


REPO = Path(__file__).resolve().parents[1]


def test_index_has_offline_banner_and_toast_container():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="docaro-offline-banner"' in html
    assert 'id="docaro-toast-container"' in html
    assert 'class="offline-banner"' in html


def test_index_has_empty_state_block():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="results-empty"' in html
    assert "Filter zurücksetzen" in html
    assert 'id="results-empty-reset"' in html


def test_index_has_toast_engine_and_offline_listeners():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "window.docaroToast" in html
    assert "addEventListener('online'" in html
    assert "addEventListener('offline'" in html


def test_index_no_alert_calls_in_bulk_paths():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    # Welle 7: alert() soll vollstaendig durch notify()/docaroToast ersetzt sein
    assert "alert(" not in html


def test_index_stats_fetch_has_retry():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "fetchStatsWithRetry" in html
    # Backoff: 500 * 3^(n-1) -> 500, 1500, 4500
    assert "Math.pow(3, attempt - 1)" in html


def test_style_has_welle7_block():
    css = (REPO / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert "Welle 7: Toast" in css
    assert ".docaro-toast-container" in css
    assert ".docaro-toast--error" in css
    assert ".offline-banner" in css
    assert ".results-empty" in css
