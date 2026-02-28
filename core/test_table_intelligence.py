import unittest
from pathlib import Path
from unittest.mock import patch

from core.table_intelligence import extract_table_intelligence


class _FakePage:
    def __init__(self, tables):
        self._tables = tables

    def extract_tables(self):
        return self._tables


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TableIntelligenceTests(unittest.TestCase):
    def test_extract_local_tables_returns_preview_and_text(self):
        fake_pages = [
            _FakePage(
                [
                    [
                        ["Pos", "Artikel", "Menge"],
                        ["1", "Bolzen", "4"],
                        ["2", "Mutter", "8"],
                    ]
                ]
            )
        ]

        with patch("pdfplumber.open", return_value=_FakePdf(fake_pages)):
            summary = extract_table_intelligence(Path("dummy.pdf"), enabled=True, max_pages=1)

        self.assertEqual(summary.source, "pdfplumber")
        self.assertEqual(summary.tables_count, 1)
        self.assertEqual(summary.rows_count, 3)
        self.assertTrue(summary.preview)
        self.assertIn("Bolzen", summary.text)

    def test_disabled_returns_disabled_summary(self):
        summary = extract_table_intelligence(Path("dummy.pdf"), enabled=False, max_pages=1)
        self.assertEqual(summary.source, "disabled")
        self.assertEqual(summary.rows_count, 0)
        self.assertEqual(summary.error, "disabled")


if __name__ == "__main__":
    unittest.main()
