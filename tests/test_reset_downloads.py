from __future__ import annotations

import os
from pathlib import Path

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"

import app.app as app_module


def test_reset_downloads_clears_visible_pdf_artifacts_and_runtime_state(monkeypatch, tmp_path: Path):
    user_tmp = tmp_path / "tmp"
    user_out = tmp_path / "fertig"
    user_quarantine = tmp_path / "quarantaene"
    user_autosort = tmp_path / "autosort"
    nested_autosort = user_autosort / "Supplier" / "2026-04"

    for folder in (user_tmp, user_out, user_quarantine, nested_autosort):
        folder.mkdir(parents=True, exist_ok=True)

    out_pdf = user_out / "download.pdf"
    quarantine_pdf = user_quarantine / "review.pdf"
    autosort_pdf = nested_autosort / "sorted.pdf"
    mapped_pdf = user_out / "mapped.pdf"
    for pdf in (out_pdf, quarantine_pdf, autosort_pdf, mapped_pdf):
        pdf.write_bytes(b"%PDF-1.4\n%test")

    results_path = user_tmp / "last_results.json"
    results_path.write_text("[]", encoding="utf-8")
    processing_flag = user_tmp / "processing.flag"
    processing_flag.write_text("1", encoding="utf-8")
    progress_path = user_tmp / "progress.json"
    progress_path.write_text("{}", encoding="utf-8")

    removed: dict[str, bool] = {"session_files": False}

    monkeypatch.setattr(app_module, "_check_processing_timeout", lambda: None)
    monkeypatch.setattr(app_module, "_current_user_scope", lambda user_scope="": "system")
    monkeypatch.setattr(app_module, "_user_tmp_dir", lambda user_scope="": user_tmp)
    monkeypatch.setattr(app_module, "_user_out_dir", lambda user_scope="": user_out)
    monkeypatch.setattr(app_module, "_user_quarantine_dir", lambda user_scope="": user_quarantine)
    monkeypatch.setattr(app_module, "_user_autosort_dir", lambda user_scope="": user_autosort)
    monkeypatch.setattr(
        app_module,
        "_get_session_file_map",
        lambda: {"mapped": {"path": str(mapped_pdf), "filename": mapped_pdf.name}},
    )
    monkeypatch.setattr(
        app_module,
        "_remove_session_files",
        lambda: removed.__setitem__("session_files", True),
    )

    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["csrf_token"] = "test-csrf"
        session["sid"] = "test-sid"

    response = client.post(
        "/reset",
        data={"csrf_token": "test-csrf"},
        headers={"Referer": "http://localhost/"},
    )

    assert response.status_code == 302
    assert response.headers.get("Location") == "/?reset=1"
    assert removed["session_files"] is True
    assert not out_pdf.exists()
    assert not quarantine_pdf.exists()
    assert not autosort_pdf.exists()
    assert not mapped_pdf.exists()
    assert not results_path.exists()
    assert not processing_flag.exists()
    assert not progress_path.exists()