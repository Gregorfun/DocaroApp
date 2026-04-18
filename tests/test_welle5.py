"""Tests fuer Welle 5: tour_done in User-Prefs."""

from __future__ import annotations

import json
import os

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"
os.environ["DOCARO_DESKTOP_MODE"] = "1"

import app.app as app_module  # noqa: E402


def _csrf_headers(client):
    client.get("/api/desktop/info")
    token = ""
    for cookie in client.cookie_jar if hasattr(client, "cookie_jar") else []:
        if cookie.name == "XSRF-TOKEN":
            token = cookie.value or ""
            break
    headers = {
        "Origin": "http://localhost",
        "Referer": "http://localhost/",
        "X-Requested-With": "fetch",
        "Accept": "application/json",
    }
    if token:
        headers["X-CSRF-Token"] = token
    return headers


def test_user_prefs_tour_done_default_false(tmp_path):
    from core import user_prefs
    prefs = user_prefs.load_prefs(tmp_path, "scope")
    assert prefs["tour_done"] is False


def test_user_prefs_update_tour_done(tmp_path):
    from core import user_prefs
    prefs = user_prefs.update_prefs(tmp_path, "scope", tour_done=True)
    assert prefs["tour_done"] is True
    prefs2 = user_prefs.load_prefs(tmp_path, "scope")
    assert prefs2["tour_done"] is True


def test_prefs_endpoint_get_includes_tour_done():
    client = app_module.app.test_client()
    res = client.get("/api/desktop/prefs")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "tour_done" in data["prefs"]
    assert isinstance(data["prefs"]["tour_done"], bool)


def test_prefs_endpoint_post_persists_tour_done():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    res = client.post(
        "/api/desktop/prefs",
        data=json.dumps({"tour_done": True}),
        content_type="application/json",
        headers=headers,
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    body = res.get_json()
    assert body["ok"] is True
    assert body["prefs"]["tour_done"] is True
    res2 = client.get("/api/desktop/prefs")
    assert res2.get_json()["prefs"]["tour_done"] is True


def test_index_has_help_button_and_overlay():
    client = app_module.app.test_client()
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'id="help-open-btn"' in html
    assert 'id="help-overlay"' in html
    assert 'id="tour-overlay"' in html
