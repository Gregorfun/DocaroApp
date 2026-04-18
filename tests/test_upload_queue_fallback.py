from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"

import app.app as app_module


class _DummyRuntimeStore:
    def get_document_fingerprint(self, file_hash: str, owner_scope: str = ""):
        return None

    def register_document_fingerprint(self, *args, **kwargs) -> None:
        return None


def test_upload_falls_back_to_inline_processing_when_queue_is_unavailable(monkeypatch, tmp_path: Path):
    user_tmp = tmp_path / "tmp"
    user_out = tmp_path / "out"
    user_tmp.mkdir(parents=True, exist_ok=True)
    user_out.mkdir(parents=True, exist_ok=True)

    calls: dict[str, object] = {"bg": 0, "progress": []}

    monkeypatch.setattr(app_module, "_runtime_store", _DummyRuntimeStore())
    monkeypatch.setattr(app_module, "_check_processing_timeout", lambda: None)
    monkeypatch.setattr(app_module, "_current_user_scope", lambda user_scope="": "")
    monkeypatch.setattr(app_module, "_user_tmp_dir", lambda user_scope="": user_tmp)
    monkeypatch.setattr(app_module, "_user_out_dir", lambda user_scope="": user_out)
    monkeypatch.setattr(
        app_module,
        "_set_progress",
        lambda total, done, current_file, job_id="", user_scope="": calls["progress"].append(
            (total, done, current_file, job_id)
        ),
    )
    monkeypatch.setattr(app_module, "_set_processing", lambda value, user_scope="": None)
    monkeypatch.setattr(app_module, "_enqueue_job_safe", lambda *args, **kwargs: (None, "redis offline"))
    monkeypatch.setattr(
        app_module,
        "background_process_upload",
        lambda upload_dir, date_fmt, user_scope="": calls.__setitem__("bg", int(calls["bg"]) + 1),
    )
    monkeypatch.setattr(app_module, "count_step_error", lambda *args, **kwargs: None)

    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["csrf_token"] = "test-csrf"
        session["sid"] = "test-sid"

    response = client.post(
        "/upload",
        data={
            "csrf_token": "test-csrf",
            "date_fmt": "%d.%m.%Y",
            "files": (BytesIO(b"%PDF-1.4\n%test"), "sample.pdf"),
        },
        content_type="multipart/form-data",
        headers={"Referer": "http://localhost/upload"},
    )

    assert response.status_code == 302
    assert response.headers.get("Location") == "/"
    assert calls["bg"] == 1
    assert calls["progress"] == [(1, 0, "", "")]