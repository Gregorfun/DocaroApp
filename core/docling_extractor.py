"""
Docling-basierte PDF-Dokumentenextraktoren für Docaro.
Nutzt die Docling-Bibliothek für erweiterte Dokumentenverarbeitung.
Integriert docling-core für DoclingDocument, Chunking und Serialization.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Lazy Loading für Docling um Import-Probleme zu vermeiden
DOCLING_AVAILABLE = False
DOCLING_CORE_AVAILABLE = False
DocumentConverter = None
DoclingDocument = None
HybridChunker = None

def _ensure_docling_loaded():
    """Stelle sicher, dass Docling und docling-core geladen sind."""
    global DOCLING_AVAILABLE, DOCLING_CORE_AVAILABLE, DocumentConverter, DoclingDocument, HybridChunker
    if DOCLING_AVAILABLE or DocumentConverter is not None:
        return
    try:
        from docling.document_converter import DocumentConverter as _DC
        DocumentConverter = _DC
        DOCLING_AVAILABLE = True
        _LOGGER.info("Docling erfolgreich geladen")
        
        # Lade auch docling-core Features
        try:
            from docling_core.types.doc import DoclingDocument as _DD
            from docling_core.transforms.chunker import HybridChunker as _HC
            DoclingDocument = _DD
            HybridChunker = _HC
            DOCLING_CORE_AVAILABLE = True
            _LOGGER.info("Docling-core erfolgreich geladen")
        except Exception as e:
            _LOGGER.debug(f"Docling-core optionale Features nicht verfügbar: {e}")
            DOCLING_CORE_AVAILABLE = False
    except Exception as e:
        _LOGGER.debug(f"Docling Import fehlgeschlagen: {e}")
        DOCLING_AVAILABLE = False
        DOCLING_CORE_AVAILABLE = False

try:
    import date_parser  # type: ignore
except ImportError:
    try:
        from core import date_parser  # type: ignore
    except ImportError:
        date_parser = None

from config import Config

config = Config()
from constants import DATE_REGEX_PATTERNS, LABEL_PATTERNS, LABEL_PRIORITY, DATE_LABELS
from utils import first_path_from_env

_LOGGER = logging.getLogger(__name__)

DEFAULT_DATE_FORMAT = "%Y-%m-%d"
INTERNAL_DATE_FORMAT = "%Y-%m-%d"
SUPPLIERS_DB_PATH = config.DATA_DIR / "suppliers.json"


class DoclingExtractor:
    """
    Dokumentenextraktor basierend auf Docling.
    
    Docling bietet:
    - Advanced PDF Layout-Analyse
    - Automatische Tabellenerkennung
    - Bessere Text-Reihenfolge
    - Integrierte OCR-Fähigkeiten
    - Strukturierte Dokumentenrepräsentation
    """

    def __init__(self):
        """Initialisiert den Docling-Extractor."""
        _ensure_docling_loaded()
        
        if not DOCLING_AVAILABLE or DocumentConverter is None:
            raise ImportError(
                "Docling ist nicht installiert. "
                "Installiere mit: pip install docling"
            )
        
        _LOGGER.info("Initialisiere Docling DocumentConverter...")
        try:
            # Erstelle den Converter mit Standard-Einstellungen
            self.converter = DocumentConverter()
            _LOGGER.info("Docling DocumentConverter erfolgreich initialisiert")
        except Exception as e:
            _LOGGER.error(f"Fehler bei Docling-Initialisierung: {e}")
            raise

    def extract_text(self, pdf_path: Path | str) -> str:
        """
        Extrahiert Text aus PDF mit Docling.
        
        Args:
            pdf_path: Pfad zur PDF-Datei
            
        Returns:
            Extrahierter Text
        """
        pdf_path = Path(pdf_path)
        _LOGGER.debug(f"Extrahiere Text aus {pdf_path} mit Docling...")
        
        try:
            # Konvertiere PDF mit Docling
            result = self.converter.convert(str(pdf_path))
            
            # Exportiere zu Markdown (beste Lesbarkeit + Struktur)
            text = result.document.export_to_markdown()
            
            _LOGGER.debug(f"Docling-Extraktion erfolgreich, {len(text)} Zeichen")
            return text
        except Exception as e:
            _LOGGER.error(f"Fehler beim Extrahieren von {pdf_path}: {e}")
            raise

    def extract_text_per_page(self, pdf_path: Path | str) -> Dict[int, str]:
        """
        Extrahiert Text seitenweise aus PDF.
        
        Args:
            pdf_path: Pfad zur PDF-Datei
            
        Returns:
            Dict mit Seitennummern als Keys und Text als Values
        """
        pdf_path = Path(pdf_path)
        _LOGGER.debug(f"Extrahiere Text pro Seite aus {pdf_path}...")
        
        try:
            result = self.converter.convert(str(pdf_path))
            
            # Gruppiere Content nach Seiten
            pages_content = {}
            current_page = 1
            current_text = []
            
            # Iteriere durch die Dokumenten-Blöcke und sammle sie nach Seite
            for block in result.document.blocks:
                if hasattr(block, 'page_index'):
                    page_num = block.page_index + 1  # 0-indexed -> 1-indexed
                    if page_num != current_page:
                        # Neue Seite
                        if current_text:
                            pages_content[current_page] = '\n'.join(current_text)
                        current_page = page_num
                        current_text = []
                
                # Extrahiere Text aus Block
                block_text = self._extract_block_text(block)
                if block_text:
                    current_text.append(block_text)
            
            # Speichere letzte Seite
            if current_text:
                pages_content[current_page] = '\n'.join(current_text)
            
            _LOGGER.debug(f"Extrahierte {len(pages_content)} Seiten")
            return pages_content
        except Exception as e:
            _LOGGER.error(f"Fehler beim seitenweisen Extrahieren von {pdf_path}: {e}")
            raise

    def extract_tables(self, pdf_path: Path | str) -> List[Dict[str, Any]]:
        """
        Extrahiert Tabellen aus PDF mit strukturierter Ausgabe.
        
        Args:
            pdf_path: Pfad zur PDF-Datei
            
        Returns:
            Liste von Tabellen-Daten
        """
        pdf_path = Path(pdf_path)
        _LOGGER.debug(f"Extrahiere Tabellen aus {pdf_path}...")
        
        try:
            result = self.converter.convert(str(pdf_path))
            
            tables = []
            # Docling nutzt TableBlock für Tabellen
            for block in result.document.blocks:
                if hasattr(block, '__class__') and 'Table' in block.__class__.__name__:
                    table_data = self._extract_table_data(block)
                    if table_data:
                        tables.append(table_data)
            
            _LOGGER.debug(f"Extrahierte {len(tables)} Tabellen")
            return tables
        except Exception as e:
            _LOGGER.error(f"Fehler beim Extrahieren von Tabellen aus {pdf_path}: {e}")
            raise

    def extract_metadata(self, pdf_path: Path | str) -> Dict[str, Any]:
        """
        Extrahiert Metadaten aus PDF.
        
        Args:
            pdf_path: Pfad zur PDF-Datei
            
        Returns:
            Dict mit Metadaten
        """
        pdf_path = Path(pdf_path)
        _LOGGER.debug(f"Extrahiere Metadaten aus {pdf_path}...")
        
        try:
            result = self.converter.convert(str(pdf_path))
            
            metadata = {
                'num_pages': len(result.document.pages) if hasattr(result.document, 'pages') else 0,
                'num_blocks': len(result.document.blocks),
                'model_version': str(result.metadata.get('model_version', 'unknown')) 
                    if hasattr(result, 'metadata') else 'unknown',
            }
            
            _LOGGER.debug(f"Metadaten: {metadata}")
            return metadata
        except Exception as e:
            _LOGGER.error(f"Fehler beim Extrahieren von Metadaten aus {pdf_path}: {e}")
            raise

    def extract_date(self, pdf_path: Path | str, supplier: Optional[str] = None) -> Optional[datetime]:
        """
        Versucht, ein Datum aus der PDF zu extrahieren.
        
        Args:
            pdf_path: Pfad zur PDF-Datei
            supplier: Optional: Lieferant für kontextuelle Hinweise
            
        Returns:
            Extrahiertes Datum oder None
        """
        try:
            text = self.extract_text(pdf_path)
            return self._find_date_in_text(text, supplier)
        except Exception as e:
            _LOGGER.error(f"Fehler beim Datums-Extrahieren aus {pdf_path}: {e}")
            return None

    def extract_supplier(self, pdf_path: Path | str) -> Optional[str]:
        """
        Versucht, Lieferanten-Informationen aus PDF zu extrahieren.
        
        Args:
            pdf_path: Pfad zur PDF-Datei
            
        Returns:
            Erkannter Lieferant oder None
        """
        try:
            text = self.extract_text(pdf_path)
            return self._find_supplier_in_text(text)
        except Exception as e:
            _LOGGER.error(f"Fehler beim Lieferanten-Extrahieren aus {pdf_path}: {e}")
            return None

    def export_to_json(self, pdf_path: Path | str) -> Dict[str, Any]:
        """
        Exportiert Dokument als strukturiertes JSON mit docling-core.
        
        Args:
            pdf_path: Pfad zur PDF-Datei
            
        Returns:
            Vollständiges DoclingDocument als JSON-Dict
        """
        pdf_path = Path(pdf_path)
        _LOGGER.debug(f"Exportiere {pdf_path} zu JSON...")
        
        try:
            result = self.converter.convert(str(pdf_path))
            
            # Nutze docling-core's export_to_dict
            if hasattr(result.document, 'export_to_dict'):
                return result.document.export_to_dict()
            else:
                # Fallback: Manuelles JSON-Dict erstellen
                return {
                    'text': self.extract_text(pdf_path),
                    'metadata': self.extract_metadata(pdf_path),
                    'tables': self.extract_tables(pdf_path)
                }
        except Exception as e:
            _LOGGER.error(f"Fehler beim JSON-Export von {pdf_path}: {e}")
            raise

    def chunk_document(self, pdf_path: Path | str, tokenizer: str = "sentence", 
                       max_tokens: int = 512) -> List[Dict[str, Any]]:
        """
        Chunked das Dokument in kleinere Abschnitte für RAG/LLM-Verwendung.
        Nutzt docling-core HybridChunker wenn verfügbar.
        
        Args:
            pdf_path: Pfad zur PDF-Datei
            tokenizer: Tokenizer-Typ ("sentence", "word")
            max_tokens: Maximale Token-Anzahl pro Chunk
            
        Returns:
            Liste von Chunks mit Metadaten
        """
        pdf_path = Path(pdf_path)
        _LOGGER.debug(f"Chunke Dokument {pdf_path}...")
        
        try:
            result = self.converter.convert(str(pdf_path))
            
            if DOCLING_CORE_AVAILABLE and HybridChunker:
                # Nutze HybridChunker von docling-core
                chunker = HybridChunker(
                    tokenizer=tokenizer,
                    max_tokens=max_tokens
                )
                chunks = chunker.chunk(result.document)
                
                return [
                    {
                        'text': chunk.text,
                        'meta': chunk.meta if hasattr(chunk, 'meta') else {},
                        'index': idx
                    }
                    for idx, chunk in enumerate(chunks)
                ]
            else:
                # Fallback: Einfaches Text-Chunking
                text = result.document.export_to_markdown()
                # Simple sentence-based splitting
                sentences = re.split(r'[.!?]\s+', text)
                chunks = []
                current_chunk = []
                current_tokens = 0
                
                for sentence in sentences:
                    sentence_tokens = len(sentence.split())
                    if current_tokens + sentence_tokens > max_tokens and current_chunk:
                        chunks.append({
                            'text': ' '.join(current_chunk),
                            'meta': {},
                            'index': len(chunks)
                        })
                        current_chunk = [sentence]
                        current_tokens = sentence_tokens
                    else:
                        current_chunk.append(sentence)
                        current_tokens += sentence_tokens
                
                if current_chunk:
                    chunks.append({
                        'text': ' '.join(current_chunk),
                        'meta': {},
                        'index': len(chunks)
                    })
                
                return chunks
        except Exception as e:
            _LOGGER.error(f"Fehler beim Chunken von {pdf_path}: {e}")
            raise

    def export_to_html(self, pdf_path: Path | str) -> str:
        """
        Exportiert Dokument als HTML mit docling-core.
        
        Args:
            pdf_path: Pfad zur PDF-Datei
            
        Returns:
            HTML-String
        """
        pdf_path = Path(pdf_path)
        _LOGGER.debug(f"Exportiere {pdf_path} zu HTML...")
        
        try:
            result = self.converter.convert(str(pdf_path))
            
            if hasattr(result.document, 'export_to_html'):
                return result.document.export_to_html()
            else:
                # Fallback: Markdown zu HTML
                markdown_text = result.document.export_to_markdown()
                # Einfache Markdown-zu-HTML-Konvertierung
                html = f"<html><body>{markdown_text}</body></html>"
                return html
        except Exception as e:
            _LOGGER.error(f"Fehler beim HTML-Export von {pdf_path}: {e}")
            raise

    # Private Helper-Methoden

    def _extract_block_text(self, block: Any) -> str:
        """Extrahiert Text aus einem Docling-Block."""
        try:
            if hasattr(block, 'text'):
                return block.text
            elif hasattr(block, 'export_to_markdown'):
                return block.export_to_markdown()
            return ""
        except Exception:
            return ""

    def _extract_table_data(self, table_block: Any) -> Dict[str, Any]:
        """Extrahiert Daten aus einem Tabellen-Block."""
        try:
            table_dict = {
                'type': 'table',
                'bbox': self._get_bbox(table_block),
                'data': []
            }
            
            # Versuche, Tabellen-Struktur zu extrahieren
            if hasattr(table_block, 'export_to_dict'):
                table_dict['data'] = table_block.export_to_dict()
            elif hasattr(table_block, 'text'):
                table_dict['data'] = table_block.text
            
            return table_dict
        except Exception as e:
            _LOGGER.warning(f"Fehler beim Extrahieren von Tabellen-Daten: {e}")
            return {}

    def _get_bbox(self, block: Any) -> Optional[Dict[str, float]]:
        """Extrahiert Bounding Box aus Block."""
        try:
            if hasattr(block, 'bbox'):
                bbox = block.bbox
                return {
                    'x0': bbox.x0,
                    'y0': bbox.y0,
                    'x1': bbox.x1,
                    'y1': bbox.y1
                }
        except Exception:
            pass
        return None

    def _find_date_in_text(self, text: str, supplier: Optional[str] = None) -> Optional[datetime]:
        """
        Findet ein Datum im Text unter Nutzung von regex Patterns.
        """
        if not text:
            return None
        
        # Nutze vorhandene Date Patterns aus constants
        for pattern in DATE_REGEX_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    date_str = match.group(0)
                    if date_parser:
                        parsed = date_parser.parse_date(date_str)
                        if parsed:
                            return parsed
                except Exception:
                    continue
        
        return None

    def _find_supplier_in_text(self, text: str) -> Optional[str]:
        """
        Versucht, einen Lieferanten im Text zu finden.
        """
        if not text:
            return None
        
        try:
            suppliers_path = SUPPLIERS_DB_PATH
            if suppliers_path.exists():
                with open(suppliers_path, 'r', encoding='utf-8') as f:
                    suppliers_data = json.load(f)
                
                # Suche nach Lieferanten im Text
                for supplier_entry in suppliers_data:
                    supplier_name = supplier_entry.get('name', '')
                    if supplier_name and supplier_name.lower() in text.lower():
                        return supplier_name
        except Exception as e:
            _LOGGER.warning(f"Fehler beim Lieferanten-Suchen: {e}")
        
        return None


def is_docling_available() -> bool:
    """Prüft, ob Docling installiert und nutzbar ist."""
    _ensure_docling_loaded()
    return DOCLING_AVAILABLE


def get_extractor() -> Optional[DoclingExtractor]:
    """
    Erstellt und gibt einen DoclingExtractor zurück.
    Gibt None zurück, wenn Docling nicht verfügbar ist.
    """
    _ensure_docling_loaded()
    if not DOCLING_AVAILABLE:
        _LOGGER.warning("Docling nicht verfügbar")
        return None
    
    try:
        return DoclingExtractor()
    except Exception as e:
        _LOGGER.error(f"Fehler beim Erstellen des Docling Extractors: {e}")
        return None
