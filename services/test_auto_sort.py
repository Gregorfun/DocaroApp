import sys
import unittest
import tempfile
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.auto_sort import (
    AutoSortSettings,
    build_target_folder,
    build_target_filename,
    decide_auto_sort,
    export_document,
    make_unique_filename,
    sanitize_supplier_name,
    should_auto_sort,
)


class TestAutoSortHelpers(unittest.TestCase):
    def test_build_target_filename_omits_default_doc_type(self):
        date_obj = datetime(2025, 1, 4)
        name1 = build_target_filename("ACME", date_obj, "Dokument", "scan_001.pdf")
        self.assertNotIn("_Dokument_", name1)
        self.assertNotIn("_Dokument.", name1)

        name2 = build_target_filename("ACME", date_obj, "unknown", "scan_001.pdf")
        self.assertNotIn("_unknown_", name2.lower())

        name3 = build_target_filename("ACME", date_obj, "Lieferschein", "scan_001.pdf")
        self.assertIn("_Lieferschein_", name3)

    def test_sanitize_supplier_name(self):
        cleaned = sanitize_supplier_name("ACME: GmbH/ | Test?")
        self.assertEqual(cleaned, "ACME GmbH Test")

    def test_build_target_folder_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp) / "base"
            settings = AutoSortSettings(enabled=True, base_dir=base_dir, folder_format="A")
            date_obj = datetime(2025, 1, 4)
            folder_a = build_target_folder(settings, "ACME", date_obj)
            self.assertEqual(folder_a, base_dir / "ACME" / "2025-01")

            settings.folder_format = "B"
            folder_b = build_target_folder(settings, "ACME", date_obj)
            self.assertEqual(folder_b, base_dir / "ACME" / "Januar 2025")

            settings.folder_format = "C"
            folder_c = build_target_folder(settings, "ACME", date_obj)
            self.assertEqual(folder_c, base_dir / "ACME" / "2025-01_ACME")

    def test_make_unique_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp)
            first = target_dir / "file.pdf"
            first.write_text("demo", encoding="utf-8")
            unique = make_unique_filename(target_dir, "file.pdf")
            self.assertTrue(unique.name.startswith("file_01"))
            self.assertFalse(unique.exists())

    def test_should_auto_sort(self):
        settings = AutoSortSettings(enabled=True, base_dir=Path("."), confidence_threshold=0.8)
        ok, reason = should_auto_sort({"supplier": "ACME", "supplier_confidence": "0.9", "date": "2025-01-04", "document_type": "Lieferschein"}, settings)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

        low_conf, reason_low = should_auto_sort({"supplier": "ACME", "supplier_confidence": "0.5", "date": "2025-01-04"}, settings)
        self.assertFalse(low_conf)
        self.assertEqual(reason_low, "supplier_confidence_low")

        missing_date, reason_date = should_auto_sort({"supplier": "ACME", "supplier_confidence": "0.9"}, settings)
        self.assertFalse(missing_date)
        self.assertEqual(reason_date, "date_missing")

        wrong_type, reason_type = should_auto_sort({"supplier": "ACME", "supplier_confidence": "0.9", "date": "2025-01-04", "document_type": "Rechnung"}, settings)
        self.assertFalse(wrong_type)
        self.assertEqual(reason_type, "doctype_is_rechnung")

        # Dokumente ohne Typ oder mit Typ "Lieferschein" sollten sortiert werden
        no_type, reason_no = should_auto_sort({"supplier": "ACME", "supplier_confidence": "0.9", "date": "2025-01-04"}, settings)
        self.assertTrue(no_type)
        self.assertEqual(reason_no, "")

    def test_decide_auto_sort_reasons(self):
        settings = AutoSortSettings(enabled=True, base_dir=Path("."), confidence_threshold=0.8)

        d1 = decide_auto_sort({"supplier": "", "supplier_confidence": "0.9", "date": "2025-01-04"}, settings)
        self.assertFalse(d1.should_sort)
        self.assertEqual(d1.reason_code, "MISSING_SUPPLIER")

        d2 = decide_auto_sort({"supplier": "ACME", "supplier_confidence": "0.5", "date": "2025-01-04"}, settings)
        self.assertFalse(d2.should_sort)
        self.assertEqual(d2.reason_code, "SUPPLIER_CONF_LOW")

        d3 = decide_auto_sort({"supplier": "ACME", "supplier_confidence": "0.9", "date": ""}, settings)
        self.assertFalse(d3.should_sort)
        self.assertEqual(d3.reason_code, "MISSING_DATE")

    def test_export_document_sorted_and_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src = tmp_dir / "demo.pdf"
            src.write_text("demo", encoding="utf-8")
            settings = AutoSortSettings(enabled=True, base_dir=tmp_dir / "out", folder_format="A", mode="copy")
            result_meta = {"supplier": "ACME", "supplier_confidence": "0.9", "date": "2025-01-04", "document_type": "Lieferschein", "original": "uploadname.pdf"}
            export_res = export_document(src, result_meta, settings)
            self.assertEqual(export_res.status, "sorted")
            self.assertTrue(export_res.path and export_res.path.exists())

            # AutoSort benennt nicht um, nur verschieben/kopieren
            self.assertEqual(export_res.path.name, src.name)

            # Duplikat-Handling: wenn Ziel-Datei existiert, Suffix _01, _02, ...
            date_obj = datetime(2025, 1, 4)
            target_dir = build_target_folder(settings, "ACME", date_obj)
            existing = target_dir / src.name
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text("existing", encoding="utf-8")
            # Quelle mit gleichem Dateinamen erzeugen (Collision)
            src_dup_dir = tmp_dir / "sub"
            src_dup_dir.mkdir(parents=True, exist_ok=True)
            src_dup = src_dup_dir / "demo.pdf"
            src_dup.write_text("demo", encoding="utf-8")
            export_dup = export_document(src_dup, result_meta, settings)
            self.assertTrue(export_dup.path and export_dup.path.exists())
            self.assertNotEqual(str(export_dup.path), str(existing))
            self.assertIn("_01", export_dup.path.name)

            src2 = tmp_dir / "demo2.pdf"
            src2.write_text("demo", encoding="utf-8")
            result_meta_fallback = {"supplier": "", "supplier_confidence": "0.2", "date": "", "original": "whatever.pdf"}
            export_res_fb = export_document(src2, result_meta_fallback, settings)
            self.assertIn(export_res_fb.status, ("fallback", "skipped"))
            self.assertTrue(export_res_fb.path and export_res_fb.path.exists())


if __name__ == "__main__":
    unittest.main()
