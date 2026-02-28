from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.auth_store import create_user, get_user_by_email, init_auth_db, set_user_role


class AuthStoreTests(unittest.TestCase):
    def test_create_user_sets_default_role(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.db"
            init_auth_db(db_path)
            user = create_user(db_path, "new.user@example.com", "verysecure123")
            self.assertEqual(user.role, "user")
            loaded = get_user_by_email(db_path, "new.user@example.com")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.role, "user")

    def test_create_user_with_admin_role(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.db"
            init_auth_db(db_path)
            user = create_user(db_path, "admin.user@example.com", "verysecure123", role="admin")
            self.assertEqual(user.role, "admin")
            loaded = get_user_by_email(db_path, "admin.user@example.com")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.role, "admin")

    def test_set_user_role_promotes_existing_user(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.db"
            init_auth_db(db_path)
            create_user(db_path, "promote.user@example.com", "verysecure123")
            updated = set_user_role(db_path, "promote.user@example.com", "admin")
            self.assertIsNotNone(updated)
            self.assertEqual(updated.role, "admin")


if __name__ == "__main__":
    unittest.main()
