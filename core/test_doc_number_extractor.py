"""
Unit-Tests für supplier-spezifische Dokumentnummern-Extraktion.
"""

import unittest
from pathlib import Path
from core.doc_number_extractor import DocNumberExtractor, extract_doc_number, generate_fallback_identifier


class TestDocNumberExtraction(unittest.TestCase):
    """Tests für supplier-spezifische Dokumentnummern-Extraktion."""
    
    def setUp(self):
        """Setup: Erstelle Extractor-Instanz."""
        config_path = Path(__file__).parent.parent / "config" / "supplier_field_aliases.yaml"
        self.extractor = DocNumberExtractor(config_path)
    
    def test_wm_auftrags_nr(self):
        """Test: WM Auftrags-Nr Erkennung."""
        text = """
        WM SE
        Werkstatt München
        
        Auftrags-Nr: 12345678
        Datum: 26.11.2025
        Kunde: Test GmbH
        """
        result = self.extractor.extract_doc_number(text, "WM", None)
        
        self.assertIsNotNone(result.doc_number)
        self.assertEqual(result.doc_number, "12345678")
        self.assertEqual(result.confidence, "high")
        self.assertIn("Auftrags", result.source_field)
    
    def test_vergoelst_belegnummer(self):
        """Test: Vergölst Belegnummer D018017955."""
        text = """
        Vergölst Reifen Service
        
        Beleg-Nr: D018017955
        Datum: 27.11.2025
        Lieferschein
        """
        result = self.extractor.extract_doc_number(text, "VERGOELST", None)
        
        self.assertIsNotNone(result.doc_number)
        self.assertEqual(result.doc_number, "D018017955")
        self.assertEqual(result.confidence, "high")
        self.assertIn("Beleg", result.source_field)
    
    def test_wfi_lieferscheinnr(self):
        """Test: WFI Lieferscheinnr LS20250982."""
        text = """
        WFI GmbH & Co. KG
        
        Lieferscheinnr: LS20250982
        Datum: 26.11.2025
        Auftragsnummer: 123456
        """
        result = self.extractor.extract_doc_number(text, "WFI", None)
        
        self.assertIsNotNone(result.doc_number)
        self.assertEqual(result.doc_number, "LS20250982")
        self.assertEqual(result.confidence, "high")
        self.assertIn("Lieferschein", result.source_field)
    
    def test_fuchs_nummer(self):
        """Test: FUCHS Nummer 226267189."""
        text = """
        FUCHS EUROPE SCHMIERSTOFFE GMBH
        Lieferschein
        
        Nummer: 226267189
        Lieferdatum: 18.11.2025
        Auftragsnummer: AUF-789
        """
        result = self.extractor.extract_doc_number(text, "FUCHS", None)
        
        self.assertIsNotNone(result.doc_number)
        self.assertEqual(result.doc_number, "226267189")
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.source_field, "Nummer")
    
    def test_lkq_lieferschein_nr(self):
        """Test: LKQ Lieferschein-Nr 3814300."""
        text = """
        LKQ PV AUTOMOTIVE GMBH
        Lieferschein
        
        Lieferschein-Nr: 3814300
        Datum: 25.11.2025
        Auftragsnummer: 999888
        """
        result = self.extractor.extract_doc_number(text, "LKQ PV AUTOMOTIVE", None)
        
        self.assertIsNotNone(result.doc_number)
        self.assertEqual(result.doc_number, "3814300")
        self.assertEqual(result.confidence, "high")
        self.assertIn("Lieferschein", result.source_field)
    
    def test_ok_rechnungsnummer(self):
        """Test: OK Rechnung RE-2025-90879."""
        text = """
        Ortojohann + Kraft GmbH
        RECHNUNG
        
        Rechnungsnummer: RE-2025-90879
        Rechnungsdatum: 22.11.2025
        Ursprünglicher Auftrag: AUF-12345
        """
        result = self.extractor.extract_doc_number(text, "OK", "Rechnung")
        
        self.assertIsNotNone(result.doc_number)
        self.assertIn("RE-2025", result.doc_number)  # Format kann variieren (mit/ohne slash)
        self.assertEqual(result.confidence, "high")
        self.assertIn("Rechnung", result.source_field)
    
    def test_ok_ursprunglicher_auftrag(self):
        """Test: OK sekundäres Feld 'Ursprünglicher Auftrag'."""
        text = """
        Ortojohann + Kraft GmbH
        RECHNUNG
        
        Ursprünglicher Auftrag: AUF-55555
        Rechnungsdatum: 22.11.2025
        """
        result = self.extractor.extract_doc_number(text, "OK", None)
        
        self.assertIsNotNone(result.doc_number)
        self.assertEqual(result.doc_number, "AUF-55555")
        self.assertIn(result.confidence, ["high", "medium"])
    
    def test_hofmeister_auftragsnr(self):
        """Test: Hofmeister & Meincke Auftragsnr 14619213."""
        text = """
        HOFMEISTER & MEINCKE GMBH
        Lieferschein
        
        Auftragsnr.: 14619213
        Datum: 25.11.2025
        """
        result = self.extractor.extract_doc_number(text, "HOFMEISTER & MEINCKE", None)
        
        self.assertIsNotNone(result.doc_number)
        self.assertEqual(result.doc_number, "14619213")
        self.assertEqual(result.confidence, "high")
    
    def test_pirtek_arbeitsauftrag(self):
        """Test: PIRTEK Arbeitsauftrag 08625112402."""
        text = """
        PIRTEK Deutschland GmbH
        
        Arbeitsauftrag: 08625112402
        Datum: 24.11.2025
        Kunde: Bracht Autokrane
        """
        result = self.extractor.extract_doc_number(text, "PIRTEK", None)
        
        self.assertIsNotNone(result.doc_number)
        self.assertEqual(result.doc_number, "08625112402")
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.source_field, "Arbeitsauftrag")
    
    def test_fallback_ohne_nummer(self):
        """Test: Fallback ohneNr+Hash wenn keine Nummer gefunden."""
        text = """
        Unbekannter Lieferant
        
        Datum: 26.11.2025
        Kunde: Test GmbH
        Betrag: 1.234,56 EUR
        """
        result = self.extractor.extract_doc_number(text, "UNBEKANNT", None)
        
        # Kein Treffer: Sollte None zurückgeben
        self.assertIsNone(result.doc_number)
        self.assertEqual(result.confidence, "none")
    
    def test_generate_fallback_identifier(self):
        """Test: Generiere stabilen Hash für Fallback."""
        text = "Test Document Content 12345"
        hash1 = generate_fallback_identifier(text)
        hash2 = generate_fallback_identifier(text)
        
        self.assertEqual(hash1, hash2)  # Deterministisch
        self.assertEqual(len(hash1), 6)  # 6 Zeichen
        self.assertTrue(hash1.isupper())  # Uppercase
        self.assertTrue(all(c in "0123456789ABCDEF" for c in hash1))  # Hex
    
    def test_filter_datum(self):
        """Test: Filtere Datumswerte (kein false positive)."""
        text = """
        Lieferant XYZ
        Lieferschein-Nr: 2025-11-26
        Datum: 26.11.2025
        """
        result = self.extractor.extract_doc_number(text, None, None)
        
        # 2025-11-26 sollte nicht als Nummer erkannt werden (ist Datum)
        if result.doc_number:
            self.assertNotIn("2025-11-26", result.doc_number)
    
    def test_filter_plz(self):
        """Test: Filtere PLZ (5-stellige Zahl ohne Kontext)."""
        text = """
        Lieferant ABC
        Straße 123
        12345 Berlin
        """
        result = self.extractor.extract_doc_number(text, None, None)
        
        # 12345 sollte nicht als Nummer erkannt werden (PLZ)
        if result.doc_number:
            self.assertNotEqual(result.doc_number, "12345")
    
    def test_multiline_extraction(self):
        """Test: Nummer in nächster Zeile nach Feldname."""
        text = """
        FUCHS Schmierstoffe
        Lieferschein
        Nummer:
        999888777
        Datum: 18.11.2025
        """
        result = self.extractor.extract_doc_number(text, "FUCHS", None)
        
        self.assertIsNotNone(result.doc_number)
        self.assertEqual(result.doc_number, "999888777")
        self.assertEqual(result.confidence, "high")
    
    def test_convenience_function(self):
        """Test: Globale convenience-Funktion extract_doc_number()."""
        text = """
        WFI GmbH
        Lieferschein Nr: LS88888
        """
        result = extract_doc_number(text, "WFI", None)
        
        self.assertIsNotNone(result.doc_number)
        self.assertEqual(result.doc_number, "LS88888")


if __name__ == "__main__":
    unittest.main()
