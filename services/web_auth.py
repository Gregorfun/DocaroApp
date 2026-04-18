from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Callable, Optional
import os
import re

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from services.auth_store import create_user, ensure_seed_user, get_user_by_email, init_auth_db, verify_password


def _wants_json() -> bool:
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept


_EMAIL_BASIC_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _validate_registration(email: str, password: str, password_confirm: str) -> Optional[str]:
    email_norm = (email or "").strip().lower()
    if not email_norm:
        return "E-Mail fehlt."
    if len(email_norm) > 254 or not _EMAIL_BASIC_RE.match(email_norm):
        return "Ungültige E-Mail."
    if not password:
        return "Passwort fehlt."
    if len(password) < 8:
        return "Passwort muss mindestens 8 Zeichen haben."
    if password != (password_confirm or ""):
        return "Passwörter stimmen nicht überein."
    return None


def install_auth(
    app: Flask,
    auth_db_path: Path,
    seed_email: Optional[str] = None,
    seed_password: Optional[str] = None,
) -> None:
    init_auth_db(auth_db_path)

    if seed_email and seed_password:
        ensure_seed_user(auth_db_path, seed_email, seed_password)

    auth_required = _env_flag("DOCARO_AUTH_REQUIRED", True)
    allow_self_register = _env_flag("DOCARO_ALLOW_SELF_REGISTER", False)
    public_metrics = _env_flag("DOCARO_METRICS_PUBLIC", False)
    public_health = _env_flag("DOCARO_HEALTH_PUBLIC", True)
    metrics_token = (os.getenv("DOCARO_METRICS_TOKEN") or "").strip()

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/login")
    def login_page():
        if session.get("user_id"):
            return redirect(url_for("index"))
        return render_template("login.html", allow_self_register=allow_self_register)

    @app.post("/login")
    def login_submit():
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = verify_password(auth_db_path, email, password)
        if not user:
            if _wants_json():
                return jsonify({"ok": False, "error": "invalid_credentials"}), 401
            return (
                render_template("login.html", error="Ungültige Login-Daten.", allow_self_register=allow_self_register),
                401,
            )
        session.clear()
        session.permanent = True
        session["user_id"] = user.id
        session["user_email"] = user.email
        session["user_role"] = user.role or "user"
        return redirect(url_for("index"))

    @app.get("/register")
    def register_page():
        if not allow_self_register:
            return redirect(url_for("login_page"))
        if session.get("user_id"):
            return redirect(url_for("index"))
        return render_template("register.html")

    @app.post("/register")
    def register_submit():
        if not allow_self_register:
            if _wants_json():
                return jsonify({"ok": False, "error": "registration_disabled"}), 403
            return (
                render_template(
                    "login.html", error="Registrierung ist deaktiviert.", allow_self_register=allow_self_register
                ),
                403,
            )

        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        password_confirm = request.form.get("password_confirm") or ""
        error_msg = _validate_registration(email, password, password_confirm)
        if error_msg:
            if _wants_json():
                return jsonify({"ok": False, "error": "invalid_registration", "message": error_msg}), 400
            return render_template("register.html", error=error_msg, email=email), 400

        existing = get_user_by_email(auth_db_path, email)
        if existing:
            if _wants_json():
                return jsonify({"ok": False, "error": "email_exists"}), 409
            return render_template("register.html", error="E-Mail ist bereits registriert.", email=email), 409

        try:
            user = create_user(auth_db_path, email, password)
        except Exception:
            if _wants_json():
                return jsonify({"ok": False, "error": "registration_failed"}), 500
            return render_template("register.html", error="Registrierung fehlgeschlagen.", email=email), 500

        session.clear()
        session.permanent = True
        session["user_id"] = user.id
        session["user_email"] = user.email
        session["user_role"] = user.role or "user"
        return redirect(url_for("index"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login_page"))

    public_endpoints = {
        "login_page",
        "login_submit",
        "register_page",
        "register_submit",
        "static",
    }

    if public_health:
        public_endpoints.add("health")
    if public_metrics or metrics_token:
        public_endpoints.add("metrics_endpoint")

    @app.before_request
    def _require_auth():
        if not auth_required:
            return None
        endpoint = request.endpoint or ""
        if endpoint in public_endpoints:
            return None
        if session.get("user_id"):
            return None
        if _wants_json():
            return jsonify({"ok": False, "error": "auth_required"}), 401
        return redirect(url_for("login_page"))


def login_required(fn: Callable):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            if _wants_json():
                return jsonify({"ok": False, "error": "auth_required"}), 401
            return redirect(url_for("login_page"))
        return fn(*args, **kwargs)

    return wrapper
