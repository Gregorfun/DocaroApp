"""
Haupt-Pipeline-Orchestrator für Docaro.

Integriert alle Komponenten:
1. Qualitätsprüfung
2. OCR (falls nötig)
3. Docling-Verarbeitung
4. ML-Analyse
5. Finalisierung
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_LOGGER = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Ergebnis der kompletten Pipeline."""
    
    success: bool
    status: str  # "success", "quarantine", "error"
    
    # Extrahierte Informationen
    supplier: Optional[str] = None
    supplier_confidence: float = 0.0
    
    date: Optional[str] = None
    date_confidence: float = 0.0
    
    document_type: Optional[str] = None
    doctype_confidence: float = 0.0
    
    # Pfade
    original_path: Optional[Path] = None
    final_path: Optional[Path] = None
    
    # Zwischenergebnisse
    ocr_used: bool = False
    ocr_method: Optional[str] = None
    
    tables_found: int = 0
    layout_elements: int = 0
    
    # Metadaten
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    processing_time: float = 0.0
    
    # Für ML-Training
    needs_review: bool = False
    review_reason: Optional[str] = None


class DocumentPipeline:
    """
    Haupt-Pipeline für Dokumentenverarbeitung.
    
    **Workflow**:
    1. Qualitätsprüfung → OCR falls nötig
    2. Docling-Extraktion → Strukturierte Daten
    3. ML-Analyse → Lieferant, Datum, Dokumenttyp
    4. Konfidenz-Check → Quarantäne bei Unsicherheit
    5. Finalisierung → Umbenennung & Verschiebung
    """
    
    def __init__(
        self,
        quarantine_threshold_supplier: float = 0.85,
        quarantine_threshold_date: float = 0.75,
        use_vector_db: bool = False
    ):
        """
        Args:
            quarantine_threshold_supplier: Min. Confidence für Lieferant
            quarantine_threshold_date: Min. Confidence für Datum
            use_vector_db: Semantische Embeddings speichern
        """
        self.quarantine_threshold_supplier = quarantine_threshold_supplier
        self.quarantine_threshold_date = quarantine_threshold_date
        self.use_vector_db = use_vector_db
        
        # Lazy-Loading der Prozessoren
        self._quality_checker = None
        self._ocr_processor = None
        self._docling_processor = None
        self._ml_analyzer = None
        self._vector_service = None
    
    def process_document(self, pdf_path: Path, config: Optional[Dict] = None) -> PipelineResult:
        """
        Verarbeitet ein einzelnes Dokument durch die komplette Pipeline.
        
        Args:
            pdf_path: Pfad zur PDF
            config: Optionale Konfigurations-Overrides
        
        Returns:
            PipelineResult mit allen extrahierten Daten
        """
        import time
        start_time = time.time()
        
        _LOGGER.info(f"🚀 Starte Pipeline für: {pdf_path.name}")
        
        try:
            # ═══════════════════════════════════════════════════════
            # SCHRITT 1: QUALITÄTSPRÜFUNG
            # ═══════════════════════════════════════════════════════
            _LOGGER.info("📊 Schritt 1: Qualitätsprüfung")
            
            from pipelines.document_processor import DoclingQualityChecker
            
            quality = DoclingQualityChecker.assess_pdf_quality(pdf_path)
            _LOGGER.info(f"   Qualität: OCR nötig={quality['needs_ocr']}, "
                        f"Text-Coverage={quality['text_coverage']:.2f}")
            
            # ═══════════════════════════════════════════════════════
            # SCHRITT 2: OCR (falls nötig)
            # ═══════════════════════════════════════════════════════
            ocr_used = False
            ocr_method = None
            processed_pdf = pdf_path
            
            if quality['needs_ocr']:
                _LOGGER.info("🔍 Schritt 2: OCR-Verarbeitung")
                
                from pipelines.ocr_processor import process_with_ocr
                
                ocr_result = process_with_ocr(
                    pdf_path,
                    method=config.get('ocr_method', 'auto') if config else 'auto'
                )
                
                if ocr_result.success:
                    ocr_used = True
                    ocr_method = ocr_result.method
                    
                    if ocr_result.output_path:
                        processed_pdf = ocr_result.output_path
                    
                    _LOGGER.info(f"   OCR erfolgreich mit {ocr_method} "
                               f"(Conf: {ocr_result.confidence:.2f})")
                else:
                    _LOGGER.warning(f"   OCR fehlgeschlagen: {ocr_result.error}")
                    # Fahre trotzdem fort, vielleicht kann Docling was extrahieren
            
            # ═══════════════════════════════════════════════════════
            # SCHRITT 3: DOCLING-VERARBEITUNG
            # ═══════════════════════════════════════════════════════
            _LOGGER.info("📄 Schritt 3: Docling-Verarbeitung")
            
            from pipelines.document_processor import DoclingProcessor
            
            docling_processor = DoclingProcessor()
            docling_result = docling_processor.process(
                processed_pdf,
                extract_tables=True,
                extract_layout=True,
                chunk_text=True
            )
            
            if not docling_result.success:
                return PipelineResult(
                    success=False,
                    status="error",
                    original_path=pdf_path,
                    error=f"Docling-Verarbeitung fehlgeschlagen: {docling_result.error}",
                    processing_time=time.time() - start_time
                )
            
            _LOGGER.info(f"   Docling: {len(docling_result.tables)} Tabellen, "
                        f"{len(docling_result.layout_elements)} Layout-Elemente")
            
            # ═══════════════════════════════════════════════════════
            # SCHRITT 4: ML-ANALYSE
            # ═══════════════════════════════════════════════════════
            _LOGGER.info("🤖 Schritt 4: ML-Analyse")
            
            from pipelines.ml_analyzer import MLAnalyzer
            from core.audit_logger import AuditLogger, FieldExtraction
            
            ml_analyzer = MLAnalyzer()
            ml_result = ml_analyzer.analyze(docling_result)
            
            _LOGGER.info(f"   Lieferant: {ml_result.supplier} (Conf: {ml_result.supplier_confidence:.2f})")
            _LOGGER.info(f"   Datum: {ml_result.date} (Conf: {ml_result.date_confidence:.2f})")
            _LOGGER.info(f"   Dokumenttyp: {ml_result.document_type} (Conf: {ml_result.doctype_confidence:.2f})")
            
            # Audit-Logging für Erklärbarkeit
            from config import Config
            audit_logger = AuditLogger(Config.DATA_DIR / "audit.jsonl")
            
            extractions = {}
            if ml_result.supplier:
                extractions["supplier"] = audit_logger.log_extraction(
                    document_path=pdf_path,
                    field_name="supplier",
                    value=ml_result.supplier,
                    confidence=ml_result.supplier_confidence,
                    page=0,
                    text_snippet=ml_result.metadata.get("supplier_text", ""),
                    reasons=ml_result.metadata.get("supplier_reasons", [])
                )
            if ml_result.date:
                extractions["date"] = audit_logger.log_extraction(
                    document_path=pdf_path,
                    field_name="date",
                    value=ml_result.date,
                    confidence=ml_result.date_confidence,
                    page=0,
                    text_snippet=ml_result.metadata.get("date_text", ""),
                    reasons=ml_result.metadata.get("date_reasons", [])
                )
            if ml_result.document_type:
                extractions["document_type"] = audit_logger.log_extraction(
                    document_path=pdf_path,
                    field_name="document_type",
                    value=ml_result.document_type,
                    confidence=ml_result.doctype_confidence,
                    page=0,
                    text_snippet="",
                    reasons=ml_result.metadata.get("doctype_reasons", [])
                )
            
            # ═══════════════════════════════════════════════════════
            # SCHRITT 5: SEMANTISCHE EMBEDDINGS (optional)
            # ═══════════════════════════════════════════════════════
            embedding_id = None
            
            if self.use_vector_db:
                _LOGGER.info("🔎 Schritt 5: Semantische Embeddings")
                
                try:
                    from services.vector_service import store_embeddings
                    
                    embedding_id = store_embeddings(
                        text=docling_result.text,
                        metadata={
                            'supplier': ml_result.supplier,
                            'date': ml_result.date,
                            'document_type': ml_result.document_type,
                            'filename': pdf_path.name
                        }
                    )
                    _LOGGER.info(f"   Embedding gespeichert: {embedding_id}")
                
                except Exception as e:
                    _LOGGER.warning(f"   Embedding-Speicherung fehlgeschlagen: {e}")
            
            # ═══════════════════════════════════════════════════════
            # SCHRITT 6: KONFIDENZ-CHECK → QUARANTÄNE?
            # ═══════════════════════════════════════════════════════
            needs_review = False
            review_reason = None
            status = "success"
            
            if not ml_result.supplier or ml_result.supplier_confidence < self.quarantine_threshold_supplier:
                needs_review = True
                review_reason = f"Lieferant unsicher (Conf: {ml_result.supplier_confidence:.2f})"
                status = "quarantine"
            
            elif not ml_result.date or ml_result.date_confidence < self.quarantine_threshold_date:
                needs_review = True
                review_reason = f"Datum unsicher (Conf: {ml_result.date_confidence:.2f})"
                status = "quarantine"
            
            if needs_review:
                _LOGGER.warning(f"⚠️  Quarantäne: {review_reason}")
                
                # Verschiebe in Quarantäne
                from core.quarantine_manager import QuarantineManager
                qm = QuarantineManager(
                    quarantine_dir=Config.QUARANTINE_DIR,
                    quarantine_log=Config.DATA_DIR / "quarantine.jsonl"
                )
                
                qm.add_to_quarantine(
                    pdf_path=pdf_path,
                    reason=review_reason,
                    supplier=ml_result.supplier,
                    supplier_confidence=ml_result.supplier_confidence,
                    date=ml_result.date,
                    date_confidence=ml_result.date_confidence,
                    document_type=ml_result.document_type,
                    doctype_confidence=ml_result.doctype_confidence
                )
            
            # Audit-Eintrag speichern
            audit_entry = audit_logger.create_audit_entry(
                document_path=pdf_path,
                extractions=extractions,
                status=status,
                ocr_method=ocr_method,
                processing_time=time.time() - start_time,
                needs_review=needs_review,
                review_reason=review_reason
            )
            audit_logger.save_audit_entry(audit_entry)
            
            # ═══════════════════════════════════════════════════════
            # SCHRITT 7: METADATEN & ERGEBNIS
            # ═══════════════════════════════════════════════════════
            processing_time = time.time() - start_time
            
            result = PipelineResult(
                success=True,
                status=status,
                supplier=ml_result.supplier,
                supplier_confidence=ml_result.supplier_confidence,
                date=ml_result.date,
                date_confidence=ml_result.date_confidence,
                document_type=ml_result.document_type,
                doctype_confidence=ml_result.doctype_confidence,
                original_path=pdf_path,
                ocr_used=ocr_used,
                ocr_method=ocr_method,
                tables_found=len(docling_result.tables),
                layout_elements=len(docling_result.layout_elements),
                needs_review=needs_review,
                review_reason=review_reason,
                metadata={
                    'quality': quality,
                    'docling_metadata': docling_result.metadata,
                    'embedding_id': embedding_id,
                    'processed_at': datetime.now().isoformat()
                },
                processing_time=processing_time
            )
            
            _LOGGER.info(f"✅ Pipeline abgeschlossen in {processing_time:.2f}s - Status: {status}")
            
            return result
        
        except Exception as e:
            _LOGGER.error(f"❌ Pipeline-Fehler: {e}", exc_info=True)
            return PipelineResult(
                success=False,
                status="error",
                original_path=pdf_path,
                error=str(e),
                processing_time=time.time() - start_time
            )


# Beispiel-Nutzung
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    pipeline = DocumentPipeline(
        quarantine_threshold_supplier=0.85,
        quarantine_threshold_date=0.75,
        use_vector_db=False  # Aktiviere für semantische Suche
    )
    
    test_pdf = Path("test_document.pdf")
    
    if test_pdf.exists():
        result = pipeline.process_document(test_pdf)
        
        print("\n" + "="*60)
        print("PIPELINE-ERGEBNIS")
        print("="*60)
        print(f"Status: {result.status}")
        print(f"Lieferant: {result.supplier} (Conf: {result.supplier_confidence:.2f})")
        print(f"Datum: {result.date} (Conf: {result.date_confidence:.2f})")
        print(f"Dokumenttyp: {result.document_type} (Conf: {result.doctype_confidence:.2f})")
        print(f"OCR verwendet: {result.ocr_used} ({result.ocr_method})")
        print(f"Tabellen: {result.tables_found}")
        print(f"Verarbeitungszeit: {result.processing_time:.2f}s")
        
        if result.needs_review:
            print(f"\n⚠️  REVIEW NÖTIG: {result.review_reason}")
        
        print("="*60)
