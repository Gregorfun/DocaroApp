"""
Docling Document Processor für erweiterte PDF-Verarbeitung.

Integriert:
- Docling: PDF → DoclingDocument mit Layout-Analyse
- Docling-Core: Strukturierte Repräsentation, Chunking, Serialization
- Docling-Serve: Optional für API-basierte Verarbeitung
- Docling-Agent: Optional für automatisierte Workflows
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


@dataclass
class TableData:
    """Extrahierte Tabellendaten."""
    
    page: int
    bbox: Tuple[float, float, float, float]  # (x1, y1, x2, y2)
    rows: List[List[str]]
    columns: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class LayoutElement:
    """Layout-Element (Header, Footer, Section, etc.)."""
    
    element_type: str  # "header", "footer", "section", "paragraph", etc.
    text: str
    page: int
    bbox: Optional[Tuple[float, float, float, float]] = None
    level: int = 0  # Hierarchie-Ebene (für Sections)


@dataclass
class DoclingProcessingResult:
    """Ergebnis der Docling-Verarbeitung."""
    
    success: bool
    text: str = ""
    tables: List[TableData] = field(default_factory=list)
    layout_elements: List[LayoutElement] = field(default_factory=list)
    chunks: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    docling_document: Optional[Any] = None  # DoclingDocument-Objekt
    error: Optional[str] = None
    processing_time: float = 0.0


class DoclingProcessor:
    """
    Haupt-Processor für Docling-basierte Dokumentenverarbeitung.
    
    **Nutzen**:
    - Layout-Analyse: Erkennt Header, Footer, Sections
    - Tabellen-Extraktion: Automatische Strukturierung
    - Text-Chunking: Intelligent segmentierte Textblöcke
    - Export: JSON, Markdown, HTML
    
    **Docling-Features**:
    - DocumentConverter: PDF → DoclingDocument
    - Layout-Recognition: Automatische Seitenlayout-Analyse
    - Table-Detection: ML-basierte Tabellenerkennung
    
    **Offline**: ✅ Vollständig lokal (Modelle werden beim ersten Start geladen)
    """
    
    def __init__(self):
        """Initialisiere Docling-Processor."""
        self._converter = None
        self._chunker = None
    
    def _get_converter(self):
        """Lazy-Loading für DocumentConverter."""
        if self._converter is not None:
            return self._converter
        
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            raise ImportError(
                "Docling ist nicht installiert. "
                "Installiere mit: pip install docling"
            )
        
        _LOGGER.info("Initialisiere Docling DocumentConverter...")
        self._converter = DocumentConverter()
        return self._converter
    
    def _get_chunker(self):
        """Lazy-Loading für HybridChunker (docling-core)."""
        if self._chunker is not None:
            return self._chunker
        
        try:
            from docling_core.transforms.chunker import HybridChunker
        except ImportError:
            _LOGGER.warning("docling-core nicht verfügbar, Chunking deaktiviert")
            return None
        
        _LOGGER.info("Initialisiere HybridChunker...")
        self._chunker = HybridChunker()
        return self._chunker
    
    def process(
        self,
        pdf_path: Path,
        extract_tables: bool = True,
        extract_layout: bool = True,
        chunk_text: bool = True,
        max_chunk_size: int = 512
    ) -> DoclingProcessingResult:
        """
        Verarbeitet PDF mit Docling.
        
        Args:
            pdf_path: Pfad zur PDF
            extract_tables: Tabellen extrahieren
            extract_layout: Layout-Elemente extrahieren
            chunk_text: Text in Chunks aufteilen
            max_chunk_size: Maximale Chunk-Größe in Tokens
        
        Returns:
            DoclingProcessingResult mit extrahierten Daten
        """
        import time
        start_time = time.time()
        
        _LOGGER.info(f"Starte Docling-Verarbeitung: {pdf_path.name}")
        
        try:
            converter = self._get_converter()
            
            # PDF konvertieren
            _LOGGER.debug("Konvertiere PDF zu DoclingDocument...")
            conversion_result = converter.convert(str(pdf_path))
            
            # DoclingDocument extrahieren
            docling_doc = conversion_result.document
            
            # Text extrahieren
            full_text = docling_doc.export_to_markdown()
            
            # Single-pass extraction for tables and layout (optimized)
            tables = []
            layout_elements = []
            if extract_tables or extract_layout:
                tables, layout_elements = self._extract_elements_single_pass(
                    docling_doc, 
                    extract_tables=extract_tables,
                    extract_layout=extract_layout
                )
                if extract_tables:
                    _LOGGER.info(f"  → {len(tables)} Tabellen extrahiert")
                if extract_layout:
                    _LOGGER.info(f"  → {len(layout_elements)} Layout-Elemente extrahiert")
            
            # Text-Chunking
            chunks = []
            if chunk_text:
                chunks = self._chunk_text(docling_doc, max_chunk_size)
                _LOGGER.info(f"  → {len(chunks)} Chunks erstellt")
            
            # Metadaten
            metadata = self._extract_metadata(docling_doc)
            
            processing_time = time.time() - start_time
            
            _LOGGER.info(f"Docling-Verarbeitung abgeschlossen ({processing_time:.2f}s)")
            
            return DoclingProcessingResult(
                success=True,
                text=full_text,
                tables=tables,
                layout_elements=layout_elements,
                chunks=chunks,
                metadata=metadata,
                docling_document=docling_doc,
                processing_time=processing_time
            )
        
        except Exception as e:
            _LOGGER.error(f"Docling-Verarbeitung fehlgeschlagen: {e}")
            return DoclingProcessingResult(
                success=False,
                error=str(e),
                processing_time=time.time() - start_time
            )
    
    def _extract_elements_single_pass(
        self, 
        docling_doc, 
        extract_tables: bool = True,
        extract_layout: bool = True
    ) -> Tuple[List[TableData], List[LayoutElement]]:
        """
        Extrahiert Tabellen und Layout-Elemente in einem Durchgang (optimiert).
        
        Vermeidet mehrfache Iteration über docling_doc.pages für bessere Performance.
        """
        tables = []
        layout_elements = []
        
        try:
            # Single pass über alle Pages und Elements
            for page_num, page in enumerate(docling_doc.pages):
                for element in page.elements:
                    # Tabellen extrahieren
                    if extract_tables and element.label == "table":
                        table_data = self._parse_table_element(element, page_num)
                        if table_data:
                            tables.append(table_data)
                    
                    # Layout-Elemente extrahieren
                    if extract_layout:
                        element_type = element.label.lower()
                        text = element.text if hasattr(element, 'text') else ""
                        
                        # Bbox
                        bbox = None
                        if hasattr(element, 'bbox'):
                            bbox = (element.bbox.x1, element.bbox.y1, element.bbox.x2, element.bbox.y2)
                        
                        # Level (für Sections/Headers)
                        level = 0
                        if element_type.startswith('heading'):
                            try:
                                level = int(element_type.split('_')[-1])
                            except (ValueError, IndexError):
                                level = 1
                        
                        layout_elements.append(LayoutElement(
                            element_type=element_type,
                            text=text,
                            page=page_num,
                            bbox=bbox,
                            level=level
                        ))
        
        except Exception as e:
            _LOGGER.warning(f"Element-Extraktion fehlgeschlagen: {e}")
        
        return tables, layout_elements
    
    def _extract_tables(self, docling_doc) -> List[TableData]:
        """Extrahiert Tabellen aus DoclingDocument."""
        tables = []
        
        try:
            # Docling-API: Iteriere über alle Elemente
            for page_num, page in enumerate(docling_doc.pages):
                for element in page.elements:
                    if element.label == "table":
                        # Extrahiere Tabellendaten
                        table_data = self._parse_table_element(element, page_num)
                        if table_data:
                            tables.append(table_data)
        except Exception as e:
            _LOGGER.warning(f"Tabellen-Extraktion fehlgeschlagen: {e}")
        
        return tables
    
    def _parse_table_element(self, element, page_num: int) -> Optional[TableData]:
        """Parse einzelnes Tabellen-Element."""
        try:
            # Extrahiere Tabellenstruktur
            rows = []
            
            # Docling speichert Tabellen als strukturierte Daten
            if hasattr(element, 'cells'):
                # Grid-basierte Tabelle
                grid = {}
                for cell in element.cells:
                    row_idx = cell.row
                    col_idx = cell.col
                    if row_idx not in grid:
                        grid[row_idx] = {}
                    grid[row_idx][col_idx] = cell.text
                
                # Konvertiere zu Liste
                for row_idx in sorted(grid.keys()):
                    row = [grid[row_idx].get(col_idx, "") for col_idx in sorted(grid[row_idx].keys())]
                    rows.append(row)
            
            elif hasattr(element, 'text'):
                # Fallback: Parse Text
                lines = element.text.split('\n')
                rows = [line.split('\t') for line in lines if line.strip()]
            
            # Bbox (Bounding Box)
            bbox = None
            if hasattr(element, 'bbox'):
                bbox = (element.bbox.x1, element.bbox.y1, element.bbox.x2, element.bbox.y2)
            
            # Spalten (erste Zeile als Header)
            columns = rows[0] if rows else []
            
            return TableData(
                page=page_num,
                bbox=bbox,
                rows=rows,
                columns=columns,
                confidence=0.9  # Docling hat keine explizite Confidence
            )
        
        except Exception as e:
            _LOGGER.debug(f"Fehler beim Parsen der Tabelle: {e}")
            return None
    
    def _extract_layout_elements(self, docling_doc) -> List[LayoutElement]:
        """Extrahiert Layout-Elemente (Header, Footer, Sections)."""
        elements = []
        
        try:
            for page_num, page in enumerate(docling_doc.pages):
                for element in page.elements:
                    # Element-Typ mapping
                    element_type = element.label.lower()
                    
                    # Extrahiere Text
                    text = element.text if hasattr(element, 'text') else ""
                    
                    # Bbox
                    bbox = None
                    if hasattr(element, 'bbox'):
                        bbox = (element.bbox.x1, element.bbox.y1, element.bbox.x2, element.bbox.y2)
                    
                    # Level (für Sections/Headers)
                    level = 0
                    if element_type.startswith('heading'):
                        # heading_1 → level 1
                        try:
                            level = int(element_type.split('_')[-1])
                        except:
                            level = 1
                    
                    elements.append(LayoutElement(
                        element_type=element_type,
                        text=text,
                        page=page_num,
                        bbox=bbox,
                        level=level
                    ))
        
        except Exception as e:
            _LOGGER.warning(f"Layout-Extraktion fehlgeschlagen: {e}")
        
        return elements
    
    def _chunk_text(self, docling_doc, max_chunk_size: int) -> List[str]:
        """Chunked Text mit HybridChunker (docling-core)."""
        chunker = self._get_chunker()
        
        if chunker is None:
            # Fallback: Einfaches Chunking
            text = docling_doc.export_to_markdown()
            words = text.split()
            chunks = []
            current_chunk = []
            current_size = 0
            
            for word in words:
                if current_size + len(word) > max_chunk_size:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = [word]
                    current_size = len(word)
                else:
                    current_chunk.append(word)
                    current_size += len(word) + 1  # +1 for space
            
            if current_chunk:
                chunks.append(" ".join(current_chunk))
            
            return chunks
        
        try:
            # Nutze HybridChunker für intelligentes Chunking
            chunks = list(chunker.chunk(docling_doc))
            return [chunk.text for chunk in chunks]
        
        except Exception as e:
            _LOGGER.warning(f"HybridChunker fehlgeschlagen: {e}")
            # Fallback
            return [docling_doc.export_to_markdown()]
    
    def _extract_metadata(self, docling_doc) -> Dict[str, Any]:
        """Extrahiert Metadaten aus DoclingDocument."""
        metadata = {}
        
        try:
            # Seitenanzahl
            metadata['page_count'] = len(docling_doc.pages)
            
            # Tabellen-Anzahl
            table_count = 0
            for page in docling_doc.pages:
                for element in page.elements:
                    if element.label == "table":
                        table_count += 1
            metadata['table_count'] = table_count
            
            # Element-Typen
            element_types = {}
            for page in docling_doc.pages:
                for element in page.elements:
                    label = element.label
                    element_types[label] = element_types.get(label, 0) + 1
            metadata['element_types'] = element_types
            
            # Text-Statistiken
            text = docling_doc.export_to_markdown()
            metadata['text_length'] = len(text)
            metadata['word_count'] = len(text.split())
        
        except Exception as e:
            _LOGGER.warning(f"Metadaten-Extraktion fehlgeschlagen: {e}")
        
        return metadata
    
    def export_to_json(self, docling_doc, output_path: Path):
        """Exportiert DoclingDocument als JSON."""
        try:
            # Docling-Core: Serialization
            from docling_core.types.doc import DoclingDocument
            
            json_str = docling_doc.export_to_dict()
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(json_str, f, ensure_ascii=False, indent=2)
            
            _LOGGER.info(f"Exportiert nach JSON: {output_path}")
        
        except Exception as e:
            _LOGGER.error(f"JSON-Export fehlgeschlagen: {e}")
    
    def export_to_markdown(self, docling_doc, output_path: Path):
        """Exportiert DoclingDocument als Markdown."""
        try:
            markdown = docling_doc.export_to_markdown()
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(markdown)
            
            _LOGGER.info(f"Exportiert nach Markdown: {output_path}")
        
        except Exception as e:
            _LOGGER.error(f"Markdown-Export fehlgeschlagen: {e}")


class DoclingQualityChecker:
    """
    Prüft PDF-Qualität und entscheidet, ob OCR nötig ist.
    
    **Nutzen**:
    - Erkennt native PDFs (mit Text-Layer)
    - Erkennt gescannte PDFs (nur Bilder)
    - Bewertet Text-Coverage und Bildqualität
    """
    
    @staticmethod
    def assess_pdf_quality(pdf_path: Path) -> Dict[str, Any]:
        """
        Bewertet PDF-Qualität.
        
        Returns:
            Dict mit:
            - needs_ocr: bool
            - has_text: bool
            - text_coverage: float (0-1)
            - is_scanned: bool
            - page_count: int
        """
        import pdfplumber
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                page_count = len(pdf.pages)
                
                # Prüfe erste Seite auf Text
                first_page = pdf.pages[0]
                text = first_page.extract_text()
                
                has_text = bool(text and len(text.strip()) > 50)
                
                # Text-Coverage: Wie viel Fläche ist mit Text bedeckt?
                # (Näherung über Zeichen-Anzahl)
                text_coverage = 0.0
                if has_text:
                    # Grobe Schätzung: >500 Zeichen = gute Coverage
                    text_coverage = min(len(text) / 500, 1.0)
                
                # Ist es ein Scan? (wenig Text, viele Bilder)
                images = first_page.images
                is_scanned = len(images) > 0 and not has_text
                
                needs_ocr = is_scanned or text_coverage < 0.3
                
                return {
                    'needs_ocr': needs_ocr,
                    'has_text': has_text,
                    'text_coverage': text_coverage,
                    'is_scanned': is_scanned,
                    'page_count': page_count,
                    'image_count': len(images)
                }
        
        except Exception as e:
            _LOGGER.error(f"PDF-Qualitätsprüfung fehlgeschlagen: {e}")
            return {
                'needs_ocr': True,  # Im Zweifel OCR
                'has_text': False,
                'text_coverage': 0.0,
                'is_scanned': True,
                'page_count': 0,
                'error': str(e)
            }


# Beispiel-Nutzung
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    test_pdf = Path("test_document.pdf")
    
    if test_pdf.exists():
        # 1. Qualitätsprüfung
        quality = DoclingQualityChecker.assess_pdf_quality(test_pdf)
        print(f"📊 Qualität: {quality}")
        
        # 2. Docling-Verarbeitung
        processor = DoclingProcessor()
        result = processor.process(test_pdf)
        
        if result.success:
            print(f"\n✅ Docling erfolgreich:")
            print(f"   Text-Länge: {len(result.text)} Zeichen")
            print(f"   Tabellen: {len(result.tables)}")
            print(f"   Layout-Elemente: {len(result.layout_elements)}")
            print(f"   Chunks: {len(result.chunks)}")
            print(f"   Verarbeitungszeit: {result.processing_time:.2f}s")
            
            # 3. Export
            processor.export_to_markdown(result.docling_document, test_pdf.with_suffix('.md'))
            processor.export_to_json(result.docling_document, test_pdf.with_suffix('.json'))
        else:
            print(f"❌ Fehler: {result.error}")
