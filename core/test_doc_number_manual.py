"""Schnelltest für doc_number_extractor."""

import sys
from pathlib import Path

# Add core to path
sys.path.insert(0, str(Path(__file__).parent))

from doc_number_extractor import extract_doc_number, generate_fallback_identifier


def test_all_suppliers():
    """Testet alle 8 Supplier-Beispiele."""
    
    tests = [
        ("WM", """
WM SE
Auftrags-Nr: 12345678
Datum: 26.11.2025
        """, "12345678"),
        
        ("VERGOELST", """
Vergölst Reifen
Beleg-Nr: D018017955
Datum: 27.11.2025
        """, "D018017955"),
        
        ("WFI", """
WFI GmbH
Lieferscheinnr: LS20250982
        """, "LS20250982"),
        
        ("FUCHS", """
FUCHS Schmierstoffe
Nummer: 226267189
        """, "226267189"),
        
        ("LKQ PV AUTOMOTIVE", """
LKQ PV Automotive
Lieferschein-Nr: 3814300
        """, "3814300"),
        
        ("OK", """
Ortojohann + Kraft
Rechnungsnummer: RE-2025-90879
        """, "RE-2025-90879"),
        
        ("HOFMEISTER & MEINCKE", """
Hofmeister & Meincke
Auftragsnr.: 14619213
        """, "14619213"),
        
        ("PIRTEK", """
PIRTEK Deutschland
Arbeitsauftrag: 08625112402
        """, "08625112402"),
    ]
    
    print("=" * 60)
    print("DOC NUMBER EXTRACTION - MANUAL TEST")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for supplier, text, expected in tests:
        result = extract_doc_number(text, supplier, None)
        
        status = "✓ PASS" if result.doc_number == expected else "✗ FAIL"
        
        if result.doc_number == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"\n{status} | {supplier}")
        print(f"  Expected: {expected}")
        print(f"  Got:      {result.doc_number}")
        print(f"  Source:   {result.source_field}")
        print(f"  Conf:     {result.confidence}")
    
    # Fallback-Test
    print("\n" + "=" * 60)
    print("FALLBACK TEST (ohneNr + Hash)")
    print("=" * 60)
    
    text_no_number = "Unbekannter Lieferant\nDatum: 26.11.2025"
    result_fallback = extract_doc_number(text_no_number, "UNKNOWN", None)
    
    print(f"Text ohne Nummer -> doc_number: {result_fallback.doc_number}")
    print(f"Confidence: {result_fallback.confidence}")
    
    # Hash-Test
    hash1 = generate_fallback_identifier(text_no_number)
    hash2 = generate_fallback_identifier(text_no_number)
    print(f"\nHash (deterministisch): {hash1}")
    print(f"Hash-Check: {hash1 == hash2} (sollte True sein)")
    
    print("\n" + "=" * 60)
    print(f"ERGEBNIS: {passed} passed, {failed} failed")
    print("=" * 60)


if __name__ == "__main__":
    test_all_suppliers()
