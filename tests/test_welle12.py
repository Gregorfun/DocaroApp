"""Tests fuer Welle 12: Naming-Templates + Sortierung + Datums-Range-Filter."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"
os.environ["DOCARO_DESKTOP_MODE"] = "1"

from core import naming_templates as nt
from core import user_prefs

REPO = Path(__file__).resolve().parents[1]


# ---- naming_templates Modul ----

def test_default_template_valid():
    assert nt.is_valid_template(nt.DEFAULT_TEMPLATE)


def test_invalid_token_rejected():
    assert not nt.is_valid_template("{evil}_{supplier}")
    assert not nt.is_valid_template("")
    assert not nt.is_valid_template("a" * (nt.MAX_TEMPLATE_LEN + 1))


def test_render_basic():
    ctx = nt.build_context(
        supplier="ACME GmbH",
        date_obj=datetime(2026, 12, 31),
        date_format="%d-%m-%Y",
        doc_number="R12345",
        doctype="RECHNUNG",
    )
    out = nt.render_template("{supplier}_{date}_{doc_number}", ctx)
    assert "ACME" in out
    assert "31-12-2026" in out
    assert "R12345" in out


def test_render_alt_tokens():
    ctx = nt.build_context(
        supplier="ACME",
        date_obj=datetime(2026, 1, 5),
        doc_number="",
        doctype="LIEFERSCHEIN",
    )
    out = nt.render_template("{date_iso}_{doctype}_{supplier}_{year}-{month}", ctx)
    assert out.startswith("2026-01-05_LIEFERSCHEIN_ACME_2026-01")


def test_unsafe_chars_sanitized():
    ctx = nt.build_context(supplier="A<>:|/B", date_obj=datetime(2026, 1, 1))
    out = nt.render_template("{supplier}_{date}", ctx)
    for bad in "<>:|/\\":
        assert bad not in out


def test_invalid_template_falls_back_to_default():
    ctx = nt.build_context(supplier="X", date_obj=datetime(2026, 1, 1))
    out = nt.render_template("{evil}", ctx)
    # Default-Template => sollte X_01-01-2026 enthalten
    assert "X" in out
    assert "01-01-2026" in out


def test_preview_uses_sample_data():
    p = nt.preview("{supplier}_{date}")
    assert p.endswith(".pdf")
    assert "ACME" in p


def test_empty_context_renders_unbenannt():
    ctx = nt.build_context()
    assert nt.render_template("{supplier}_{date}", ctx) == "Unbenannt"


# ---- user_prefs Integration ----

def test_filename_template_pref(tmp_path: Path):
    res = user_prefs.update_prefs(tmp_path, "s", filename_template="{supplier}_{date}")
    assert res["filename_template"] == "{supplier}_{date}"
    # ungueltig => unverandert
    res2 = user_prefs.update_prefs(tmp_path, "s", filename_template="{evil}")
    assert res2["filename_template"] == "{supplier}_{date}"
    # leer => zuruecksetzen
    res3 = user_prefs.update_prefs(tmp_path, "s", filename_template="")
    assert res3["filename_template"] == ""


def test_results_sort_pref(tmp_path: Path):
    res = user_prefs.update_prefs(tmp_path, "s", results_sort="date_desc")
    assert res["results_sort"] == "date_desc"
    res2 = user_prefs.update_prefs(tmp_path, "s", results_sort="bogus")
    assert res2["results_sort"] == "date_desc"  # unverandert
    res3 = user_prefs.update_prefs(tmp_path, "s", results_sort="")
    assert res3["results_sort"] == ""


# ---- Routen ----

import app.app as app_module  # noqa: E402
import desktop_routes  # noqa: E402


def test_naming_preview_endpoint_valid(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    # POST waere CSRF-blockiert; teste die Route-Funktion direkt im request_context.
    with app_module.app.test_request_context(
        "/api/desktop/naming/preview",
        method="POST",
        json={"template": "{supplier}_{date}"},
    ):
        resp = desktop_routes.naming_preview()
    body = resp.get_json()
    assert body["ok"] is True
    assert body["valid"] is True
    assert body["preview"].endswith(".pdf")
    assert "tokens" in body


def test_naming_preview_endpoint_invalid(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    with app_module.app.test_request_context(
        "/api/desktop/naming/preview",
        method="POST",
        json={"template": "{evil}"},
    ):
        resp = desktop_routes.naming_preview()
    body = resp.get_json()
    assert body["valid"] is False
    assert body["preview"] == ""


def test_naming_preview_endpoint_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    with app_module.app.test_request_context(
        "/api/desktop/naming/preview",
        method="POST",
        json={"template": ""},
    ):
        resp = desktop_routes.naming_preview()
    body = resp.get_json()
    assert body["ok"] is True
    assert body["valid"] is False
    assert body["default"] == nt.DEFAULT_TEMPLATE


def test_prefs_endpoint_returns_w12_fields(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    cli = app_module.app.test_client()
    r = cli.get("/api/desktop/prefs")
    body = r.get_json()
    assert "filename_template" in body["prefs"]
    assert "results_sort" in body["prefs"]


# ---- Markup ----

def test_index_has_w12_toolbar():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="results-sort"' in html
    assert 'id="results-date-from"' in html
    assert 'id="results-date-to"' in html
    assert 'id="settings-filename-template"' in html
    assert 'id="settings-filename-preview"' in html
    assert "Welle 12" in html


def test_style_has_w12_block():
    css = (REPO / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert "Welle 12: Search/Sort + Naming-Templates" in css
    assert ".results-toolbar-row--w12" in css
    assert ".settings-hint" in css
