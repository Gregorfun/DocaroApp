"""
Docaro Pipelines Package.

Enthält alle Pipeline-Komponenten für die Dokumentenverarbeitung.
"""

from pipelines.document_pipeline import DocumentPipeline, PipelineResult
from pipelines.ocr_processor import process_with_ocr, OCRResult
from pipelines.document_processor import DoclingProcessor, DoclingProcessingResult
from pipelines.ml_analyzer import MLAnalyzer, MLAnalysisResult

__all__ = [
    'DocumentPipeline',
    'PipelineResult',
    'process_with_ocr',
    'OCRResult',
    'DoclingProcessor',
    'DoclingProcessingResult',
    'MLAnalyzer',
    'MLAnalysisResult',
]
