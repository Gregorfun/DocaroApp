"""
Minimale Tests für die 3 NEUEN Dokumente:
- Manitowoc (Rechnung)
- Kommissionierliste (Emergency Order)
- Übernahmeschein (Entsorgung)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.supplier_canonicalizer import SupplierCanonicalizer
from core.doc_number_extractor import DocNumberExtractor


def test_new_documents():
    """Test Canonicalizer + DocNumber für Manitowoc, Kommissionierliste, Übernahmeschein."""
    
    canonicalizer = SupplierCanonicalizer()
    extractor = DocNumberExtractor()
    
    test_cases = [
        {
            "name": "Manitowoc - Rechnung",
            "raw_supplier": "Manitowoc Crane Group",
            "ocr_text": """
                Manitowoc Crane Group
                RECHNUNG
                Rechnungsdatum: 15.01.2026
                Rechnungsnummer: 28463630558637
                Auftrags-Nr: A-123456
                Kunde: Franz Bracht Kran-Vermietung
            """,
            "doc_type": "Rechnung",
            "expected_canonical": "Manitowoc",
            "expected_doc_number": "28463630558637",
        },
        {
            "name": "Kommissionierliste - Emergency Order",
            "raw_supplier": "Kommissionierliste",
            "ocr_text": """
                KOMMISSIONIERLISTE (pro Auftrag)
                Emergency Order
                Datum: 18.01.2026
                Auftrag: 932639
                Kunde: Franz Bracht
                Komm.-is: XYZ-789
            """,
            "doc_type": "Lieferschein",
            "expected_canonical": "Kommissionierliste",
            "expected_doc_number": "932639",
        },
        {
            "name": "Übernahmeschein - Entsorgung",
            "raw_supplier": "Übernahmeschein",
            "ocr_text": """
                Übernahmeschein (Entsorgung/KS)
                Datum der Übernahme: 20.01.2026
                Nr. 28463630558637
                Entsorgungsnachweis-Nummer: ENT-2026-001
                SNE: 12345
            """,
            "doc_type": "Entsorgung",
            "expected_canonical": "Uebernahmeschein",
            "expected_doc_number": "28463630558637",
        },
    ]
    
    print("=" * 80)
    print("TEST: Neue Dokumente (Manitowoc, Kommissionierliste, Übernahmeschein)")
    print("=" * 80)
    
    all_passed = True
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n[Test {i}] {test['name']}")
        print("-" * 80)
        print(f"  Raw Supplier:   {test['raw_supplier']}")
        print(f"  Doc Type:       {test['doc_type']}")
        
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
            result = extractor.extract_doc_number(test["ocr_text"], canonical_name, test["doc_type"])
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
    success = test_new_documents()
    sys.exit(0 if success else 1)
