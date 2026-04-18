from __future__ import annotations

import os
from pathlib import Path

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"

import app.app as app_module
import pdf_toolkit_routes as toolkit_routes


def test_pdf_toolkit_download_survives_empty_in_memory_store(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(toolkit_routes, "_tmp_dir", lambda: tmp_path)
    toolkit_routes._result_store.clear()

    with app_module.app.test_request_context("/pdf-toolkit/"):
        token, _ = toolkit_routes._save_result(b"%PDF-1.4\n%toolkit", "toolkit_result.pdf")

    toolkit_routes._result_store.clear()

    client = app_module.app.test_client()
    response = client.get(f"/pdf-toolkit/download/{token}")

    assert response.status_code == 200
    assert response.data == b"%PDF-1.4\n%toolkit"
    assert "attachment;" in (response.headers.get("Content-Disposition") or "")
    assert "toolkit_result.pdf" in (response.headers.get("Content-Disposition") or "")