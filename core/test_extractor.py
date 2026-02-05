import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

# Pfad für Imports setzen
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.extractor import (
    extract_date,
    extract_date_with_priority,
    detect_supplier,
    detect_supplier_detailed,
    normalize_text,
    load_suppliers_db,
    build_new_filename,
    INTERNAL_DATE_FORMAT,
)


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

    # Zusätzliche Tests für extract_date
    def test_extract_date_iso_format(self):
        dt = extract_date("Rechnung vom 2025-11-04")
        self.assertEqual(dt, datetime(2025, 11, 4))

    def test_extract_date_slash_format(self):
        dt = extract_date("Datum: 04/11/2025")
        self.assertEqual(dt, datetime(2025, 11, 4))

    def test_extract_date_invalid(self):
        dt = extract_date("Kein Datum hier")
        self.assertIsNone(dt)

    def test_extract_date_empty_text(self):
        dt = extract_date("")
        self.assertIsNone(dt)

    def test_extract_date_with_priority_no_date(self):
        dt, source = extract_date_with_priority("Kein Datum")
        self.assertIsNone(dt)
        self.assertEqual(source, "fallback")

    def test_extract_date_with_priority_multiple_dates(self):
        text = "Bestelldatum 01.01.2020\nLieferdatum 04.11.2025\nRechnungsdatum 05.12.2025"
        dt, source = extract_date_with_priority(text)
        self.assertEqual(dt, datetime(2025, 11, 4))
        self.assertEqual(source, "lieferdatum")


class TestSupplierDetection(unittest.TestCase):
    def test_detect_supplier_known_supplier(self):
        supplier, confidence, source, alias = detect_supplier("Rechnung von Firma ABC GmbH")
        # Annahme: ABC ist in suppliers.json – anpassen falls nötig
        self.assertIsNotNone(supplier)
        self.assertTrue(confidence > 0.0)

    def test_detect_supplier_unknown(self):
        supplier, confidence, source, alias = detect_supplier("Unbekannte Firma XYZ")
        self.assertEqual(supplier, "Unbekannt")
        self.assertEqual(confidence, 0.0)

    def test_detect_supplier_alias(self):
        # Test für Alias, falls vorhanden
        supplier, confidence, source, alias = detect_supplier("Verglst")
        if supplier:
            self.assertTrue(alias)

    def test_detect_supplier_case_insensitive(self):
        supplier1, _, _, _ = detect_supplier("vergoelst")
        supplier2, _, _, _ = detect_supplier("VERGOELST")
        self.assertEqual(supplier1, supplier2)

    def test_detect_supplier_ksr_from_befoerderer(self):
        text = """
        Lieferschein
        Kunde: Franz Bracht

        Beförderer: KS- Logistic GmbH & Co KG
        """
        supplier, confidence, source, matched, cands = detect_supplier_detailed(text)
        self.assertEqual(supplier, "KSR")
        self.assertTrue(confidence > 0.0)


class TestNormalizeText(unittest.TestCase):
    def test_normalize_text_basic(self):
        text = "Hallo\nWelt\tTest"
        normalized = normalize_text(text)
        self.assertEqual(normalized, "Hallo Welt Test")

    def test_normalize_text_empty(self):
        normalized = normalize_text("")
        self.assertEqual(normalized, "")

    def test_normalize_text_special_chars(self):
        text = "Café & Co. – 100%"
        normalized = normalize_text(text)
        # Erwartet: Entfernung von Sonderzeichen, aber behalten von Buchstaben
        self.assertIn("Café", normalized)
        self.assertNotIn("&", normalized)


class TestBuildNewFilename(unittest.TestCase):
    def test_build_new_filename_basic(self):
        filename = build_new_filename("Rechnung_001.pdf", datetime(2025, 11, 4), "ABC GmbH")
        self.assertIn("2025-11-04", filename)
        self.assertIn("ABC_GmbH", filename)
        self.assertTrue(filename.endswith(".pdf"))

    def test_build_new_filename_no_supplier(self):
        filename = build_new_filename("Test.pdf", datetime(2025, 11, 4), None)
        self.assertIn("2025-11-04", filename)
        self.assertTrue(filename.endswith(".pdf"))

    def test_build_new_filename_special_chars(self):
        filename = build_new_filename("Test.pdf", datetime(2025, 11, 4), "Firma & Co.")
        # Sollte Sonderzeichen behandeln
        self.assertTrue(filename.endswith(".pdf"))


class TestLoadSuppliersDB(unittest.TestCase):
    @patch('core.extractor.SUPPLIERS_DB_PATH')
    def test_load_suppliers_db(self, mock_path):
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = '{"suppliers": {"ABC": {"name": "ABC GmbH"}}}'
        db = load_suppliers_db()
        self.assertIn("ABC", db['suppliers'])

    @patch('core.extractor.SUPPLIERS_DB_PATH')
    def test_load_suppliers_db_missing_file(self, mock_path):
        mock_path.exists.return_value = False
        db = load_suppliers_db()
        self.assertEqual(db, {"suppliers": []})


if __name__ == "__main__":
    unittest.main()
