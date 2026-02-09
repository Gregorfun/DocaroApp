"""
Unit-Tests für Supplier Canonicalizer.
"""

import unittest
from pathlib import Path
from core.supplier_canonicalizer import SupplierCanonicalizer, canonicalize_supplier


class TestSupplierCanonicalizer(unittest.TestCase):
    """Tests für Supplier-Canonicalization."""
    
    def setUp(self):
        """Setup: Erstelle Canonicalizer-Instanz."""
        config_path = Path(__file__).parent.parent / "config" / "supplier_aliases.yaml"
        self.canonicalizer = SupplierCanonicalizer(config_path)
    
    def test_vergoelst_variant(self):
        """Test: Vergolst -> Vergölst."""
        result = self.canonicalizer.canonicalize_supplier("Vergolst")
        
        self.assertIsNotNone(result)
        self.assertEqual(result.canonical_name, "Vergölst")
        self.assertGreaterEqual(result.confidence, 0.85)
    
    def test_lkq_pv_automotive(self):
        """Test: LKQ PV Automotive -> LKQ PV AUTOMOTIVE."""
        result = self.canonicalizer.canonicalize_supplier("LKQ PV Automotive")
        
        self.assertIsNotNone(result)
        self.assertEqual(result.canonical_name, "LKQ PV AUTOMOTIVE")
        self.assertGreaterEqual(result.confidence, 0.90)
    
    def test_wfi_wireless_funk(self):
        """Test: Wireless Funk- und Informationstechnik -> WFI."""
        result = self.canonicalizer.canonicalize_supplier("Wireless Funk- und Informationstechnik")
        
        self.assertIsNotNone(result)
        self.assertEqual(result.canonical_name, "WFI")
        self.assertGreaterEqual(result.confidence, 0.85)
    
    def test_fuchs_lubricants(self):
        """Test: Fuchs Lubricants Germany -> FUCHS."""
        text = "Fuchs Lubricants Germany"
        full_text = "FUCHS LUBRICANTS GERMANY GmbH\nRechnung\nDatum: 01.12.2025"
        
        result = self.canonicalizer.canonicalize_supplier(text, full_text)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.canonical_name, "FUCHS")
        self.assertGreaterEqual(result.confidence, 0.85)
    
    def test_hofmeister_meincke_context(self):
        """Test: Hofmeister ... Meincke -> Hofmeister & Meincke."""
        text = "Hofmeister"
        full_text = """
        Hofmeister & Meincke GmbH
        Reifen und Autoteile
        Datum: 25.11.2025
        """
        
        result = self.canonicalizer.canonicalize_supplier(text, full_text)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.canonical_name, "Hofmeister & Meincke")
        self.assertGreaterEqual(result.confidence, 0.70)
    
    def test_wm_variants(self):
        """Test: W+M, W & M -> WM."""
        variants = ["W+M", "W & M", "WM Fahrzeugteile", "WM SE"]
        
        for variant in variants:
            with self.subTest(variant=variant):
                result = self.canonicalizer.canonicalize_supplier(variant)
                self.assertIsNotNone(result, f"No match for {variant}")
                self.assertEqual(result.canonical_name, "WM", f"Wrong canonical for {variant}")
    
    def test_ortojohann_kraft(self):
        """Test: Ortojohann, Ortojohann+Kraft -> Ortojohann+Kraft."""
        variants = ["Ortojohann", "Ortojohann+Kraft", "Ortojohann & Kraft"]
        
        for variant in variants:
            with self.subTest(variant=variant):
                result = self.canonicalizer.canonicalize_supplier(variant)
                self.assertIsNotNone(result, f"No match for {variant}")
                self.assertEqual(result.canonical_name, "Orjohann Kraft", f"Wrong canonical for {variant}")
    
    def test_pirtek_case_insensitive(self):
        """Test: PIRTEK, Pirtek, pirtek -> PIRTEK."""
        variants = ["PIRTEK", "Pirtek", "pirtek"]
        
        for variant in variants:
            with self.subTest(variant=variant):
                result = self.canonicalizer.canonicalize_supplier(variant)
                self.assertIsNotNone(result, f"No match for {variant}")
                self.assertEqual(result.canonical_name, "PIRTEK", f"Wrong canonical for {variant}")
    
    def test_fuchs_regex_pattern(self):
        """Test: Fuchs Schmierstoffe via Regex."""
        text = "FUCHS EUROPE SCHMIERSTOFFE GMBH"
        
        result = self.canonicalizer.canonicalize_supplier(text)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.canonical_name, "FUCHS")
        self.assertEqual(result.match_type, "regex")
    
    def test_bracht_variants(self):
        """Test: Franz Bracht Varianten."""
        variants = ["Bracht", "Franz Bracht", "Franz Bracht Kran-Vermietung", "Bracht Autokrane"]
        
        for variant in variants:
            with self.subTest(variant=variant):
                result = self.canonicalizer.canonicalize_supplier(variant)
                self.assertIsNotNone(result, f"No match for {variant}")
                self.assertEqual(result.canonical_name, "Franz Bracht", f"Wrong canonical for {variant}")
    
    def test_no_match_unbekannt(self):
        """Test: Unbekannter Supplier -> None."""
        result = self.canonicalizer.canonicalize_supplier("XYZ Totally Unknown Company")
        
        self.assertIsNone(result)
    
    def test_normalization(self):
        """Test: Normalisierung (Umlaute, Sonderzeichen)."""
        # Vergölst mit ö sollte auch Vergoelst mit oe matchen
        result = self.canonicalizer.canonicalize_supplier("Vergoelst")
        
        self.assertIsNotNone(result)
        self.assertEqual(result.canonical_name, "Vergölst")
    
    def test_substring_match(self):
        """Test: Substring-Match (LKQ in 'LKQ GmbH')."""
        result = self.canonicalizer.canonicalize_supplier("LKQ GmbH")
        
        self.assertIsNotNone(result)
        self.assertEqual(result.canonical_name, "LKQ PV AUTOMOTIVE")
    
    def test_convenience_function(self):
        """Test: Globale convenience-Funktion."""
        result = canonicalize_supplier("WM Fahrzeugteile")
        
        self.assertIsNotNone(result)
        self.assertEqual(result.canonical_name, "WM")
    
    def test_all_canonical_names(self):
        """Test: Alle kanonischen Namen abrufen."""
        names = self.canonicalizer.list_all_canonical_names()
        
        self.assertGreater(len(names), 0)
        self.assertIn("WM", names)
        self.assertIn("Vergölst", names)
        self.assertIn("FUCHS", names)


if __name__ == "__main__":
    unittest.main()
