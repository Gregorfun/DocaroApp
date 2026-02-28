from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


@dataclass(frozen=True)
class User:
    id: int
    email: str
    password_hash: str
    role: str
    created_at: str


_ph = PasswordHasher()
_ALLOWED_ROLES = {"user", "admin"}


def _normalize_role(role: str) -> str:
    normalized = (role or "").strip().lower()
    return normalized if normalized in _ALLOWED_ROLES else "user"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            )
            """
        )
        try:
            cols = conn.execute("PRAGMA table_info(users)").fetchall()
            col_names = {str(row["name"]) for row in cols}
            if "role" not in col_names:
                conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        except Exception:
            pass
        conn.commit()


def get_user_by_email(db_path: Path, email: str) -> Optional[User]:
    email_norm = (email or "").strip().lower()
    if not email_norm:
        return None
    with _connect(db_path) as conn:
        try:
            row = conn.execute(
                "SELECT id, email, password_hash, role, created_at FROM users WHERE email = ?",
                (email_norm,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if not row:
            return None
        return User(
            int(row["id"]),
            str(row["email"]),
            str(row["password_hash"]),
            str(row["role"] or "user"),
            str(row["created_at"]),
        )


def get_user_by_id(db_path: Path, user_id: int) -> Optional[User]:
    with _connect(db_path) as conn:
        try:
            row = conn.execute(
                "SELECT id, email, password_hash, role, created_at FROM users WHERE id = ?",
                (int(user_id),),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if not row:
            return None
        return User(
            int(row["id"]),
            str(row["email"]),
            str(row["password_hash"]),
            str(row["role"] or "user"),
            str(row["created_at"]),
        )


def create_user(db_path: Path, email: str, password: str, role: str = "user") -> User:
    init_auth_db(db_path)
    email_norm = (email or "").strip().lower()
    if not email_norm:
        raise ValueError("email_missing")
    if not password:
        raise ValueError("password_missing")
    role_norm = _normalize_role(role)

    existing = get_user_by_email(db_path, email_norm)
    if existing:
        return existing

    password_hash = _ph.hash(password)
    created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO users(email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (email_norm, password_hash, role_norm, created_at),
        )
        conn.commit()
        user_id = int(cur.lastrowid)

    return User(user_id, email_norm, password_hash, role_norm, created_at)


def set_user_password(db_path: Path, email: str, password: str) -> Optional[User]:
    """Setzt das Passwort für einen bestehenden Benutzer.

    Gibt den aktualisierten User zurück, oder None, falls der User nicht existiert.
    """
    init_auth_db(db_path)
    email_norm = (email or "").strip().lower()
    if not email_norm:
        raise ValueError("email_missing")
    if not password:
        raise ValueError("password_missing")

    existing = get_user_by_email(db_path, email_norm)
    if not existing:
        return None

    password_hash = _ph.hash(password)
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE email = ?",
            (password_hash, email_norm),
        )
        conn.commit()
    return get_user_by_email(db_path, email_norm)


def set_user_role(db_path: Path, email: str, role: str) -> Optional[User]:
    """Setzt die Rolle für einen bestehenden Benutzer."""
    init_auth_db(db_path)
    email_norm = (email or "").strip().lower()
    if not email_norm:
        raise ValueError("email_missing")
    role_norm = _normalize_role(role)

    existing = get_user_by_email(db_path, email_norm)
    if not existing:
        return None

    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE users SET role = ? WHERE email = ?",
            (role_norm, email_norm),
        )
        conn.commit()
    return get_user_by_email(db_path, email_norm)


def verify_password(db_path: Path, email: str, password: str) -> Optional[User]:
    init_auth_db(db_path)
    user = get_user_by_email(db_path, email)
    if not user:
        return None
    try:
        if _ph.verify(user.password_hash, password or ""):
            return user
    except VerifyMismatchError:
        return None
    except Exception:
        return None
    return None


def ensure_seed_user(db_path: Path, email: str, password: str) -> Optional[User]:
    if not email or not password:
        return None
    init_auth_db(db_path)
    return create_user(db_path, email, password)
