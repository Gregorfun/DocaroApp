from __future__ import annotations

import argparse
import os
from getpass import getpass
from pathlib import Path

from config import Config
from services.auth_store import create_user, init_auth_db, set_user_password, set_user_role


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a Docaro user (registration is disabled).")
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="If user exists, overwrite the password.",
    )
    parser.add_argument(
        "--password-env",
        default="DOCARO_SEED_PASSWORD",
        help="Environment variable name that contains the password",
    )
    parser.add_argument(
        "--role",
        default="user",
        choices=("user", "admin"),
        help="User role to set",
    )
    args = parser.parse_args()

    password = os.getenv(args.password_env)
    if not password:
        password = getpass(f"Passwort (ENV {args.password_env} nicht gesetzt): ")

    cfg = Config()
    db_path: Path = cfg.AUTH_DB_PATH

    init_auth_db(db_path)
    if args.reset_password:
        updated = set_user_password(db_path, args.email, password)
        user = updated or create_user(db_path, args.email, password, role=args.role)
    else:
        user = create_user(db_path, args.email, password, role=args.role)
    if user.role != args.role:
        user = set_user_role(db_path, args.email, args.role) or user
    print(f"OK seeded user: {user.email} (id={user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
