import tempfile
import unittest
from pathlib import Path

from core.runtime_store import RuntimeStore


class RuntimeStoreMultiTenantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "runtime_state.db"
        self.store = RuntimeStore(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_owned_document_isolation(self):
        self.store.register_owned_document(
            "file_a",
            owner_scope="user_1",
            path="/tmp/u1/file.pdf",
            filename="file.pdf",
        )
        self.assertIsNotNone(self.store.get_owned_document("file_a", owner_scope="user_1"))
        self.assertIsNone(self.store.get_owned_document("file_a", owner_scope="user_2"))

    def test_fingerprint_isolation_by_owner_scope(self):
        sha = "ab" * 32
        self.store.register_document_fingerprint(
            sha,
            original_name="doc.pdf",
            path="/tmp/u1/doc.pdf",
            file_id="f1",
            owner_scope="user_1",
        )
        self.store.register_document_fingerprint(
            sha,
            original_name="doc.pdf",
            path="/tmp/u2/doc.pdf",
            file_id="f2",
            owner_scope="user_2",
        )
        fp1 = self.store.get_document_fingerprint(sha, owner_scope="user_1")
        fp2 = self.store.get_document_fingerprint(sha, owner_scope="user_2")
        self.assertIsNotNone(fp1)
        self.assertIsNotNone(fp2)
        self.assertEqual(fp1["owner_scope"], "user_1")
        self.assertEqual(fp2["owner_scope"], "user_2")
        self.assertNotEqual(fp1["last_file_id"], fp2["last_file_id"])


if __name__ == "__main__":
    unittest.main()
