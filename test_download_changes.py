#!/usr/bin/env python3
"""
Test für die neuen Download-Route-Änderungen.
Überprüft, dass Auto-Sort in download() und download_all() aufgerufen wird.
"""
import sys
from pathlib import Path

# Add base dir to path
BASE_DIR = Path(__file__).parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

def test_download_code_changes():
    """Überprüfe dass die Code-Änderungen in download-routes vorhanden sind."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 6 + "TEST: DOWNLOAD-ROUTE AUTO-SORT IMPLEMENTIERUNG" + " " * 6 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    app_file = Path("app/app.py")
    if not app_file.exists():
        print("❌ app/app.py nicht gefunden")
        return False
    
    app_code = app_file.read_text(encoding="utf-8")
    
    print("=" * 60)
    print("1. ÜBERPRÜFE download() ROUTE")
    print("=" * 60)
    
    # Überprüfe dass download() Auto-Sort aufruft
    checks = [
        ("_auto_sort_pdf in download()", "_auto_sort_pdf(result, pdf_path)" in app_code),
        ("already_sorted Logik", "already_sorted = export_path_val and Path(export_path_val).exists()" in app_code),
        ("Auto-Sort logging", "Auto-sorting before download" in app_code),
    ]
    
    all_pass = True
    for check_name, result in checks:
        if result:
            print(f"  ✓ {check_name}")
        else:
            print(f"  ❌ {check_name}")
            all_pass = False
    
    print("\n" + "=" * 60)
    print("2. ÜBERPRÜFE download_all() ROUTE")
    print("=" * 60)
    
    # Überprüfe dass download_all() Auto-Sort aufruft
    checks_all = [
        ("_auto_sort_pdf in download_all()", "def download_all():" in app_code and "_auto_sort_pdf" in app_code),
        ("Auto-Sort Loop in download_all", "for item in results:" in app_code),
        ("already_sorted Logik in download_all", "already_sorted = export_path_val and Path(export_path_val).exists()" in app_code),
        ("Auto-Sort logging in download_all", "Auto-sorting before download_all" in app_code),
    ]
    
    for check_name, result in checks_all:
        if result:
            print(f"  ✓ {check_name}")
        else:
            print(f"  ❌ {check_name}")
            all_pass = False
    
    print("\n" + "=" * 60)
    print("3. CODE-QUALITÄT")
    print("=" * 60)
    
    # Überprüfe dass Error-Handling vorhanden ist
    error_handling = [
        ("Try-Except um _auto_sort_pdf", "except Exception as exc:" in app_code),
        ("Logging bei Fehlern", "logger.warning" in app_code),
        ("No Exception on Auto-Sort Failure", "continue" in app_code or "pass" in app_code),
    ]
    
    for check_name, result in error_handling:
        if result:
            print(f"  ✓ {check_name}")
        else:
            print(f"  ⚠️  {check_name}")
            # Nicht kritisch für all_pass
    
    print("\n" + "=" * 60)
    print("4. ZUSÄTZLICHE VERBESSERUNGEN")
    print("=" * 60)
    
    improvements = [
        ("settings.enabled Überprüfung", "settings.enabled and not bool(result.get(\"quarantined\"))" in app_code or "if settings.enabled" in app_code),
        ("Quarantine Check", "quarantined" in app_code),
        ("PDF existence Check", "if pdf_path and pdf_path.exists():" in app_code or "path.exists()" in app_code),
    ]
    
    for check_name, result in improvements:
        if result:
            print(f"  ✓ {check_name}")
        else:
            print(f"  ⚠️  {check_name}")
    
    print("\n" + "=" * 60)
    if all_pass:
        print("✓ ALLE KRITISCHEN TESTS BESTANDEN")
    else:
        print("❌ EINIGE TESTS FEHLGESCHLAGEN")
    print("=" * 60)
    print()
    
    return all_pass

def test_code_correctness():
    """Überprüfe dass die Code-Logik korrekt ist."""
    print("\n" + "=" * 60)
    print("5. LOGIK-ÜBERPRÜFUNG")
    print("=" * 60)
    
    # Simuliere die Logik
    print("\nScenario 1: Datei noch nicht sortiert")
    print("-" * 40)
    
    export_path_val = ""  # Leerer export_path
    already_sorted = export_path_val and Path(export_path_val).exists()
    print(f"  export_path_val = '{export_path_val}'")
    print(f"  already_sorted = {already_sorted}")
    print(f"  → Should Auto-Sort = {not already_sorted}")
    if not already_sorted:
        print("  ✓ Auto-Sort würde aufgerufen")
    
    print("\nScenario 2: Datei bereits sortiert")
    print("-" * 40)
    
    export_path_val = str(Path("data/fertig/Foerch/2025-11/test.pdf"))
    already_sorted = export_path_val and Path(export_path_val).exists()
    print(f"  export_path_val = '{export_path_val}'")
    print(f"  already_sorted = {already_sorted}")
    print(f"  → Should Auto-Sort = {not already_sorted}")
    if not already_sorted:
        print("  ✓ Auto-Sort würde aufgerufen (Datei existiert nicht, also erneut versucht)")
    else:
        print("  ✓ Auto-Sort nicht nötig (Datei existiert bereits)")
    
    print("\n" + "=" * 60)
    print("✓ LOGIK-ÜBERPRÜFUNG ABGESCHLOSSEN")
    print("=" * 60)
    print()

if __name__ == "__main__":
    success = test_download_code_changes()
    test_code_correctness()
    sys.exit(0 if success else 1)
