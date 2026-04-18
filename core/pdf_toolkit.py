"""
PDF-Toolkit: Zusammenführen, Teilen, Komprimieren, OCR – vollständig lokal.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_tesseract_cmd() -> Optional[Path]:
    configured = (os.getenv("DOCARO_TESSERACT_CMD") or "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            BASE_DIR / "Tesseract OCR Windows installer" / "tesseract.exe",
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_tessdata_prefix(tesseract_cmd: Optional[Path]) -> Optional[Path]:
    configured = (os.getenv("TESSDATA_PREFIX") or "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured))
    if tesseract_cmd is not None:
        candidates.append(tesseract_cmd.parent / "tessdata")
    candidates.append(Path(r"C:\Program Files\Tesseract-OCR\tessdata"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _build_ocr_process_env() -> dict[str, str]:
    env = os.environ.copy()
    tesseract_cmd = _resolve_tesseract_cmd()
    if tesseract_cmd is not None:
        env["DOCARO_TESSERACT_CMD"] = str(tesseract_cmd)
        tool_dir = str(tesseract_cmd.parent)
        current_path = env.get("PATH", "")
        path_parts = current_path.split(os.pathsep) if current_path else []
        if tool_dir not in path_parts:
            env["PATH"] = tool_dir + (os.pathsep + current_path if current_path else "")

    tessdata_prefix = _resolve_tessdata_prefix(tesseract_cmd)
    if tessdata_prefix is not None:
        env["TESSDATA_PREFIX"] = str(tessdata_prefix)

    return env


def _which_in_env(executable: str, env: dict[str, str]) -> Optional[str]:
    return shutil.which(executable, path=env.get("PATH"))


def _ocrmypdf_optimize_level(env: dict[str, str]) -> str:
    explicit = (os.getenv("DOCARO_OCRMYPDF_OPTIMIZE") or "").strip()
    if explicit in {"0", "1", "2", "3"}:
        return explicit

    has_pngquant = _which_in_env("pngquant", env) is not None
    has_jbig2 = _which_in_env("jbig2", env) is not None
    if has_pngquant or has_jbig2:
        return "1"
    return "0"


def _configure_pytesseract() -> None:
    try:
        import pytesseract
    except Exception:
        return

    env = _build_ocr_process_env()
    tesseract_cmd = env.get("DOCARO_TESSERACT_CMD")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    tessdata_prefix = env.get("TESSDATA_PREFIX")
    if tessdata_prefix:
        os.environ["TESSDATA_PREFIX"] = tessdata_prefix


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge_pdfs(input_paths: List[Path], output_path: Path) -> Path:
    """Mehrere PDFs zu einer Datei zusammenführen (Reihenfolge wie übergeben)."""
    try:
        import fitz  # PyMuPDF
        out_doc = fitz.open()
        for p in input_paths:
            with fitz.open(str(p)) as src:
                out_doc.insert_pdf(src)
        out_doc.save(str(output_path), garbage=4, deflate=True)
        out_doc.close()
    except ImportError:
        from PyPDF2 import PdfMerger
        merger = PdfMerger()
        for p in input_paths:
            merger.append(str(p))
        with open(output_path, "wb") as f:
            merger.write(f)
        merger.close()
    return output_path


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------

def split_pdf(
    input_path: Path,
    output_dir: Path,
    ranges: Optional[List[Tuple[int, int]]] = None,
) -> List[Path]:
    """
    PDF aufteilen.

    ranges: Liste von (von, bis) Seitenbereichen (1-basiert, inklusiv).
            Wenn None → jede Seite als eigene Datei.
    Gibt eine Liste der erstellten Pfade zurück.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results: List[Path] = []

    try:
        import fitz
        doc = fitz.open(str(input_path))
        page_count = doc.page_count

        if ranges is None:
            for i in range(page_count):
                out = fitz.open()
                out.insert_pdf(doc, from_page=i, to_page=i)
                dest = output_dir / f"seite_{i + 1:04d}.pdf"
                out.save(str(dest), garbage=4, deflate=True)
                out.close()
                results.append(dest)
        else:
            for idx, (start, end) in enumerate(ranges, 1):
                s = max(0, start - 1)
                e = min(page_count - 1, end - 1)
                out = fitz.open()
                out.insert_pdf(doc, from_page=s, to_page=e)
                dest = output_dir / f"bereich_{idx:02d}_s{start}-{end}.pdf"
                out.save(str(dest), garbage=4, deflate=True)
                out.close()
                results.append(dest)
        doc.close()

    except ImportError:
        from PyPDF2 import PdfReader, PdfWriter
        reader = PdfReader(str(input_path))
        page_count = len(reader.pages)

        if ranges is None:
            for i in range(page_count):
                writer = PdfWriter()
                writer.add_page(reader.pages[i])
                dest = output_dir / f"seite_{i + 1:04d}.pdf"
                with open(dest, "wb") as f:
                    writer.write(f)
                results.append(dest)
        else:
            for idx, (start, end) in enumerate(ranges, 1):
                writer = PdfWriter()
                for i in range(start - 1, min(end, page_count)):
                    writer.add_page(reader.pages[i])
                dest = output_dir / f"bereich_{idx:02d}_s{start}-{end}.pdf"
                with open(dest, "wb") as f:
                    writer.write(f)
                results.append(dest)

    return results


