"""
Test-Script für die neuen Supplier (Foerch, Tadano, Liebherr)
und verifizierten Supplier (LKQ, Vergölst, WM).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.supplier_canonicalizer import SupplierCanonicalizer
from core.doc_number_extractor import DocNumberExtractor


def test_canonicalizer_and_doc_number():
    """Test Canonicalizer + DocNumber Extraktion für alle 6 Supplier."""
    
    canonicalizer = SupplierCanonicalizer()
    extractor = DocNumberExtractor()
    
    test_cases = [
        {
            "name": "LKQ - Lieferschein",
            "raw_supplier": "LKQ PV Automotive",  # Das würde detect_supplier() liefern
            "ocr_text": """
                LKQ PV Automotive GmbH
                Lieferschein
                Datum: 2025-01-15
                Lieferschein-Nr: LS20250982
                Auftragsnummer: 123456789
                Kunde: Franz Bracht
            """,
            "expected_canonical": "LKQ PV AUTOMOTIVE",
            "expected_doc_number": "LS20250982",
        },
        {
            "name": "Vergölst - Belegnummer",
            "raw_supplier": "VERGÖLST",
            "ocr_text": """
                VERGÖLST
                Niederlassung Ulm
                Beleg-Datum: 15.01.2025
                Belegnummer: D018017933
                Kunde: Franz Bracht Kran-Vermietung
            """,
            "expected_canonical": "Vergölst",
            "expected_doc_number": "D018017933",
        },
        {
            "name": "Foerch - Belegnummer",
            "raw_supplier": "FÖRCH GmbH",
            "ocr_text": """
                FÖRCH GmbH
                Lieferschein
                Datum: 2025-01-18
                Belegnummer: 801299479x
                Kundennummer: K-12345
            """,
            "expected_canonical": "Foerch",
            "expected_doc_number": "801299479x",
        },
        {
            "name": "WM - Auftrags-Nr",
            "raw_supplier": "WM SE",
            "ocr_text": """
                WM SE
                Lieferschein
                Datum: 20.01.2025
                Auftrags-Nr: 226267189
                Kunde: Bracht Autokrane
            """,
            "expected_canonical": "WM",
            "expected_doc_number": "226267189",
        },
        {
            "name": "Tadano - Order ID",
            "raw_supplier": "CEVA Logistics",
            "ocr_text": """
                CEVA Logistics GmbH
                for Tadano Faun
                Shipment Date: 2025-01-22
                Order ID: C-6062165240
                Lieferschein: LS-9988776
            """,
            "expected_canonical": "Tadano",
            "expected_doc_number": "C-6062165240",
        },
        {
            "name": "Liebherr - Lieferschein",
            "raw_supplier": "Liebherr-Werk Ehingen",
            "ocr_text": """
                Liebherr-Werk Ehingen GmbH
                Lieferschein-Datum: 25.01.2025
                Lieferschein: 127749
                Auftragsnummer: A-5544332211
                Bestellnummer: B-9988776
            """,
            "expected_canonical": "Liebherr",
            "expected_doc_number": "127749",
        },
    ]
    
    print("=" * 80)
    print("TEST: Neue Supplier (Foerch, Tadano, Liebherr) + Verifizierte (LKQ, Vergölst, WM)")
    print("=" * 80)
    
    all_passed = True
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n[Test {i}] {test['name']}")
        print("-" * 80)
        print(f"  Raw Supplier:   {test['raw_supplier']}")
        
        # 1. Canonicalizer Test
        match = canonicalizer.canonicalize_supplier(test["raw_supplier"], test["ocr_text"])
        canonical_name = match.canonical_name if match else None
        
        print(f"  Canonical Name: {canonical_name}")
        print(f"  Expected:       {test['expected_canonical']}")
        
        if canonical_name != test['expected_canonical']:
            print(f"  ❌ FAIL: Canonicalizer")
            all_passed = False
        else:
            print(f"  ✅ PASS: Canonicalizer")
        
        # 2. DocNumber Extractor Test
        if canonical_name:
            result = extractor.extract_doc_number(test["ocr_text"], canonical_name, "Lieferschein")
            doc_number = result.doc_number
            
            print(f"  Doc Number:     {doc_number}")
            print(f"  Expected:       {test['expected_doc_number']}")
            print(f"  Source Field:   {result.source_field}")
            print(f"  Confidence:     {result.confidence}")
            
            if doc_number != test['expected_doc_number']:
                print(f"  ❌ FAIL: DocNumber Extraction")
                all_passed = False
            else:
                print(f"  ✅ PASS: DocNumber Extraction")
        else:
            print(f"  ❌ SKIP: DocNumber Test (Canonicalizer failed)")
            all_passed = False
    
    print("\n" + "=" * 80)
    if all_passed:
        print("✅ ALLE TESTS BESTANDEN")
    else:
        print("❌ EINIGE TESTS FEHLGESCHLAGEN")
    print("=" * 80)
    
    return all_passed


if __name__ == "__main__":
    success = test_canonicalizer_and_doc_number()
    sys.exit(0 if success else 1)
