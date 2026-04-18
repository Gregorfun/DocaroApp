"""Tests fuer Welle 4: CSV-Export & Stats-Summary."""

from __future__ import annotations

import os

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"
os.environ["DOCARO_DESKTOP_MODE"] = "1"

import app.app as app_module  # noqa: E402


def _seed(items):
    app_module._save_last_results(items)


def test_results_csv_returns_utf8_bom_and_header():
    client = app_module.app.test_client()
    _seed([
        {"file_id": "a1", "out_name": "a.pdf", "supplier": "ACME", "doc_type": "RECHNUNG"},
        {"file_id": "a2", "out_name": "b.pdf", "supplier": "Beta", "doc_type": "LIEFERSCHEIN"},
    ])
    res = client.get("/api/results.csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["Content-Type"]
    assert "attachment" in res.headers.get("Content-Disposition", "")
    body = res.get_data()
    assert body[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM
    text = body.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0].startswith("FileID;Datei;Lieferant")
    assert any("a1;a.pdf;ACME" in line for line in lines)
    assert any("a2;b.pdf;Beta" in line for line in lines)


def test_results_csv_filters_by_file_ids():
    client = app_module.app.test_client()
    _seed([
        {"file_id": "k1", "out_name": "x.pdf", "supplier": "X"},
        {"file_id": "k2", "out_name": "y.pdf", "supplier": "Y"},
        {"file_id": "k3", "out_name": "z.pdf", "supplier": "Z"},
    ])
    res = client.get("/api/results.csv?file_ids=k1,k3")
    assert res.status_code == 200
    text = res.get_data().decode("utf-8-sig")
    assert "x.pdf" in text
    assert "z.pdf" in text
    assert "y.pdf" not in text


def test_results_summary_counts_and_groups():
    client = app_module.app.test_client()
    _seed([
        {"file_id": "s1", "supplier": "ACME", "doc_type": "RECHNUNG", "needs_review": "1"},
        {"file_id": "s2", "supplier": "ACME", "doc_type": "RECHNUNG"},
        {"file_id": "s3", "supplier": "Beta", "doc_type": "LIEFERSCHEIN", "supplier_missing": "1", "date_missing": "1"},
        {"file_id": "s4", "supplier": "", "doc_type": "", "quarantined": "1"},
    ])
    res = client.get("/api/results_summary")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["total"] == 4
    assert data["incomplete"] == 1
    assert data["in_review"] == 1
    assert data["quarantined"] == 1
    assert data["by_doctype"].get("RECHNUNG") == 2
    assert data["by_doctype"].get("LIEFERSCHEIN") == 1
    assert data["by_doctype"].get("SONSTIGES") == 1
    sup_names = [s["supplier"] for s in data["top_suppliers"]]
    assert sup_names[0] == "ACME"
    assert data["top_suppliers"][0]["count"] == 2
