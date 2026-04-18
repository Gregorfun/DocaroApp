"""Tests fuer Welle 2: User-Prefs, Quarantaene-Release."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

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
    headers = {"Origin": "http://localhost", "Referer": "http://localhost/"}
    if token:
        headers["X-CSRF-Token"] = token
    return headers


def test_user_prefs_module_records_supplier(tmp_path):
    from core import user_prefs
    user_prefs.record_supplier_use(tmp_path, "scope", "ACME GmbH", doctype="RECHNUNG")
    user_prefs.record_supplier_use(tmp_path, "scope", "ACME GmbH")
    user_prefs.record_supplier_use(tmp_path, "scope", "Beta AG")
    prefs = user_prefs.load_prefs(tmp_path, "scope")
    assert prefs["recent_suppliers"][:2] == ["ACME GmbH", "Beta AG"]
    assert prefs["doctype_per_supplier"]["ACME GmbH"] == "RECHNUNG"
    assert prefs["last_doctype"] == "RECHNUNG"


def test_user_prefs_module_validates_date_fmt(tmp_path):
    from core import user_prefs
    user_prefs.update_prefs(tmp_path, "scope", last_date_fmt="%Y-%m-%d")
    user_prefs.update_prefs(tmp_path, "scope", last_date_fmt="evil")
    prefs = user_prefs.load_prefs(tmp_path, "scope")
    assert prefs["last_date_fmt"] == "%Y-%m-%d"


def test_user_prefs_caps_recent_suppliers(tmp_path):
    from core import user_prefs
    for i in range(user_prefs.MAX_RECENT_SUPPLIERS + 5):
        user_prefs.record_supplier_use(tmp_path, "scope", f"Sup{i}")
    prefs = user_prefs.load_prefs(tmp_path, "scope")
    assert len(prefs["recent_suppliers"]) == user_prefs.MAX_RECENT_SUPPLIERS


def test_prefs_endpoint_get_returns_defaults():
    client = app_module.app.test_client()
    res = client.get("/api/desktop/prefs")
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["prefs"]["last_date_fmt"]
    assert isinstance(payload["prefs"]["recent_suppliers"], list)


def test_prefs_endpoint_post_persists_date_fmt():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    res = client.post("/api/desktop/prefs", data=json.dumps({"last_date_fmt": "%Y-%m-%d"}), content_type="application/json", headers=headers)
    assert res.status_code == 200, res.get_data(as_text=True)
    assert res.get_json()["prefs"]["last_date_fmt"] == "%Y-%m-%d"
    res2 = client.get("/api/desktop/prefs")
    assert res2.get_json()["prefs"]["last_date_fmt"] == "%Y-%m-%d"


def test_prefs_endpoint_rejects_unknown_fields():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    res = client.post("/api/desktop/prefs", data=json.dumps({"random": "noop"}), content_type="application/json", headers=headers)
    assert res.status_code == 400


def _seed_quarantined_doc():
    user_scope = "system"
    quarantine_dir = app_module._user_quarantine_dir(user_scope)
    pdf_path = quarantine_dir / f"test_quar_{uuid.uuid4().hex[:8]}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")
    file_id = uuid.uuid4().hex
    item = {"file_id": file_id, "out_name": pdf_path.name, "supplier": "Beispiel GmbH", "supplier_confidence": "0.45", "date": "2026-04-18", "date_confidence": "0.50", "doc_type": "RECHNUNG", "doc_type_confidence": "0.40", "quarantined": "1", "quarantine_reason": "low_supplier_confidence"}
    app_module._save_last_results([item], user_scope=user_scope)
    return file_id, pdf_path


def test_quarantine_page_lists_items():
    client = app_module.app.test_client()
    file_id, pdf_path = _seed_quarantined_doc()
    res = client.get("/quarantine")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert pdf_path.name in body
    assert "Trotzdem freigeben" in body
    assert file_id in body


def test_quarantine_release_moves_pdf_and_clears_flag():
    client = app_module.app.test_client()
    file_id, pdf_path = _seed_quarantined_doc()
    headers = _csrf_headers(client)
    headers["X-Requested-With"] = "fetch"
    headers["Accept"] = "application/json"
    res = client.post("/quarantine/release", data={"file_id": file_id, "csrf_token": headers.get("X-CSRF-Token", "")}, headers=headers)
    assert res.status_code == 200, res.get_data(as_text=True)
    payload = res.get_json()
    assert payload["ok"] is True
    out_dir = app_module._user_out_dir("system")
    moved = out_dir / pdf_path.name
    assert moved.exists(), f"Nicht in {out_dir}: {list(out_dir.iterdir())}"
    assert not pdf_path.exists()
    results = app_module._load_last_results(user_scope="system") or []
    target = next((r for r in results if r.get("file_id") == file_id), None)
    assert target is not None and target["quarantined"] == ""


def test_quarantine_release_requires_file_id():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    headers["X-Requested-With"] = "fetch"
    headers["Accept"] = "application/json"
    res = client.post("/quarantine/release", data={"csrf_token": headers.get("X-CSRF-Token", "")}, headers=headers)
    assert res.status_code == 400


def test_quarantine_release_unknown_file_id_returns_404():
    client = app_module.app.test_client()
    headers = _csrf_headers(client)
    headers["X-Requested-With"] = "fetch"
    headers["Accept"] = "application/json"
    res = client.post("/quarantine/release", data={"file_id": "nope_does_not_exist", "csrf_token": headers.get("X-CSRF-Token", "")}, headers=headers)
    assert res.status_code == 404
