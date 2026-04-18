"""Tests fuer Welle 9: Datenpflege & Backup."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"
os.environ["DOCARO_DESKTOP_MODE"] = "1"

from core import user_backup

REPO = Path(__file__).resolve().parents[1]


def _seed(tmp: Path, scope: str) -> Path:
    sd = tmp / "users" / scope
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "prefs.json").write_text(json.dumps({"last_doctype": "Rechnung"}), encoding="utf-8")
    (sd / "recent.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    return sd


def test_create_and_list_backup(tmp_path: Path):
    _seed(tmp_path, "user_42")
    res = user_backup.create_backup(tmp_path, "user_42")
    assert res["ok"] is True
    assert res["name"].startswith("backup-") and res["name"].endswith(".zip")
    items = user_backup.list_backups(tmp_path, "user_42")
    assert len(items) == 1 and items[0]["name"] == res["name"]


def test_create_backup_no_data(tmp_path: Path):
    res = user_backup.create_backup(tmp_path, "leer")
    assert res["ok"] is False


def test_prune_keeps_max(tmp_path: Path):
    bdir = tmp_path / "users" / "u" / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    for i in range(12):
        (bdir / f"backup-2026010{i % 10}-12{i:04d}.zip").write_bytes(b"x")
    removed = user_backup.prune_backups(tmp_path, "u", keep=10)
    assert removed == 2
    assert len(user_backup.list_backups(tmp_path, "u")) == 10


def test_export_and_import_roundtrip(tmp_path: Path):
    _seed(tmp_path, "u")
    data = user_backup.export_user_data(tmp_path, "u")
    assert data[:2] == b"PK"
    (tmp_path / "users" / "u" / "prefs.json").unlink()
    res = user_backup.import_user_data(tmp_path, "u", data)
    assert res["ok"] is True
    assert "prefs.json" in res["restored"]
    assert (tmp_path / "users" / "u" / "prefs.json").exists()


def test_import_rejects_invalid_zip(tmp_path: Path):
    _seed(tmp_path, "u")
    res = user_backup.import_user_data(tmp_path, "u", b"not-a-zip")
    assert res["ok"] is False


def test_import_rejects_bad_json(tmp_path: Path):
    _seed(tmp_path, "u")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("prefs.json", b"{not json")
    res = user_backup.import_user_data(tmp_path, "u", buf.getvalue())
    assert res["ok"] is False


def test_read_backup_path_traversal_blocked(tmp_path: Path):
    _seed(tmp_path, "u")
    user_backup.create_backup(tmp_path, "u")
    assert user_backup.read_backup(tmp_path, "u", "../../etc/passwd") is None
    assert user_backup.read_backup(tmp_path, "u", "anything.zip") is None


def test_safe_scope_normalizes():
    assert user_backup._safe_scope("../boom") == ".._boom"
    assert user_backup._safe_scope("") == "system"
    assert user_backup._safe_scope("user_1") == "user_1"


import app.app as app_module  # noqa: E402
import desktop_routes  # noqa: E402


def test_backup_export_download(tmp_path: Path, monkeypatch):
    """GET /api/desktop/backup/export.zip ohne CSRF, nur Read."""
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    sd = tmp_path / "users" / "system"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "prefs.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
    cli = app_module.app.test_client()
    r = cli.get("/api/desktop/backup/export.zip")
    try:
        assert r.status_code == 200
        assert r.data[:2] == b"PK"
        assert "docaro-userdata-" in r.headers.get("Content-Disposition", "")
    finally:
        r.close()


def test_backup_list_endpoint_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    cli = app_module.app.test_client()
    r = cli.get("/api/desktop/backup")
    try:
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["backups"] == []
        assert body["max"] == 10
    finally:
        r.close()


def test_index_has_backup_panel():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="help-backup-section"' in html
    assert 'id="backup-create-btn"' in html
    assert 'id="backup-list"' in html
    assert "Welle 9: Datenpflege" in html


def test_style_has_welle9_block():
    css = (REPO / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert "Welle 9: Backup-Panel" in css
    assert ".backup-list" in css
    assert ".backup-actions" in css
