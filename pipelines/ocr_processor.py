"""
OCR-Processor für Docaro Pipeline.

Unterstützt:
- OCRmyPDF (primär): Macht gescannte PDFs durchsuchbar
- PaddleOCR: Hochpräzise OCR für schwierige Fälle
- EasyOCR: Fallback-Option

Alle Methoden funktionieren offline/lokal.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

_LOGGER = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """Ergebnis einer OCR-Verarbeitung."""
    
    success: bool
    output_path: Optional[Path] = None
    text: Optional[str] = None
    method: Optional[str] = None
    confidence: float = 0.0
    error: Optional[str] = None
    processing_time: float = 0.0


class OCRmyPDFProcessor:
    """
    Wrapper für OCRmyPDF.
    
    **Nutzen**:
    - Fügt Text-Layer zu gescannten PDFs hinzu
    - Macht PDFs durchsuchbar
    - Optimiert PDF-Größe
    - Integriert Tesseract OCR
    
    **Offline**: ✅ Vollständig lokal (benötigt ocrmypdf + tesseract)
    
    **Installation**:
    ```bash
    pip install ocrmypdf
    # Windows: Tesseract separat installieren
    # Linux: apt-get install tesseract-ocr tesseract-ocr-deu
    ```
    """
    
    def __init__(
        self,
        language: str = "deu",
        deskew: bool = True,
        optimize: int = 1,
        force_ocr: bool = False
    ):
        """
        Args:
            language: Tesseract-Sprache (deu, eng, etc.)
            deskew: Automatische Drehung/Begradigung
            optimize: Optimierungslevel (0-3)
            force_ocr: OCR auch auf PDFs mit Text anwenden
        """
        self.language = language
        self.deskew = deskew
        self.optimize = optimize
        self.force_ocr = force_ocr
    
    def process(self, pdf_path: Path, output_path: Optional[Path] = None) -> OCRResult:
        """
        Verarbeitet PDF mit OCRmyPDF.
        
        Args:
            pdf_path: Pfad zur Eingabe-PDF
            output_path: Pfad zur Ausgabe-PDF (optional, default: input_ocr.pdf)
        
        Returns:
            OCRResult mit Status und Pfad
        """
        import time
        start_time = time.time()
        
        if output_path is None:
            output_path = pdf_path.parent / f"{pdf_path.stem}_ocr.pdf"
        
        try:
            import ocrmypdf
        except ImportError:
            return OCRResult(
                success=False,
                error="OCRmyPDF ist nicht installiert. Installiere mit: pip install ocrmypdf",
                processing_time=time.time() - start_time
            )
        
        _LOGGER.info(f"Starte OCRmyPDF für {pdf_path.name}")
        
        try:
            # OCRmyPDF API-Aufruf
            result = ocrmypdf.ocr(
                input_file=str(pdf_path),
                output_file=str(output_path),
                language=self.language,
                deskew=self.deskew,
                optimize=self.optimize,
                force_ocr=self.force_ocr,
                skip_text=not self.force_ocr,
                redo_ocr=False,  # Bestehenden Text beibehalten
                progress_bar=False,
            )
            
            processing_time = time.time() - start_time
            
            if result == 0 or result == 6:  # 0=success, 6=already has text
                _LOGGER.info(f"OCRmyPDF erfolgreich: {output_path.name} ({processing_time:.2f}s)")
                return OCRResult(
                    success=True,
                    output_path=output_path,
                    method="ocrmypdf",
                    confidence=0.9,  # OCRmyPDF hat keine explizite Confidence
                    processing_time=processing_time
                )
            else:
                return OCRResult(
                    success=False,
                    error=f"OCRmyPDF Fehlercode: {result}",
                    processing_time=processing_time
                )
        
        except Exception as e:
            _LOGGER.error(f"OCRmyPDF Fehler: {e}")
            return OCRResult(
                success=False,
                error=str(e),
                processing_time=time.time() - start_time
            )


class PaddleOCRProcessor:
    """
    Wrapper für PaddleOCR.
    
    **Nutzen**:
    - Hochpräzise OCR für 100+ Sprachen
    - Gut für Handschrift, schlechte Qualität
    - Automatische Text-Rotation
    - GPU-Support für schnellere Verarbeitung
    
    **Offline**: ✅ Modelle werden beim ersten Start heruntergeladen, dann lokal
    
    **Installation**:
    ```bash
    pip install paddlepaddle paddleocr
    # Optional GPU-Support: paddlepaddle-gpu
    ```
    """
    
    def __init__(
        self,
        lang: str = "german",
        use_angle_cls: bool = True,
        use_gpu: bool = False
    ):
        """
        Args:
            lang: Sprache (german, en, ch, etc.)
            use_angle_cls: Automatische Rotation
            use_gpu: GPU-Beschleunigung
        """
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self.use_gpu = use_gpu
        self._ocr = None
    
    def _get_ocr(self):
        """Lazy-Loading für PaddleOCR (verhindert Import-Fehler)."""
        if self._ocr is not None:
            return self._ocr
        
        try:
            from paddleocr import PaddleOCR
        except ImportError:
            raise ImportError(
                "PaddleOCR ist nicht installiert. "
                "Installiere mit: pip install paddlepaddle paddleocr"
            )
        
        _LOGGER.info("Initialisiere PaddleOCR...")
        self._ocr = PaddleOCR(
            lang=self.lang,
            use_angle_cls=self.use_angle_cls,
            use_gpu=self.use_gpu,
            show_log=False
        )
        return self._ocr
    
    def process_image(self, image_path: Path) -> OCRResult:
        """
        OCR auf einzelnem Bild.
        
        Args:
            image_path: Pfad zum Bild
        
        Returns:
            OCRResult mit Text und Confidence
        """
        import time
        start_time = time.time()
        
        ocr = self._get_ocr()
        
        try:
            result = ocr.ocr(str(image_path), cls=self.use_angle_cls)
            
            if not result or not result[0]:
                return OCRResult(
                    success=False,
                    error="Kein Text erkannt",
                    processing_time=time.time() - start_time
                )
            
            # PaddleOCR gibt Liste von [bbox, (text, confidence)] zurück
            lines = []
            confidences = []
            
            for line in result[0]:
                text, conf = line[1]
                lines.append(text)
                confidences.append(conf)
            
            full_text = "\n".join(lines)
            avg_confidence = np.mean(confidences) if confidences else 0.0
            
            _LOGGER.info(f"PaddleOCR: {len(lines)} Zeilen, Conf: {avg_confidence:.2f}")
            
            return OCRResult(
                success=True,
                text=full_text,
                method="paddleocr",
                confidence=float(avg_confidence),
                processing_time=time.time() - start_time
            )
        
        except Exception as e:
            _LOGGER.error(f"PaddleOCR Fehler: {e}")
            return OCRResult(
                success=False,
                error=str(e),
                processing_time=time.time() - start_time
            )
    
    def process_pdf(self, pdf_path: Path, max_pages: int = 5) -> OCRResult:
        """
        OCR auf PDF (konvertiert zu Bildern).
        
        Args:
            pdf_path: Pfad zur PDF
            max_pages: Maximale Seitenanzahl für OCR
        
        Returns:
            OCRResult mit kombiniertem Text
        """
        import time
        start_time = time.time()
        
        try:
            from pdf2image import convert_from_path
        except ImportError:
            return OCRResult(
                success=False,
                error="pdf2image ist nicht installiert",
                processing_time=time.time() - start_time
            )
        
        try:
            # PDF zu Bildern konvertieren
            _LOGGER.info(f"Konvertiere PDF zu Bildern: {pdf_path.name}")
            images = convert_from_path(pdf_path, dpi=300, last_page=max_pages)
            
            ocr = self._get_ocr()
            all_text = []
            all_confidences = []
            
            for i, img in enumerate(images):
                _LOGGER.debug(f"OCR Seite {i+1}/{len(images)}")
                
                # Konvertiere PIL zu numpy
                img_array = np.array(img)
                
                result = ocr.ocr(img_array, cls=self.use_angle_cls)
                
                if result and result[0]:
                    for line in result[0]:
                        text, conf = line[1]
                        all_text.append(text)
                        all_confidences.append(conf)
            
            full_text = "\n".join(all_text)
            avg_confidence = np.mean(all_confidences) if all_confidences else 0.0
            
            _LOGGER.info(f"PaddleOCR PDF: {len(images)} Seiten, {len(all_text)} Zeilen")
            
            return OCRResult(
                success=True,
                text=full_text,
                method="paddleocr",
                confidence=float(avg_confidence),
                processing_time=time.time() - start_time
            )
        
        except Exception as e:
            _LOGGER.error(f"PaddleOCR PDF Fehler: {e}")
            return OCRResult(
                success=False,
                error=str(e),
                processing_time=time.time() - start_time
            )


class EasyOCRProcessor:
    """
    Wrapper für EasyOCR (optional, Fallback).
    
    **Nutzen**:
    - Einfache API
    - 80+ Sprachen
    - Gut für mehrsprachige Dokumente
    
    **Offline**: ✅ Modelle werden beim ersten Start heruntergeladen
    
    **Installation**:
    ```bash
    pip install easyocr
    ```
    """
    
    def __init__(self, languages: List[str] = None, gpu: bool = False):
        """
        Args:
            languages: Liste von Sprachen (z.B. ['de', 'en'])
            gpu: GPU-Beschleunigung
        """
        self.languages = languages or ['de', 'en']
        self.gpu = gpu
        self._reader = None
    
    def _get_reader(self):
        """Lazy-Loading für EasyOCR."""
        if self._reader is not None:
            return self._reader
        
        try:
            import easyocr
        except ImportError:
            raise ImportError("EasyOCR ist nicht installiert. Installiere mit: pip install easyocr")
        
        _LOGGER.info(f"Initialisiere EasyOCR ({', '.join(self.languages)})...")
        self._reader = easyocr.Reader(self.languages, gpu=self.gpu)
        return self._reader
    
    def process_image(self, image_path: Path) -> OCRResult:
        """OCR auf Bild."""
        import time
        start_time = time.time()
        
        reader = self._get_reader()
        
        try:
            result = reader.readtext(str(image_path))
            
            if not result:
                return OCRResult(
                    success=False,
                    error="Kein Text erkannt",
                    processing_time=time.time() - start_time
                )
            
            # EasyOCR: [(bbox, text, confidence), ...]
            lines = [item[1] for item in result]
            confidences = [item[2] for item in result]
            
            full_text = "\n".join(lines)
            avg_confidence = np.mean(confidences) if confidences else 0.0
            
            return OCRResult(
                success=True,
                text=full_text,
                method="easyocr",
                confidence=float(avg_confidence),
                processing_time=time.time() - start_time
            )
        
        except Exception as e:
            _LOGGER.error(f"EasyOCR Fehler: {e}")
            return OCRResult(
                success=False,
                error=str(e),
                processing_time=time.time() - start_time
            )


def process_with_ocr(
    pdf_path: Path,
    method: str = "auto",
    output_path: Optional[Path] = None,
    **kwargs
) -> OCRResult:
    """
    Haupt-OCR-Funktion mit automatischer Methodenwahl.
    
    Args:
        pdf_path: Pfad zur PDF
        method: "auto", "ocrmypdf", "paddleocr", "easyocr"
        output_path: Ausgabepfad (nur für ocrmypdf)
        **kwargs: Zusätzliche Optionen für OCR-Prozessor
    
    Returns:
        OCRResult
    
    **Strategie bei "auto"**:
    1. Versuche OCRmyPDF (schnell, zuverlässig)
    2. Falls Fehler: PaddleOCR (präzise)
    3. Falls Fehler: EasyOCR (Fallback)
    """
    _LOGGER.info(f"OCR-Verarbeitung: {pdf_path.name} (Methode: {method})")
    
    if method == "ocrmypdf" or method == "auto":
        processor = OCRmyPDFProcessor(**kwargs)
        result = processor.process(pdf_path, output_path)
        
        if result.success or method != "auto":
            return result
        
        _LOGGER.warning("OCRmyPDF fehlgeschlagen, versuche PaddleOCR...")
    
    if method == "paddleocr" or method == "auto":
        try:
            processor = PaddleOCRProcessor(**kwargs)
            result = processor.process_pdf(pdf_path)
            
            if result.success or method != "auto":
                return result
            
            _LOGGER.warning("PaddleOCR fehlgeschlagen, versuche EasyOCR...")
        except Exception as e:
            _LOGGER.error(f"PaddleOCR nicht verfügbar: {e}")
            if method != "auto":
                return OCRResult(success=False, error=str(e))
    
    if method == "easyocr" or method == "auto":
        try:
            processor = EasyOCRProcessor(**kwargs)
            
            # EasyOCR benötigt Bilder, konvertiere PDF
            from pdf2image import convert_from_path
            images = convert_from_path(pdf_path, dpi=300, last_page=1)
            
            if images:
                # Temporäres Bild speichern
                temp_img = pdf_path.parent / f"{pdf_path.stem}_temp.jpg"
                images[0].save(temp_img)
                
                result = processor.process_image(temp_img)
                temp_img.unlink()  # Aufräumen
                
                return result
        except Exception as e:
            _LOGGER.error(f"EasyOCR nicht verfügbar: {e}")
            return OCRResult(success=False, error=str(e))
    
    return OCRResult(
        success=False,
        error="Keine OCR-Methode verfügbar oder alle fehlgeschlagen"
    )


# Beispiel-Nutzung
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test mit einer PDF
    test_pdf = Path("test_document.pdf")
    
    if test_pdf.exists():
        # Automatische Methode
        result = process_with_ocr(test_pdf, method="auto")
        
        if result.success:
            print(f"✅ OCR erfolgreich mit {result.method}")
            print(f"   Confidence: {result.confidence:.2f}")
            print(f"   Zeit: {result.processing_time:.2f}s")
            if result.output_path:
                print(f"   Ausgabe: {result.output_path}")
        else:
            print(f"❌ OCR fehlgeschlagen: {result.error}")
