"""
Tests für Docling Integration in Docaro.
"""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys

# Füge das Projekt-Verzeichnis zum Python-Pfad hinzu
test_dir = Path(__file__).parent
project_root = test_dir.parent
sys.path.insert(0, str(project_root))

from core.docling_extractor import (
    is_docling_available,
    get_extractor,
    DoclingExtractor,
)


class TestDoclingImport(unittest.TestCase):
    """Teste ob Docling-Imports funktionieren."""

    def test_is_docling_available(self):
        """Test is_docling_available Funktion."""
        result = is_docling_available()
        self.assertIsInstance(result, bool)
        print(f"Docling verfügbar: {result}")

    def test_get_extractor(self):
        """Test get_extractor Funktion."""
        try:
            extractor = get_extractor()
            # Wenn Docling nicht verfügbar ist, sollte None zurückgegeben werden
            if is_docling_available():
                self.assertIsNotNone(extractor)
                self.assertIsInstance(extractor, DoclingExtractor)
            else:
                self.assertIsNone(extractor)
        except ImportError as e:
            # Das ist ok, wenn Docling nicht installiert ist
            print(f"Erwarteter Fehler (Docling nicht installiert): {e}")
            self.assertFalse(is_docling_available())


class TestDoclingExtractor(unittest.TestCase):
    """Teste DoclingExtractor Klasse."""

    @unittest.skipIf(
        not is_docling_available(),
        "Docling nicht installiert"
    )
    def test_extractor_init(self):
        """Test DoclingExtractor Initialisierung."""
        try:
            extractor = DoclingExtractor()
            self.assertIsNotNone(extractor)
            self.assertIsNotNone(extractor.converter)
        except ImportError:
            self.skipTest("Docling nicht verfügbar")

    @unittest.skipIf(
        not is_docling_available(),
        "Docling nicht installiert"
    )
    def test_extract_text_with_mock(self):
        """Test extract_text mit Mock."""
        try:
            extractor = DoclingExtractor()
            
            # Mock die converter.convert() Methode
            mock_result = Mock()
            mock_document = Mock()
            mock_document.export_to_markdown.return_value = "# Test Document\n\nTest Content"
            mock_result.document = mock_document
            
            extractor.converter.convert = Mock(return_value=mock_result)
            
            # Test mit einem Beispiel-PDF-Pfad
            test_path = Path("/tmp/test.pdf")
            result = extractor.extract_text(test_path)
            
            self.assertEqual(result, "# Test Document\n\nTest Content")
            extractor.converter.convert.assert_called_once()
        except ImportError:
            self.skipTest("Docling nicht verfügbar")


class TestDoclingIntegration(unittest.TestCase):
    """Integrationstests für Docling."""

    def test_docling_module_structure(self):
        """Teste die Modulstruktur."""
        from core import docling_extractor
        
        # Überprüfe, dass alle notwendigen Funktionen existieren
        self.assertTrue(hasattr(docling_extractor, 'is_docling_available'))
        self.assertTrue(hasattr(docling_extractor, 'get_extractor'))
        self.assertTrue(hasattr(docling_extractor, 'DoclingExtractor'))

    def test_docling_availability_info(self):
        """Zeige Informationen zur Docling-Verfügbarkeit."""
        available = is_docling_available()
        print(f"\n{'='*50}")
        print(f"Docling Status:")
        print(f"  - Verfügbar: {available}")
        if not available:
            print(f"  - Installation: pip install docling")
            print(f"  - Speicherbedarf: ~1-2 GB (inkl. Modelle)")
        print(f"{'='*50}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
