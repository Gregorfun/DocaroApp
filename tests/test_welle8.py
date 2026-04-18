"""Tests fuer Welle 8: Accessibility & Tastatur-First."""

from __future__ import annotations

import os
from pathlib import Path

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"
os.environ["DOCARO_DESKTOP_MODE"] = "1"


REPO = Path(__file__).resolve().parents[1]


def test_index_has_skip_link_and_main_id():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'class="skip-link"' in html
    assert 'href="#main-content"' in html
    assert 'id="main-content"' in html


def test_index_has_aria_live_region():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="docaro-aria-live"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html


def test_index_has_focus_trap_helpers():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "activateTrap" in html
    assert "releaseTrap" in html
    assert "trapTabKey" in html
    assert "FOCUSABLE_SEL" in html


def test_index_tour_has_escape_handler():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    # Welle 8: Esc schliesst Tour
    assert "Esc schliesst Tour" in html or "closeTour(true)" in html


def test_style_has_welle8_block():
    css = (REPO / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert "Welle 8: A11y" in css
    assert ".skip-link" in css
    assert ".visually-hidden" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "forced-colors: active" in css
    assert "prefers-contrast: more" in css
