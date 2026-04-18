"""Tests fuer Welle 10: Multi-User & Profile-Switching."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"
os.environ["DOCARO_DESKTOP_MODE"] = "1"

from core import user_profiles

REPO = Path(__file__).resolve().parents[1]


def test_default_registry_when_missing(tmp_path: Path):
    data = user_profiles.list_profiles(tmp_path)
    assert data["active"] == user_profiles.DEFAULT_PROFILE_ID
    assert any(p["id"] == user_profiles.DEFAULT_PROFILE_ID for p in data["profiles"])


def test_create_and_activate(tmp_path: Path):
    res = user_profiles.create_profile(tmp_path, "Privat")
    assert res["ok"] is True
    pid = res["profile"]["id"]
    assert pid != user_profiles.DEFAULT_PROFILE_ID
    act = user_profiles.activate_profile(tmp_path, pid)
    assert act["ok"] is True
    assert user_profiles.get_active_id(tmp_path) == pid
    assert user_profiles.active_scope(tmp_path) == f"profile_{pid}"


def test_create_rejects_empty_label(tmp_path: Path):
    res = user_profiles.create_profile(tmp_path, "   ")
    assert res["ok"] is False


def test_create_rejects_long_label(tmp_path: Path):
    res = user_profiles.create_profile(tmp_path, "x" * 100)
    assert res["ok"] is False


def test_create_max_profiles(tmp_path: Path):
    # Default profile already exists
    for i in range(user_profiles.MAX_PROFILES - 1):
        assert user_profiles.create_profile(tmp_path, f"P{i}")["ok"] is True
    res = user_profiles.create_profile(tmp_path, "Overflow")
    assert res["ok"] is False


def test_create_dedup_id(tmp_path: Path):
    a = user_profiles.create_profile(tmp_path, "Privat")["profile"]["id"]
    b = user_profiles.create_profile(tmp_path, "Privat")["profile"]["id"]
    assert a != b


def test_rename_profile(tmp_path: Path):
    res = user_profiles.create_profile(tmp_path, "Alt")
    pid = res["profile"]["id"]
    rn = user_profiles.rename_profile(tmp_path, pid, "Neu")
    assert rn["ok"] is True
    data = user_profiles.list_profiles(tmp_path)
    found = next(p for p in data["profiles"] if p["id"] == pid)
    assert found["label"] == "Neu"


def test_delete_profile_cleans_scope(tmp_path: Path):
    pid = user_profiles.create_profile(tmp_path, "Tmp")["profile"]["id"]
    scope_dir = tmp_path / "users" / user_profiles.scope_for(pid)
    scope_dir.mkdir(parents=True, exist_ok=True)
    (scope_dir / "prefs.json").write_text("{}", encoding="utf-8")
    res = user_profiles.delete_profile(tmp_path, pid)
    assert res["ok"] is True
    assert not scope_dir.exists()


def test_delete_last_profile_blocked(tmp_path: Path):
    res = user_profiles.delete_profile(tmp_path, user_profiles.DEFAULT_PROFILE_ID)
    assert res["ok"] is False


def test_delete_active_promotes_first(tmp_path: Path):
    pid = user_profiles.create_profile(tmp_path, "Andere")["profile"]["id"]
    user_profiles.activate_profile(tmp_path, pid)
    res = user_profiles.delete_profile(tmp_path, pid)
    assert res["ok"] is True
    assert res["active"] == user_profiles.DEFAULT_PROFILE_ID


def test_corrupt_registry_falls_back(tmp_path: Path):
    (tmp_path / "profiles.json").write_text("not json", encoding="utf-8")
    data = user_profiles.list_profiles(tmp_path)
    assert data["active"] == user_profiles.DEFAULT_PROFILE_ID


def test_registry_persists(tmp_path: Path):
    user_profiles.create_profile(tmp_path, "Persist")
    raw = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert any(p["label"] == "Persist" for p in raw["profiles"])


# --- Routen-GET (ohne CSRF) ---

import app.app as app_module  # noqa: E402
import desktop_routes  # noqa: E402


def test_profiles_endpoint_lists(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    cli = app_module.app.test_client()
    r = cli.get("/api/desktop/profiles")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["active"] == user_profiles.DEFAULT_PROFILE_ID
    assert body["max"] == user_profiles.MAX_PROFILES


def test_user_scope_uses_active_profile(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(desktop_routes._config, "DATA_DIR", tmp_path)
    pid = user_profiles.create_profile(tmp_path, "Scope")["profile"]["id"]
    user_profiles.activate_profile(tmp_path, pid)
    with app_module.app.test_request_context("/"):
        assert desktop_routes._user_scope() == f"profile_{pid}"


# --- Markup ---

def test_index_has_profile_switcher():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="profile-switcher"' in html
    assert 'id="profile-menu"' in html
    assert "Welle 10: Multi-User" in html


def test_style_has_welle10_block():
    css = (REPO / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert "Welle 10: Profile-Switcher" in css
    assert ".profile-menu" in css
