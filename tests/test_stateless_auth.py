from __future__ import annotations

from pathlib import Path

from flask import Flask

from core.runtime_state import RuntimeStateConfig, reset_runtime_state
from services.auth_store import create_user
from services.web_auth import install_auth


def test_reset_runtime_state_clears_runtime_not_ml(tmp_path: Path):
    repo_root = tmp_path / "repo"
    data_dir = repo_root / "data"
    ml_dir = repo_root / "ml"
    auth_dir = data_dir / "auth"

    tmp_dir = data_dir / "tmp"
    inbox_dir = data_dir / "eingang"
    out_dir = data_dir / "fertig"
    quarantine_dir = data_dir / "quarantaene"
    log_dir = data_dir / "logs"

    # Create runtime files/dirs
    for d in (tmp_dir, inbox_dir, out_dir, quarantine_dir, log_dir, auth_dir, ml_dir / "models"):
        d.mkdir(parents=True, exist_ok=True)

    (tmp_dir / "last_results.json").write_text("x", encoding="utf-8")
    (out_dir / "doc.pdf").write_text("x", encoding="utf-8")
    (log_dir / "docaro.log").write_text("x", encoding="utf-8")

    # ML must persist
    ml_sentinel = ml_dir / "models" / "model.bin"
    ml_sentinel.write_text("ml", encoding="utf-8")

    cfg = RuntimeStateConfig(
        repo_root=repo_root,
        data_dir=data_dir,
        runtime_dirs=(tmp_dir, inbox_dir, out_dir, quarantine_dir),
        runtime_files=(data_dir / "settings.json",),
        log_dir=log_dir,
        preserve_dirs=(ml_dir, auth_dir),
    )
    reset_runtime_state(cfg)

    assert not (tmp_dir / "last_results.json").exists()
    assert not (out_dir / "doc.pdf").exists()
    assert not (log_dir / "docaro.log").exists()
    assert ml_sentinel.exists()


def test_auth_requires_login_and_allows_login(tmp_path: Path):
    db_path = tmp_path / "auth.db"
    import os

    previous_auth_required = os.environ.get("DOCARO_AUTH_REQUIRED")
    previous_allow_register = os.environ.get("DOCARO_ALLOW_SELF_REGISTER")
    os.environ["DOCARO_AUTH_REQUIRED"] = "1"
    os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"

    try:
        app = Flask(__name__)
        app.secret_key = "test"

        # Protected route
        @app.get("/")
        def index():
            return "ok"

        # Install auth (adds /login,/logout,/health and global guard)
        install_auth(app, db_path)

        # Seed a user
        create_user(db_path, "user@example.com", "pw")

        client = app.test_client()

        # Unauthenticated -> redirect to /login
        r = client.get("/")
        assert r.status_code in (301, 302)
        assert "/login" in (r.headers.get("Location") or "")

        # Login
        r2 = client.post("/login", data={"email": "user@example.com", "password": "pw"})
        assert r2.status_code in (301, 302)

        # Authenticated -> ok
        r3 = client.get("/")
        assert r3.status_code == 200
        assert r3.data == b"ok"
    finally:
        if previous_auth_required is None:
            os.environ.pop("DOCARO_AUTH_REQUIRED", None)
        else:
            os.environ["DOCARO_AUTH_REQUIRED"] = previous_auth_required
        if previous_allow_register is None:
            os.environ.pop("DOCARO_ALLOW_SELF_REGISTER", None)
        else:
            os.environ["DOCARO_ALLOW_SELF_REGISTER"] = previous_allow_register


def test_password_is_hashed(tmp_path: Path):
    db_path = tmp_path / "auth.db"
    user = create_user(db_path, "hash@example.com", "pw")
    assert user.password_hash != "pw"
    assert "pw" not in user.password_hash
