"""
Tests für OCR-Processor.

Testet OCRmyPDF, PaddleOCR und EasyOCR Integration.
"""

import pytest
from pathlib import Path
from pipelines.ocr_processor import (
    OCRmyPDFProcessor,
    PaddleOCRProcessor,
    EasyOCRProcessor,
    process_with_ocr
)


@pytest.fixture
def sample_pdf(tmp_path):
    """Erstellt eine Test-PDF."""
    # Hinweis: In echten Tests würde hier eine PDF erstellt/geladen
    pdf_path = tmp_path / "test_document.pdf"
    # Mock: Leere Datei erstellen
    pdf_path.touch()
    return pdf_path


def test_ocrmypdf_processor(sample_pdf):
    """Test OCRmyPDF Processor."""
    processor = OCRmyPDFProcessor(language="deu")
    
    # Hinweis: Dieser Test benötigt OCRmyPDF installiert
    # Im echten Szenario würde hier ein gescanntes PDF getestet
    
    assert processor.language == "deu"
    assert processor.deskew is True


def test_paddleocr_processor():
    """Test PaddleOCR Processor."""
    processor = PaddleOCRProcessor(lang="german")
    
    assert processor.lang == "german"
    assert processor.use_angle_cls is True


def test_easyocr_processor():
    """Test EasyOCR Processor."""
    processor = EasyOCRProcessor(languages=['de', 'en'])
    
    assert processor.languages == ['de', 'en']


def test_process_with_ocr_auto(sample_pdf):
    """Test automatische OCR-Methodenwahl."""
    # Hinweis: In echten Tests würde hier mit echten PDFs getestet
    
    result = process_with_ocr(sample_pdf, method="auto")
    
    # Result sollte ein OCRResult sein
    assert hasattr(result, 'success')
    assert hasattr(result, 'method')


def test_ocr_result_dataclass():
    """Test OCRResult Dataclass."""
    from pipelines.ocr_processor import OCRResult
    
    result = OCRResult(
        success=True,
        text="Test text",
        method="ocrmypdf",
        confidence=0.95,
        processing_time=1.5
    )
    
    assert result.success is True
    assert result.text == "Test text"
    assert result.method == "ocrmypdf"
    assert result.confidence == 0.95
    assert result.processing_time == 1.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