# ---------------------------------------------------------------------------
# Compress
# ---------------------------------------------------------------------------

def compress_pdf(
    input_path: Path,
    output_path: Path,
    quality: str = "medium",
) -> Path:
    """
    PDF komprimieren.

    quality: 'low' (stärkste Komprimierung), 'medium', 'high' (geringe Komprimierung)
    Nutzt PyMuPDF für optimales Ergebnis, kein Cloud-Dienst.
    """
    dpi_map = {"low": 72, "medium": 100, "high": 150}
    target_dpi = dpi_map.get(quality, 100)

    try:
        import fitz

        # Erst: strukturelle Bereinigung (funktioniert gut für Text-PDFs)
        doc = fitz.open(str(input_path))
        doc.save(str(output_path), garbage=4, deflate=True, clean=True)
        doc.close()

        # Bei mittlerer/niedriger Qualität: Bilder neu samplen wenn Eingabe groß genug
        if quality in ("medium", "low") and input_path.stat().st_size > 200_000:
            struct_size = output_path.stat().st_size
            tmp_img = output_path.with_suffix(".img_tmp.pdf")
            doc2 = fitz.open(str(input_path))
            out_doc = fitz.open()
            mat = fitz.Matrix(target_dpi / 72, target_dpi / 72)
            for page in doc2:
                pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB)
                new_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
                new_page.insert_image(page.rect, pixmap=pix)
            out_doc.save(str(tmp_img), garbage=4, deflate=True, clean=True)
            out_doc.close()
            doc2.close()
            # Nur übernehmen wenn tatsächlich kleiner
            if tmp_img.stat().st_size < struct_size:
                tmp_img.replace(output_path)
            else:
                tmp_img.unlink(missing_ok=True)

    except ImportError:
        from PyPDF2 import PdfReader, PdfWriter
        reader = PdfReader(str(input_path))
        writer = PdfWriter()
        for page in reader.pages:
            page.compress_content_streams()
            writer.add_page(page)
        with open(output_path, "wb") as f:
            writer.write(f)

    return output_path


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def ocr_pdf(
    input_path: Path,
    output_path: Path,
    lang: str = "deu+eng",
) -> Path:
    """
    Durchsuchbare Textschicht per OCR hinzufügen.

    Versucht ocrmypdf (beste Qualität), fällt auf pytesseract+PyMuPDF zurück.
    Überschreibt vorhandene Textschicht nicht wenn Dokument bereits Text enthält.
    """
    process_env = _build_ocr_process_env()
    optimize_level = _ocrmypdf_optimize_level(process_env)

    if getattr(sys, "frozen", False):
        _ocr_fallback(input_path, output_path, lang)
        return output_path

    # Versuche ocrmypdf (Kommandozeilen-Tool, bereits in requirements-pipeline)
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "ocrmypdf",
                "--language", lang,
                "--output-type", "pdf",
                "--optimize", optimize_level,
                "--skip-text",          # Seiten mit vorhandenem Text überspringen
                "--rotate-pages",
                "--deskew",
                str(input_path),
                str(output_path),
            ],
            capture_output=True,
            text=True,
            env=process_env,
            timeout=300,
        )
        if result.returncode == 0 and output_path.exists():
            return output_path
        if result.returncode == 0:
            logger.warning("ocrmypdf lieferte Code 0, aber keine Ausgabedatei: %s", output_path)
        logger.warning("ocrmypdf Fehler (Code %s): %s", result.returncode, result.stderr[:300])
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("ocrmypdf nicht verfügbar: %s", exc)

    # Fallback: pytesseract + PyMuPDF
    _ocr_fallback(input_path, output_path, lang)
    return output_path


def _ocr_fallback(input_path: Path, output_path: Path, lang: str) -> None:
    """Pytesseract-Fallback für OCR."""
    try:
        import fitz
        import pytesseract
        from PIL import Image

        _configure_pytesseract()
        tess_lang = lang.replace("+", "+")
        doc = fitz.open(str(input_path))
        out_doc = fitz.open()

        for page_num in range(doc.page_count):
            page = doc[page_num]
            mat = fitz.Matrix(2.0, 2.0)  # 144 DPI
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            pdf_bytes = pytesseract.image_to_pdf_or_hocr(
                img, extension="pdf", lang=tess_lang
            )
            page_pdf = fitz.open("pdf", pdf_bytes)
            out_doc.insert_pdf(page_pdf)
            page_pdf.close()

        out_doc.save(str(output_path), garbage=4, deflate=True)
        out_doc.close()
        doc.close()
    except Exception as exc:
        logger.error("OCR-Fallback fehlgeschlagen: %s", exc)
        raise RuntimeError(f"OCR nicht möglich: {exc}") from exc


# ---------------------------------------------------------------------------
# Hilfsfunktion
# ---------------------------------------------------------------------------

def get_page_count(path: Path) -> int:
    """Seitenanzahl eines PDFs ermitteln."""
    try:
        import fitz
        with fitz.open(str(path)) as doc:
            return doc.page_count
    except ImportError:
        from PyPDF2 import PdfReader
        return len(PdfReader(str(path)).pages)
