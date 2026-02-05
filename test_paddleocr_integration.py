#!/usr/bin/env python3
"""
PaddleOCR Integration Test für Docaro
Überprüft, ob PaddleOCR korrekt integriert ist
"""

import sys
import os
import subprocess
from pathlib import Path

# Docaro dir
DOCARO_DIR = Path(__file__).parent
VENV_PYTHON = DOCARO_DIR / ".venv" / "bin" / "python3"

# Falls nicht in venv, nutze venv python
if not hasattr(sys, 'real_prefix') and not sys.base_prefix != sys.prefix:
    if VENV_PYTHON.exists():
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__] + sys.argv[1:])

sys.path.insert(0, str(DOCARO_DIR))

def test_imports():
    """Test 1: Imports"""
    print("🧪 Test 1: Imports")
    try:
        from core import extractor
        print("  ✓ core.extractor imported")
        
        # Check if functions exist
        assert hasattr(extractor, '_get_paddleocr_instance'), "Missing _get_paddleocr_instance"
        assert hasattr(extractor, '_ocr_image_paddle'), "Missing _ocr_image_paddle"
        assert hasattr(extractor, 'USE_PADDLEOCR'), "Missing USE_PADDLEOCR config"
        print("  ✓ Alle neuen Funktionen vorhanden")
        return True
    except Exception as e:
        print(f"  ✗ Fehler: {e}")
        return False

def test_config():
    """Test 2: Configuration"""
    print("\n🧪 Test 2: Konfiguration")
    try:
        from config import Config
        print(f"  ✓ Config geladen")
        print(f"    USE_PADDLEOCR: {Config.USE_PADDLEOCR}")
        print(f"    PADDLEOCR_FALLBACK_THRESHOLD: {Config.PADDLEOCR_FALLBACK_THRESHOLD}")
        print(f"    PADDLEOCR_ENSEMBLE_FIELDS: {Config.PADDLEOCR_ENSEMBLE_FIELDS}")
        return True
    except Exception as e:
        print(f"  ✗ Fehler: {e}")
        return False

def test_paddleocr_module():
    """Test 3: PaddleOCR Module verfügbar"""
    print("\n🧪 Test 3: PaddleOCR Modul")
    try:
        # Check without import (nur pip list)
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "paddleocr"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = [l for l in result.stdout.split('\n') if l.startswith('Version:')]
            if version:
                print(f"  ✓ PaddleOCR installiert ({version[0]})")
            return True
        else:
            print("  ✗ PaddleOCR nicht installiert")
            return False
    except Exception as e:
        print(f"  ✗ Fehler: {e}")
        return False

def test_fallback_threshold():
    """Test 4: Fallback-Schwelle sinnvoll"""
    print("\n🧪 Test 4: Fallback-Schwelle")
    try:
        from config import Config
        threshold = Config.PADDLEOCR_FALLBACK_THRESHOLD
        
        # Sollte zwischen 200-800 sein
        if not (200 <= threshold <= 800):
            print(f"  ⚠️  Schwelle {threshold} ist ungewöhnlich (empfohlen: 300-500)")
            return False
        
        print(f"  ✓ Fallback-Schwelle {threshold} ist sinnvoll")
        return True
    except Exception as e:
        print(f"  ✗ Fehler: {e}")
        return False

def test_syntax():
    """Test 5: Python Syntax"""
    print("\n🧪 Test 5: Python Syntax")
    try:
        import py_compile
        py_compile.compile(str(DOCARO_DIR / "core" / "extractor.py"), doraise=True)
        py_compile.compile(str(DOCARO_DIR / "config.py"), doraise=True)
        print("  ✓ Alle Dateien syntaktisch korrekt")
        return True
    except Exception as e:
        print(f"  ✗ Fehler: {e}")
        return False

def test_service_running():
    """Test 6: Service läuft"""
    print("\n🧪 Test 6: Service Status")
    try:
        import subprocess
        result = subprocess.run(
            ["sudo", "systemctl", "is-active", "docaro"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print("  ✓ docaro.service ist aktiv")
            return True
        else:
            print("  ✗ docaro.service ist nicht aktiv")
            return False
    except Exception as e:
        print(f"  ⚠️  Kann Service-Status nicht prüfen: {e}")
        return None

def main():
    print("=" * 60)
    print("PaddleOCR Integration Test für Docaro")
    print("=" * 60)
    
    tests = [
        test_imports,
        test_config,
        test_paddleocr_module,
        test_fallback_threshold,
        test_syntax,
        test_service_running,
    ]
    
    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"\n🔥 Unerwarteter Fehler in {test_func.__name__}: {e}")
            results.append(False)
    
    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r is True)
    failed = sum(1 for r in results if r is False)
    skipped = sum(1 for r in results if r is None)
    
    print(f"Ergebnis: {passed} bestanden, {failed} fehlgeschlagen, {skipped} übersprungen")
    
    if failed == 0:
        print("\n✅ Alle Tests bestanden! PaddleOCR ist bereit.")
        print("\nNächste Schritte:")
        print("  1. Umgebungsvariable setzen:")
        print("     export DOCARO_USE_PADDLEOCR=1")
        print("  2. Services neustarten:")
        print("     sudo systemctl restart docaro docaro-worker")
        print("  3. Test-PDF hochladen und Logs überprüfen:")
        print("     tail -f /opt/Docaro/data/logs/docaro.log | grep -i paddle")
        return 0
    else:
        print("\n❌ Einige Tests sind fehlgeschlagen. Siehe Details oben.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
