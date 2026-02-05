#!/usr/bin/env python3
"""
Test-Script für Supplier-Detection mit erhöhtem DPI.
Testet die Erkennung von Förch vs. Franz Bracht in Lieferanschriften.
"""

import os
import sys
from pathlib import Path

# Set DPI to 300 for testing
os.environ["DOCARO_RENDER_DPI"] = "300"

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from core.extractor import extract_full, _render_dpi

def test_supplier_detection(pdf_path: str):
    """Testet Supplier-Erkennung für einen Lieferschein."""
    pdf = Path(pdf_path)
    
    if not pdf.exists():
        print(f"❌ Datei nicht gefunden: {pdf_path}")
        return
    
    print(f"\n{'='*70}")
    print(f"Test: {pdf.name}")
    print(f"{'='*70}")
    print(f"DPI: {_render_dpi()}")
    print()
    
    try:
        result = extract_full(pdf)
        
        print("📊 Extraktion-Ergebnis:")
        print(f"  Lieferant: {result.get('supplier', 'N/A')} (Confidence: {result.get('supplier_confidence', 0):.2f})")
        print(f"  Quelle: {result.get('supplier_source', 'N/A')}")
        print(f"  Matched: {result.get('supplier_guess', 'N/A')[:100]}")
        print(f"  Datum: {result.get('date', 'N/A')}")
        print(f"  Dokumenttyp: {result.get('doc_type', 'N/A')}")
        
        # Show top 3 candidates
        candidates = result.get('supplier_candidates', [])
        if candidates:
            print(f"\n🔍 Top 5 Kandidaten:")
            for i, cand in enumerate(candidates[:5], 1):
                print(f"  {i}. {cand.get('canonical', '?'):20s} "
                      f"Conf: {cand.get('confidence', 0):5.3f} "
                      f"Segment: {cand.get('segment', '?'):10s} "
                      f"Matched: {str(cand.get('matched', ''))[:50]}")
        
        # Show OCR text preview (first 1000 chars)
        ocr_text = result.get('ocr_text', '')
        if ocr_text:
            lines = ocr_text.split('\n')[:15]
            print(f"\n📄 OCR Text (erste 15 Zeilen):")
            for line in lines:
                if line.strip():
                    print(f"  {line[:80]}")
        
        print(f"\n{'='*70}\n")
        
    except Exception as e:
        print(f"❌ Fehler: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_supplier_detection.py <PDF-Pfad>")
        print("\nBeispiel:")
        print("  python test_supplier_detection.py data/eingang/scan.pdf")
        sys.exit(1)
    
    test_supplier_detection(sys.argv[1])
