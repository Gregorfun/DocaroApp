"""Tests fuer Welle 3: Bulk-Aktionen."""

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
        "Content-Type": "application/json",
    }
    if token:
        headers["X-CSRF-Token"] = token
    return headers


def _seed_results(items):
    app_module._save_last_results(items)


def test_bulk_action_rejects_unknown_action():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    res = client.post("/bulk_action", data=json.dumps({"action": "evil", "file_ids": ["a"]}), headers=headers)
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_bulk_action_rejects_empty_ids():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    res = client.post("/bulk_action", data=json.dumps({"action": "set_status", "file_ids": [], "value": "fertig"}), headers=headers)
    assert res.status_code == 400


def test_bulk_set_status_updates_items():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    _seed_results([
        {"file_id": "f1", "out_name": "a.pdf", "supplier": "ACME", "needs_review": ""},
        {"file_id": "f2", "out_name": "b.pdf", "supplier": "Beta", "needs_review": ""},
        {"file_id": "f3", "out_name": "c.pdf", "supplier": "Gamma", "needs_review": ""},
    ])
    res = client.post(
        "/bulk_action",
        data=json.dumps({"action": "set_status", "file_ids": ["f1", "f2", "missing"], "value": "in_bearbeitung"}),
        headers=headers,
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    body = res.get_json()
    assert body["ok"] is True
    assert sorted(body["processed"]) == ["f1", "f2"]
    assert body["skipped"] == ["missing"]
    after = {r["file_id"]: r for r in app_module._load_last_results() or []}
    assert after["f1"]["needs_review"] == "1"
    assert after["f2"]["needs_review"] == "1"
    assert after["f3"].get("needs_review", "") == ""


def test_bulk_set_doc_type_validates_value():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    _seed_results([{"file_id": "x1", "out_name": "x.pdf"}])
    res = client.post(
        "/bulk_action",
        data=json.dumps({"action": "set_doc_type", "file_ids": ["x1"], "value": "BOGUS"}),
        headers=headers,
    )
    assert res.status_code == 400


def test_bulk_set_doc_type_applies():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    _seed_results([
        {"file_id": "y1", "out_name": "y.pdf", "supplier": "S"},
        {"file_id": "y2", "out_name": "y2.pdf", "supplier": "S"},
    ])
    res = client.post(
        "/bulk_action",
        data=json.dumps({"action": "set_doc_type", "file_ids": ["y1", "y2"], "value": "RECHNUNG"}),
        headers=headers,
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert sorted(body["processed"]) == ["y1", "y2"]
    after = {r["file_id"]: r for r in app_module._load_last_results() or []}
    assert after["y1"]["doc_type"] == "RECHNUNG"
    assert after["y2"]["doc_type"] == "RECHNUNG"


def test_bulk_delete_skips_unknown_and_keeps_others():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    _seed_results([
        {"file_id": "z1", "out_name": "z1.pdf"},
        {"file_id": "z2", "out_name": "z2.pdf"},
    ])
    # z1 hat keinen physischen Pfad -> Loeschung tut nichts auf Disk, aber Item bleibt entfernt
    res = client.post(
        "/bulk_action",
        data=json.dumps({"action": "delete", "file_ids": ["z1", "missing"]}),
        headers=headers,
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert "z1" in body["processed"]
    assert "missing" in body["skipped"]
    remaining_ids = {r.get("file_id") for r in app_module._load_last_results() or []}
    assert "z1" not in remaining_ids
    assert "z2" in remaining_ids
