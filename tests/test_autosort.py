#!/usr/bin/env python3
"""
Test für Auto-Sort-Funktionalität nach Download.
"""
import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import Config

config = Config()

def test_auto_sort_config():
    """Überprüfe Auto-Sort-Konfiguration."""
    print("=" * 60)
    print("AUTO-SORT TEST - Konfiguration")
    print("=" * 60)
    
    from services.auto_sort import load_settings as load_auto_sort_settings, AutoSortSettings
    
    defaults = AutoSortSettings()
    settings = load_auto_sort_settings(config.SETTINGS_PATH, defaults)
    if not settings:
        print("❌ Auto-Sort-Settings konnten nicht geladen werden")
        return False
    
    print(f"✓ Auto-Sort aktiviert: {settings.enabled}")
    print(f"✓ Base-Verzeichnis: {settings.base_dir}")
    print(f"✓ Ordner-Format: {settings.normalized_format()}")
    print(f"✓ Modus: {settings.normalized_mode()}")
    print(f"✓ Konfidenz-Schwelle: {settings.confidence_threshold}")
    print(f"✓ Fallback-Ordner: {settings.fallback_folder}")
    
    if not settings.enabled:
        print("⚠️  Auto-Sort ist DEAKTIVIERT!")
        return False
    
    if not settings.base_dir or str(settings.base_dir).strip() == ".":
        print("⚠️  Base-Verzeichnis ist nicht gesetzt!")
        return False
    
    base_path = Path(settings.base_dir)
    if not base_path.exists():
        print(f"⚠️  Base-Verzeichnis existiert nicht: {base_path}")
        return False
    
    print(f"\n✓ Base-Verzeichnis existiert: {base_path}")
    
    # Überprüfe ob sortierte Ordner vorhanden sind
    supplier_dirs = [d for d in base_path.iterdir() if d.is_dir() and not d.name.startswith("_")]
    print(f"✓ Supplier-Ordner vorhanden: {len(supplier_dirs)}")
    for supplier_dir in supplier_dirs[:5]:
        month_dirs = [d for d in supplier_dir.iterdir() if d.is_dir()]
        pdf_count = sum(1 for d in supplier_dir.rglob("*.pdf"))
        print(f"  - {supplier_dir.name}: {pdf_count} PDFs")
    
    return True

def test_auto_sort_decision():
    """Teste Auto-Sort-Entscheidungslogik."""
    print("\n" + "=" * 60)
    print("AUTO-SORT TEST - Entscheidungslogik")
    print("=" * 60)
    
    from services.auto_sort import decide_auto_sort, load_settings as load_auto_sort_settings, AutoSortSettings
    from datetime import datetime
    
    defaults = AutoSortSettings()
    settings = load_auto_sort_settings(config.SETTINGS_PATH, defaults)
    
    # Test 1: Valides Dokument
    test_result_1 = {
        "supplier": "Foerch",
        "supplier_confidence": 0.95,
        "date": "2025-11-17",
        "document_type": "LIEFERSCHEIN"
    }
    
    decision = decide_auto_sort(test_result_1, settings)
    print(f"\nTest 1 - Valides Dokument (Foerch):")
    print(f"  Sollte sortiert werden: {decision.should_sort}")
    print(f"  Grund: {decision.reason_code}")
    print(f"  Target: {decision.target_dir}")
    
    if not decision.should_sort:
        print(f"  ❌ FEHLER: Sollte sortiert werden!")
        return False
    
    # Test 2: Fehlender Supplier
    test_result_2 = {
        "supplier": "Unbekannt",
        "supplier_confidence": 0.0,
        "date": "2025-11-17",
        "document_type": "LIEFERSCHEIN"
    }
    
    decision = decide_auto_sort(test_result_2, settings)
    print(f"\nTest 2 - Fehlender Supplier:")
    print(f"  Sollte sortiert werden: {decision.should_sort}")
    print(f"  Grund: {decision.reason_code}")
    print(f"  Target (Fallback): {decision.target_dir}")
    
    if decision.should_sort:
        print(f"  ⚠️  Warnung: Sollte NICHT sortiert werden (nur in Fallback)")
    
    # Test 3: Niedrige Konfidenz
    test_result_3 = {
        "supplier": "Some Company",
        "supplier_confidence": 0.5,
        "date": "2025-11-17",
        "document_type": "LIEFERSCHEIN"
    }
    
    decision = decide_auto_sort(test_result_3, settings)
    print(f"\nTest 3 - Niedrige Supplier-Konfidenz (0.5):")
    print(f"  Sollte sortiert werden: {decision.should_sort}")
    print(f"  Grund: {decision.reason_code}")
    
    return True

def test_export_document():
    """Teste export_document-Funktion."""
    print("\n" + "=" * 60)
    print("AUTO-SORT TEST - export_document")
    print("=" * 60)
    
    from services.auto_sort import export_document, load_settings as load_auto_sort_settings, AutoSortSettings
    import shutil
    import tempfile
    
    defaults = AutoSortSettings()
    settings = load_auto_sort_settings(config.SETTINGS_PATH, defaults)
    
    # Finde ein vorhandenes PDF
    fertig_dir = Path("data/fertig")
    existing_pdfs = list(fertig_dir.rglob("*.pdf"))
    
    if not existing_pdfs:
        print("⚠️  Keine Test-PDFs in data/fertig gefunden")
        return True
    
    # Verwende das erste gefundene PDF für den Test
    source_pdf = existing_pdfs[0]
    print(f"✓ Test-PDF gefunden: {source_pdf}")
    
    # Erstelle eine Kopie im Temp-Verzeichnis für den Test
    with tempfile.TemporaryDirectory() as tmpdir:
        test_pdf = Path(tmpdir) / source_pdf.name
        shutil.copy2(source_pdf, test_pdf)
        
        # Extrahiere Info aus dem Dateinamen
        parts = source_pdf.parent.parent.name, source_pdf.parent.name
        supplier, date_part = parts
        
        test_result = {
            "supplier": supplier,
            "supplier_confidence": 0.95,
            "date": f"{date_part}-01",
            "document_type": "LIEFERSCHEIN"
        }
        
        print(f"Test-Result: {test_result}")
        print(f"Test-PDF: {test_pdf}")
        
        # Führe export_document aus
        result = export_document(test_pdf, test_result, settings)
        
        print(f"\n✓ Export-Result:")
        print(f"  Status: {result.status}")
        print(f"  Ziel-Pfad: {result.path}")
        print(f"  Grund: {result.reason}")
        print(f"  Reason-Code: {result.reason_code}")
    
    return True

def main():
    """Führe alle Tests aus."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "AUTO-SORT FUNKTIONALITÄT TEST" + " " * 19 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    all_pass = True
    
    # Test 1: Konfiguration
    if not test_auto_sort_config():
        all_pass = False
    
    # Test 2: Entscheidungslogik
    if not test_auto_sort_decision():
        all_pass = False
    
    # Test 3: Export-Funktion
    if not test_export_document():
        all_pass = False
    
    # Zusammenfassung
    print("\n" + "=" * 60)
    if all_pass:
        print("✓ ALLE TESTS BESTANDEN")
    else:
        print("❌ EINIGE TESTS FEHLGESCHLAGEN")
    print("=" * 60)
    print()

if __name__ == "__main__":
    main()
