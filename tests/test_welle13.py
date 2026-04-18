"""Welle 13: Naming-Template-Hook + Saved-Searches + Trash-Bin Tests."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app import desktop_routes
import app.app as app_module
from core import naming_templates, saved_searches, trash_bin
from core.extractor import build_new_filename


# ---------------------------------------------------------------------------
# 13A: Provider-Hook in build_new_filename
# ---------------------------------------------------------------------------

def test_build_new_filename_uses_active_template_provider():
    naming_templates.set_active_template_provider(lambda: "{supplier}-{date_iso}-{doc_number}")
    try:
        out = build_new_filename("ACME", datetime(2025, 7, 4), delivery_note_nr="LS-1")
        assert out == "ACME-2025-07-04-LS-1.pdf"
    finally:
        naming_templates.set_active_template_provider(None)


def test_build_new_filename_explicit_template_overrides_provider():
    naming_templates.set_active_template_provider(lambda: "{supplier}-{date_iso}")
    try:
        out = build_new_filename(
            "ACME",
            datetime(2025, 7, 4),
            delivery_note_nr="LS-1",
            template="{doc_number}_{year}",
        )
        assert out == "LS-1_2025.pdf"
    finally:
        naming_templates.set_active_template_provider(None)


def test_build_new_filename_no_provider_falls_back_to_classic():
    naming_templates.set_active_template_provider(None)
    out = build_new_filename("ACME", datetime(2025, 7, 4), delivery_note_nr="LS-1", date_format="%d-%m-%Y")
    assert out == "ACME_04-07-2025_LS-1.pdf"


def test_build_new_filename_invalid_provider_template_falls_back():
    naming_templates.set_active_template_provider(lambda: "{nope}")
    try:
        out = build_new_filename("ACME", datetime(2025, 7, 4), delivery_note_nr="LS-1", date_format="%d-%m-%Y")
        assert out == "ACME_04-07-2025_LS-1.pdf"
    finally:
        naming_templates.set_active_template_provider(None)


def test_provider_exception_does_not_crash():
    def boom() -> str:
        raise RuntimeError("nope")
    naming_templates.set_active_template_provider(boom)
    try:
        out = build_new_filename("ACME", datetime(2025, 7, 4), date_format="%d-%m-%Y")
        assert out == "ACME_04-07-2025.pdf"
    finally:
        naming_templates.set_active_template_provider(None)


# ---------------------------------------------------------------------------
# 13B: Saved-Searches
# ---------------------------------------------------------------------------

def test_saved_searches_create_list_delete(tmp_path: Path):
    scope = "alice"
    entry = saved_searches.create_search(tmp_path, scope, {
        "name": "Letzte Rechnungen",
        "query": "ACME",
        "doctype": "RECHNUNG",
        "status": "fertig",
        "sort": "date_desc",
        "date_from": "2025-01-01",
        "date_to": "2025-12-31",
    })
    assert entry["id"]
    assert entry["name"] == "Letzte Rechnungen"
    items = saved_searches.list_searches(tmp_path, scope)
    assert len(items) == 1
    assert items[0]["doctype"] == "RECHNUNG"
    assert items[0]["sort"] == "date_desc"
    ok = saved_searches.delete_search(tmp_path, scope, entry["id"])
    assert ok is True
    assert saved_searches.list_searches(tmp_path, scope) == []


def test_saved_searches_sanitization(tmp_path: Path):
    entry = saved_searches.create_search(tmp_path, "bob", {
        "name": "X",
        "status": "evil",
        "sort": "boom",
        "date_from": "not-a-date",
        "date_to": "2025-13-40",
    })
    assert entry["status"] == ""
    assert entry["sort"] == ""
    assert entry["date_from"] == ""
    assert entry["date_to"] == ""


def test_saved_searches_max_limit(tmp_path: Path):
    for i in range(saved_searches.MAX_SEARCHES):
        saved_searches.create_search(tmp_path, "carol", {"name": f"S{i}"})
    with pytest.raises(ValueError):
        saved_searches.create_search(tmp_path, "carol", {"name": "overflow"})


def test_saved_searches_empty_name_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        saved_searches.create_search(tmp_path, "dave", {"name": "   "})


def test_saved_searches_delete_unknown(tmp_path: Path):
    assert saved_searches.delete_search(tmp_path, "ed", "unknown") is False


# ---------------------------------------------------------------------------
# 13C: Trash-Bin
# ---------------------------------------------------------------------------

def test_trash_move_and_restore(tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    pdf = out_dir / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    entry = trash_bin.move_to_trash(tmp_path, "alice", pdf, metadata={"supplier": "ACME"})
    assert not pdf.exists()
    assert entry["id"]
    assert entry["metadata"]["supplier"] == "ACME"
    items = trash_bin.list_items(tmp_path, "alice")
    assert len(items) == 1
    restored = trash_bin.restore(tmp_path, "alice", entry["id"])
    assert restored == pdf
    assert restored.exists()
    assert trash_bin.list_items(tmp_path, "alice") == []


def test_trash_restore_conflict_appends_suffix(tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    pdf = out_dir / "x.pdf"
    pdf.write_bytes(b"a")
    entry = trash_bin.move_to_trash(tmp_path, "bob", pdf)
    # neue Datei mit gleichem Namen anlegen
    pdf.write_bytes(b"new")
    restored = trash_bin.restore(tmp_path, "bob", entry["id"])
    assert restored.name == "x_restored.pdf"
    assert restored.exists()
    assert pdf.exists()


def test_trash_purge_removes_file(tmp_path: Path):
    pdf = tmp_path / "y.pdf"
    pdf.write_bytes(b"a")
    entry = trash_bin.move_to_trash(tmp_path, "carol", pdf)
    stored = tmp_path / "users" / "carol" / "trash" / entry["stored_name"]
    assert stored.exists()
    assert trash_bin.purge(tmp_path, "carol", entry["id"]) is True
    assert not stored.exists()
    assert trash_bin.list_items(tmp_path, "carol") == []


def test_trash_empty_clears_all(tmp_path: Path):
    for i in range(3):
        p = tmp_path / f"{i}.pdf"
        p.write_bytes(b"a")
        trash_bin.move_to_trash(tmp_path, "dave", p)
    n = trash_bin.empty_trash(tmp_path, "dave")
    assert n == 3
    assert trash_bin.list_items(tmp_path, "dave") == []


def test_trash_prune_expired(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "old.pdf"
    pdf.write_bytes(b"a")
    entry = trash_bin.move_to_trash(tmp_path, "eve", pdf)
    # Manipuliere deleted_at auf 30 Tage in der Vergangenheit
    reg = tmp_path / "users" / "eve" / "trash" / "trash.json"
    items = json.loads(reg.read_text(encoding="utf-8"))
    items[0]["deleted_at"] = "2000-01-01T00:00:00"
    reg.write_text(json.dumps(items), encoding="utf-8")
    removed = trash_bin.prune_expired(tmp_path, "eve")
    assert removed == 1
    assert trash_bin.list_items(tmp_path, "eve") == []


# ---------------------------------------------------------------------------
# Routen via test_request_context (CSRF-Bypass)
# ---------------------------------------------------------------------------

def test_searches_routes_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(desktop_routes, "_user_scope", lambda: "alice")
    with app_module.app.test_request_context(method="POST", json={"name": "Test"}):
        resp = desktop_routes.searches_create()
    body = resp.get_json() if hasattr(resp, "get_json") else resp[0].get_json()
    assert body["ok"] is True
    sid = body["search"]["id"]
    with app_module.app.test_request_context(method="GET"):
        resp = desktop_routes.searches_list()
    body = resp.get_json()
    assert len(body["searches"]) == 1
    with app_module.app.test_request_context(method="POST"):
        resp = desktop_routes.searches_delete(sid)
    body = resp.get_json() if hasattr(resp, "get_json") else resp[0].get_json()
    assert body["ok"] is True


def test_trash_routes_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(desktop_routes, "_user_scope", lambda: "alice")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"a")
    trash_bin.move_to_trash(tmp_path, "alice", pdf)
    with app_module.app.test_request_context(method="GET"):
        resp = desktop_routes.trash_list()
    body = resp.get_json()
    assert body["ok"] is True
    assert len(body["items"]) == 1
    assert body["retention_days"] == trash_bin.RETENTION_DAYS
    tid = body["items"][0]["id"]
    with app_module.app.test_request_context(method="POST"):
        resp = desktop_routes.trash_restore(tid)
    body = resp.get_json() if hasattr(resp, "get_json") else resp[0].get_json()
    assert body["ok"] is True
    assert pdf.exists()


def test_trash_purge_route(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(desktop_routes, "_user_scope", lambda: "bob")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"a")
    entry = trash_bin.move_to_trash(tmp_path, "bob", pdf)
    with app_module.app.test_request_context(method="POST"):
        resp = desktop_routes.trash_purge(entry["id"])
    body = resp.get_json() if hasattr(resp, "get_json") else resp[0].get_json()
    assert body["ok"] is True
    assert trash_bin.list_items(tmp_path, "bob") == []


def test_trash_empty_route(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(desktop_routes, "_user_scope", lambda: "carol")
    for i in range(2):
        p = tmp_path / f"{i}.pdf"
        p.write_bytes(b"a")
        trash_bin.move_to_trash(tmp_path, "carol", p)
    with app_module.app.test_request_context(method="POST"):
        resp = desktop_routes.trash_empty()
    body = resp.get_json()
    assert body["ok"] is True
    assert body["removed"] == 2


# ---------------------------------------------------------------------------
# Markup-Smoke
# ---------------------------------------------------------------------------

def test_index_html_contains_w13_markup():
    html = (Path(__file__).resolve().parent.parent / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "results-toolbar-row--w13b" in html
    assert 'id="saved-searches-select"' in html
    assert 'id="trash-modal"' in html
    assert 'id="open-trash-btn"' in html


def test_style_css_contains_w13_classes():
    css = (Path(__file__).resolve().parent.parent / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert ".results-toolbar-row--w13b" in css
    assert ".trash-modal-content" in css
    assert ".trash-item" in css
