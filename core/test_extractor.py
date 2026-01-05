import unittest
from datetime import datetime

from core.extractor import extract_date, extract_date_with_priority, detect_supplier


class TestExtractorDates(unittest.TestCase):
    def test_extract_date_dd_mm_yy(self):
        dt = extract_date("Beleg-Datum 04.11.25")
        self.assertEqual(dt, datetime(2025, 11, 4))

    def test_extract_date_dd_mmm_yyyy(self):
        dt = extract_date("TADANO 20-NOV-2025")
        self.assertEqual(dt, datetime(2025, 11, 20))

    def test_extract_date_priority_liefertermin(self):
        text = "Auftragsdatum 01.01.2020\nLiefertermin 04.11.2025"
        dt, source = extract_date_with_priority(text)
        self.assertEqual(dt, datetime(2025, 11, 4))
        self.assertEqual(source, "lieferdatum")

    def test_detect_supplier_vergoelst_alias(self):
        supplier, confidence, source, alias = detect_supplier("Verglst Reifen- und Autoservice")
        self.assertEqual(supplier, "Vergoelst")
        self.assertTrue(confidence > 0.0)
        self.assertIn(source, ("keywords", "db"))
        self.assertTrue(alias)


if __name__ == "__main__":
    unittest.main()
