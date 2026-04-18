from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"
os.environ["DOCARO_DESKTOP_MODE"] = "1"

import app.app as app_module
import desktop_routes
from core import recent_store


def _csrf_headers(client) -> dict[str, str]:
    """Holt CSRF-Token aus initialer GET-Antwort und baut Headers fuer POSTs."""
    client.get("/api/desktop/info")
    token = ""
    for cookie in client.cookie_jar if hasattr(client, "cookie_jar") else []:
        if cookie.name == "XSRF-TOKEN":
            token = cookie.value or ""
            break
    if not token:
        # Fallback: same-origin via Origin header
        return {"Origin": "http://localhost", "Referer": "http://localhost/"}
    return {"X-CSRF-Token": token}


def test_runtime_info_endpoint_reports_desktop_mode():
    client = app_module.app.test_client()
    resp = client.get("/api/desktop/info")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["desktop_mode"] is True
    assert payload["offline"] is True


def test_recent_store_roundtrip(tmp_path: Path):
    recent_store.add_recent(
        tmp_path,
        "user_test",
        kind="merge",
        filename="test.pdf",
        path=str(tmp_path / "test.pdf"),
        download_token="abc",
    )
    items = recent_store.load_recent(tmp_path, "user_test")
    assert len(items) == 1
    assert items[0]["kind"] == "merge"
    assert items[0]["filename"] == "test.pdf"
    assert items[0]["download_token"] == "abc"

    recent_store.clear_recent(tmp_path, "user_test")
    assert recent_store.load_recent(tmp_path, "user_test") == []


def test_recent_store_rejects_unknown_kind(tmp_path: Path):
    recent_store.add_recent(tmp_path, "user_x", kind="evil", filename="x.pdf")
    assert recent_store.load_recent(tmp_path, "user_x") == []


def test_recent_store_caps_entries(tmp_path: Path):
    for i in range(recent_store.MAX_ENTRIES + 5):
        recent_store.add_recent(tmp_path, "u", kind="ocr", filename=f"f{i}.pdf")
    items = recent_store.load_recent(tmp_path, "u")
    assert len(items) == recent_store.MAX_ENTRIES


def test_reveal_rejects_path_outside_data_dir(tmp_path: Path):
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    resp = client.post(
        "/api/desktop/reveal",
        data=json.dumps({"path": str(tmp_path / "evil.pdf")}),
        content_type="application/json",
        headers=headers,
    )
    assert resp.status_code in (403, 404)


def test_diagnostics_zip_returns_zip():
    client = app_module.app.test_client()
    resp = client.get("/api/desktop/diagnostics.zip")
    assert resp.status_code == 200
    assert resp.headers.get("Content-Type", "").startswith("application/zip")
    assert resp.data.startswith(b"PK")


def test_recent_endpoint_add_and_list():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    add = client.post(
        "/api/desktop/recent",
        data=json.dumps({
            "kind": "compress",
            "filename": "demo.pdf",
            "savings_pct": 42,
        }),
        content_type="application/json",
        headers=headers,
    )
    assert add.status_code == 200 and add.get_json()["ok"] is True

    listing = client.get("/api/desktop/recent")
    assert listing.status_code == 200
    items = listing.get_json()["items"]
    assert any(i["filename"] == "demo.pdf" and i["savings_pct"] == 42 for i in items)

    client.post("/api/desktop/recent/clear", headers=headers)


def test_runtime_info_in_web_mode(monkeypatch):
    monkeypatch.setattr(desktop_routes, "_is_desktop_mode", lambda: False)
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    resp = client.post(
        "/api/desktop/reveal",
        data=json.dumps({"path": "anything"}),
        content_type="application/json",
        headers=headers,
    )
    assert resp.status_code == 403
    resp2 = client.post(
        "/api/desktop/notify",
        data=json.dumps({"title": "x", "body": "y"}),
        content_type="application/json",
        headers=headers,
    )
    assert resp2.status_code == 403
