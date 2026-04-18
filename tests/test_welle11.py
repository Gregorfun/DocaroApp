"""Tests fuer Welle 11: Settings-UI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"
os.environ["DOCARO_DESKTOP_MODE"] = "1"

from core import user_prefs

REPO = Path(__file__).resolve().parents[1]


def test_default_prefs_include_ui_theme():
    assert user_prefs.DEFAULT_PREFS.get("ui_theme") == "auto"
    assert "auto" in user_prefs.ALLOWED_UI_THEMES
    assert "light" in user_prefs.ALLOWED_UI_THEMES
    assert "dark" in user_prefs.ALLOWED_UI_THEMES


def test_update_ui_theme_valid(tmp_path: Path):
    res = user_prefs.update_prefs(tmp_path, "scope1", ui_theme="dark")
    assert res["ui_theme"] == "dark"
    res2 = user_prefs.update_prefs(tmp_path, "scope1", ui_theme="light")
    assert res2["ui_theme"] == "light"


def test_update_ui_theme_invalid_ignored(tmp_path: Path):
    user_prefs.update_prefs(tmp_path, "s", ui_theme="dark")
    res = user_prefs.update_prefs(tmp_path, "s", ui_theme="rainbow")
    assert res["ui_theme"] == "dark"  # unverandert


def test_load_prefs_includes_ui_theme(tmp_path: Path):
    p = user_prefs.load_prefs(tmp_path, "neu")
    assert p["ui_theme"] == "auto"


# --- Routen ---

import app.app as app_module  # noqa: E402
import desktop_routes  # noqa: E402


def test_prefs_endpoint_returns_ui_theme(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    cli = app_module.app.test_client()
    r = cli.get("/api/desktop/prefs")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["prefs"]["ui_theme"] == "auto"


# --- Markup ---

def test_index_has_settings_panel():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="help-settings-section"' in html
    assert 'id="settings-date-fmt"' in html
    assert 'id="settings-doctype"' in html
    assert 'name="settings-theme"' in html
    assert "Welle 11: Settings-UI" in html


def test_style_has_welle11_block():
    css = (REPO / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert "Welle 11: Settings-UI" in css
    assert ".settings-grid" in css
    assert ".settings-radio" in css
