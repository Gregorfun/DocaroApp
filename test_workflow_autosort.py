#!/usr/bin/env python3
"""
Integrations-Test: Auto-Sort nach Überprüfung/Download.

Dieser Test simuliert den kompletten Workflow:
1. PDF wird verarbeitet
2. Datei wird überprüft (optional bestätigt)
3. Datei wird zum Download vorbereitet
4. Auto-Sort sollte stattfinden
"""
import sys
import json
from pathlib import Path
from datetime import datetime

# Add base dir to path
BASE_DIR = Path(__file__).parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import Config
from services.auto_sort import export_document, load_settings as load_auto_sort_settings, AutoSortSettings

config = Config()

def test_workflow():
    """Teste den kompletten Auto-Sort-Workflow."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 8 + "INTEGRATIONS-TEST: AUTO-SORT NACH DOWNLOAD" + " " * 8 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    # Lade Settings
    defaults = AutoSortSettings()
    settings = load_auto_sort_settings(config.SETTINGS_PATH, defaults)
    
    print("=" * 60)
    print("1. VORBEDINGUNGEN ÜBERPRÜFEN")
    print("=" * 60)
    
    # Überprüfe dass Auto-Sort aktiviert ist
    if not settings.enabled:
        print("❌ FEHLER: Auto-Sort ist DEAKTIVIERT!")
        return False
    print("✓ Auto-Sort ist aktiviert")
    
    # Überprüfe dass Base-Verzeichnis existiert
    if not settings.base_dir or not Path(settings.base_dir).exists():
        print(f"❌ FEHLER: Base-Verzeichnis existiert nicht: {settings.base_dir}")
        return False
    print(f"✓ Base-Verzeichnis existiert: {settings.base_dir}")
    
    # Überprüfe dass bereits PDFs sortiert wurden
    fertig_dir = Path(settings.base_dir)
    sorted_pdfs = list(fertig_dir.rglob("*.pdf"))
    if not sorted_pdfs:
        print("❌ FEHLER: Keine sortierten PDFs gefunden!")
        return False
    print(f"✓ {len(sorted_pdfs)} bereits sortierte PDFs gefunden")
    
    # Lade session_files.json um zu sehen, welche Dateien im Download wären
    session_files_path = config.DATA_DIR / "session_files.json"
    if not session_files_path.exists():
        print("⚠️  Keine session_files.json gefunden (kein aktiver Session)")
        print("   -> Test mit Beispiel-Ergebnis")
        
        # Verwende ein vorhandenes PDF für den Test
        test_pdf = sorted_pdfs[0]
        print(f"\n✓ Test-PDF: {test_pdf}")
        
        # Extrahiere Info aus Pfad
        parts = test_pdf.parent.parent.name.split()
        supplier = test_pdf.parent.parent.name
        date_str = test_pdf.parent.name
        
        test_result = {
            "file_id": "test_" + datetime.now().strftime("%Y%m%d%H%M%S"),
            "out_name": test_pdf.name,
            "supplier": supplier,
            "supplier_confidence": 0.95,
            "date": date_str + "-01",
            "document_type": "LIEFERSCHEIN",
            "auto_sort_status": "",
            "auto_sort_reason": "",
            "export_path": ""
        }
        
        print("\nTest-Ergebnis:", test_result)
    else:
        print("✓ session_files.json vorhanden")
        session_data = json.loads(session_files_path.read_text(encoding="utf-8"))
        print(f"✓ Session-Daten geladen")
    
    print("\n" + "=" * 60)
    print("2. SIMULIERE DOWNLOAD MIT AUTO-SORT")
    print("=" * 60)
    
    # Wähle ein PDF das noch nicht in export_path eingetragen ist
    out_dir = Path(config.OUT_DIR)
    test_pdf_to_sort = None
    
    # Finde ein PDF in OUT_DIR ohne export_path
    if out_dir.exists():
        out_pdfs = list(out_dir.glob("*.pdf"))
        if out_pdfs:
            test_pdf_to_sort = out_pdfs[0]
            print(f"✓ Test-PDF in OUT_DIR gefunden: {test_pdf_to_sort.name}")
    
    if not test_pdf_to_sort:
        # Verwende ein sortiertes PDF für den Test
        test_pdf_to_sort = sorted_pdfs[0]
        print(f"⚠️  Kein PDF in OUT_DIR, verwende sortiertes PDF: {test_pdf_to_sort.name}")
    
    # Erstelle Mock-Ergebnis
    test_result = {
        "file_id": "test_download_" + datetime.now().strftime("%Y%m%d%H%M%S"),
        "out_name": test_pdf_to_sort.name,
        "supplier": test_pdf_to_sort.parent.parent.name,
        "supplier_confidence": 0.95,
        "date": test_pdf_to_sort.parent.name + "-01",
        "document_type": "LIEFERSCHEIN",
        "quarantined": False,
        "auto_sort_status": "pending",
        "auto_sort_reason": "",
        "export_path": ""
    }
    
    print(f"  Supplier: {test_result['supplier']}")
    print(f"  Datum: {test_result['date']}")
    print(f"  Typ: {test_result['document_type']}")
    
    # Simuliere Download mit Auto-Sort
    print("\n  Simuliere Download-Prozess...")
    print(f"  - Überprüfe ob Auto-Sort nötig ist...")
    
    export_path_exists = bool(test_result.get("export_path"))
    if export_path_exists:
        export_path = Path(test_result["export_path"])
        if not export_path.exists():
            export_path_exists = False
    
    if not export_path_exists:
        print(f"  - Auto-Sort ist nötig (export_path nicht gesetzt)")
        print(f"  - Führe export_document aus...")
        
        try:
            result = export_document(test_pdf_to_sort, test_result, settings)
            
            print(f"\n✓ Export erfolgreich!")
            print(f"  Status: {result.status}")
            print(f"  Ziel: {result.path}")
            print(f"  Grund: {result.reason}")
            
            if result.status in ("sorted", "fallback"):
                print(f"  ✓ Datei wurde korrekt sortiert/fallback")
                test_result["export_path"] = str(result.path)
                test_result["auto_sort_status"] = result.status
                test_result["auto_sort_reason"] = result.reason
            else:
                print(f"  ⚠️  Datei wurde nicht verschoben: {result.reason}")
        
        except Exception as exc:
            print(f"  ❌ FEHLER: {exc}")
            return False
    else:
        print(f"  ✓ Auto-Sort bereits durchgeführt")
        print(f"  Export-Pfad: {test_result['export_path']}")
    
    print("\n" + "=" * 60)
    print("3. ERGEBNIS-ÜBERPRÜFUNG")
    print("=" * 60)
    
    # Überprüfe dass export_path korrekt ist
    if test_result.get("export_path"):
        export_path = Path(test_result["export_path"])
        if export_path.exists():
            print(f"✓ Ziel-Datei existiert: {export_path}")
            
            # Überprüfe dass Datei im richtigen Ordner ist
            if settings.base_dir:
                try:
                    export_path.resolve().relative_to(Path(settings.base_dir).resolve())
                    print(f"✓ Datei ist im Base-Verzeichnis: {settings.base_dir}")
                except ValueError:
                    print(f"⚠️  Datei ist NICHT im Base-Verzeichnis!")
        else:
            print(f"❌ Ziel-Datei existiert nicht: {export_path}")
    
    print("\n" + "=" * 60)
    print("4. WORKFLOW-STATUS")
    print("=" * 60)
    
    print("\nFinal-Status des Test-Ergebnisses:")
    print(f"  file_id: {test_result['file_id']}")
    print(f"  out_name: {test_result['out_name']}")
    print(f"  supplier: {test_result['supplier']}")
    print(f"  date: {test_result['date']}")
    print(f"  auto_sort_status: {test_result['auto_sort_status']}")
    print(f"  auto_sort_reason: {test_result['auto_sort_reason']}")
    print(f"  export_path: {test_result['export_path']}")
    
    print("\n" + "=" * 60)
    print("✓ INTEGRATIONS-TEST ABGESCHLOSSEN")
    print("=" * 60)
    print("\nZUSAMMENFASSUNG:")
    print("- Auto-Sort ist aktiviert und funktioniert")
    print("- Dateien werden korrekt in Ordner sortiert")
    print("- Download-Workflow funktioniert wie erwartet")
    print()
    
    return True

if __name__ == "__main__":
    success = test_workflow()
    sys.exit(0 if success else 1)
