from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Callable, Optional

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from services.auth_store import ensure_seed_user, get_user_by_id, init_auth_db, verify_password


def _wants_json() -> bool:
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept


def install_auth(
    app: Flask,
    auth_db_path: Path,
    seed_email: Optional[str] = None,
    seed_password: Optional[str] = None,
) -> None:
    init_auth_db(auth_db_path)

    if seed_email and seed_password:
        ensure_seed_user(auth_db_path, seed_email, seed_password)

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/login")
    def login_page():
        if session.get("user_id"):
            return redirect(url_for("index"))
        return render_template("login.html")

    @app.post("/login")
    def login_submit():
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = verify_password(auth_db_path, email, password)
        if not user:
            if _wants_json():
                return jsonify({"ok": False, "error": "invalid_credentials"}), 401
            return render_template("login.html", error="Ungültige Login-Daten."), 401
        session["user_id"] = user.id
        session["user_email"] = user.email
        session["user_role"] = user.role or "user"
        return redirect(url_for("index"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login_page"))

    public_endpoints = {"login_page", "login_submit", "health", "metrics_endpoint", "static"}

    @app.before_request
    def _require_auth():
        endpoint = request.endpoint or ""
        if not endpoint:
            return None
        if endpoint.startswith("static"):
            return None
        if endpoint in public_endpoints:
            return None
        user_id = session.get("user_id")
        if not user_id:
            if _wants_json():
                return jsonify({"ok": False, "error": "auth_required"}), 401
            return redirect(url_for("login_page"))
        user = get_user_by_id(auth_db_path, int(user_id))
        if not user:
            session.clear()
            if _wants_json():
                return jsonify({"ok": False, "error": "auth_required"}), 401
            return redirect(url_for("login_page"))
        session["user_role"] = user.role or "user"
        return None


def login_required(fn: Callable):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            if _wants_json():
                return jsonify({"ok": False, "error": "auth_required"}), 401
            return redirect(url_for("login_page"))
        return fn(*args, **kwargs)

    return wrapper
