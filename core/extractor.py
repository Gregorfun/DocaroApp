from __future__ import annotations

import csv
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
import logging
import threading
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from pdf2image import convert_from_path
from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError, PDFSyntaxError
import pytesseract
from PIL import ImageEnhance
from PIL import Image

try:
    import date_parser  # type: ignore
except ImportError:
    try:
        from core import date_parser  # type: ignore
    except ImportError:
        date_parser = None

try:
    from core.doc_number_extractor import extract_doc_number, generate_fallback_identifier
except ImportError:
    extract_doc_number = None
    generate_fallback_identifier = None

try:
    from core.supplier_canonicalizer import canonicalize_supplier
except ImportError:
    canonicalize_supplier = None

try:
    from core.doctype_classifier import classify_doc_type
except ImportError:
    classify_doc_type = None

try:
    from core.review_service import decide_review_status, load_review_settings, DocumentStatus
except ImportError:
    decide_review_status = None
    load_review_settings = None
    DocumentStatus = None

from config import Config

config = Config()
from constants import DATE_REGEX_PATTERNS, LABEL_PATTERNS, LABEL_PRIORITY, DATE_LABELS
from utils import first_path_from_env, has_pdfinfo
from core.text_segments import segment_text

def normalize_text(text: str) -> str:
    """Normalisiert Text für OCR: Entfernt überflüssige Leerzeichen und Zeilenumbrüche."""
    if not text:
        return ""
    # Entferne Zeilenumbrüche und Tabs, ersetze durch Leerzeichen
    text = re.sub(r'[\n\r\t]+', ' ', text)
    # Entferne Nicht-Alphanumerisch außer Leerzeichen und Umlauten
    text = re.sub(r'[^\w\säöüÄÖÜß]', '', text)
    # Entferne mehrfache Leerzeichen
    text = re.sub(r' +', ' ', text)
    return text.strip()

BASE_DIR = config.BASE_DIR
DEFAULT_DATE_FORMAT = "%Y-%m-%d"
INTERNAL_DATE_FORMAT = "%Y-%m-%d"
SUPPLIERS_DB_PATH = config.DATA_DIR / "suppliers.json"
OCR_TIMEOUT_SECONDS = config.OCR_TIMEOUT_SECONDS
PDF_CONVERT_TIMEOUT = config.PDF_CONVERT_TIMEOUT
ROTATION_OCR_TIMEOUT = config.ROTATION_OCR_TIMEOUT
DATE_CROP_OCR_TIMEOUT = config.DATE_CROP_OCR_TIMEOUT
OCR_PAGES = config.OCR_PAGES
LOG_RETENTION_DAYS = config.LOG_RETENTION_DAYS
DEBUG_EXTRACT = config.DEBUG_EXTRACT
USE_PADDLEOCR = getattr(config, "USE_PADDLEOCR", False)
PADDLEOCR_LANG = getattr(config, "PADDLEOCR_LANG", "german")

def _render_dpi() -> int:
    """DPI for PDF->image rendering.

    Lower DPI reduces memory usage and avoids OOM-kills on small servers.
    Can be overridden via DOCARO_RENDER_DPI.
    """
    try:
        dpi = int(os.getenv("DOCARO_RENDER_DPI", "200"))
    except ValueError:
        dpi = 200
    return max(120, min(dpi, 300))
DEBUG_LOG_PATH = config.LOG_DIR / "extract_debug.log"
_LOGGER = logging.getLogger(__name__)
_LOG_LOCK = threading.Lock()
_FS_LOCK = threading.Lock()

_PADDLE_OCR = None
_PADDLE_LOCK = threading.Lock()
_PADDLE_RUNTIME_OK: Optional[bool] = None


def _paddle_runtime_selftest() -> Tuple[bool, str]:
    """Checks whether PaddleOCR can be imported/initialized in this environment.

    Motivation: On some Windows setups Paddle/PaddleX can hard-crash the interpreter
    (access violation). To keep Docaro stable we probe in a subprocess first.

    Returns: (ok, detail)
    """
    try:
        test_code = (
            "import os\n"
            "os.environ['DISABLE_MODEL_SOURCE_CHECK']='True'\n"
            "os.environ.setdefault('OMP_NUM_THREADS','1')\n"
            "os.environ.setdefault('MKL_NUM_THREADS','1')\n"
            "from paddleocr import PaddleOCR\n"
            "import numpy as np\n"
            "ocr = PaddleOCR(lang=%r, use_angle_cls=True)\n"
            "arr = np.random.randint(0, 256, (256, 256, 3), dtype=np.uint8)\n"
            "_ = ocr.ocr(arr)\n"
            "print('ok')\n" % (PADDLEOCR_LANG,)
        )
        completed = subprocess.run(
            [sys.executable, "-c", test_code],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if completed.returncode == 0 and "ok" in (completed.stdout or ""):
            return True, "ok"
        detail = (completed.stderr or completed.stdout or "").strip()
        return False, f"returncode={completed.returncode} detail={detail[:300]}"
    except Exception as exc:
        return False, f"selftest_failed: {exc}"


def _get_paddle_ocr():
    """Lazy-Loader für PaddleOCR.

    Wichtig: PaddleOCR ist optional und wird nur geladen, wenn DOCARO_USE_PADDLEOCR=1.
    """
    global _PADDLE_OCR
    if _PADDLE_OCR is not None:
        return _PADDLE_OCR
    with _PADDLE_LOCK:
        if _PADDLE_OCR is not None:
            return _PADDLE_OCR

        global _PADDLE_RUNTIME_OK
        if _PADDLE_RUNTIME_OK is None:
            ok, detail = _paddle_runtime_selftest()
            _PADDLE_RUNTIME_OK = ok
            if not ok:
                _LOGGER.warning("PaddleOCR self-test failed (disabled): %s", detail)

        if _PADDLE_RUNTIME_OK is False:
            _PADDLE_OCR = False
            return _PADDLE_OCR

        # PaddleOCR kann beim ersten Import/Init Checks/Downloads triggern.
        # Wir setzen das Flag defensiv, damit es in restriktiven Umgebungen nicht hart scheitert.
        os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("MKL_NUM_THREADS", "1")

        try:
            from paddleocr import PaddleOCR  # type: ignore
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt):
                raise
            _LOGGER.info("PaddleOCR not available: %s", exc)
            _PADDLE_OCR = False
            return _PADDLE_OCR

        try:
            # use_angle_cls hilft bei 90°/180°/270° Fällen.
            _PADDLE_OCR = PaddleOCR(lang=PADDLEOCR_LANG, use_angle_cls=True)
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt):
                raise
            _LOGGER.warning("PaddleOCR init failed: %s", exc)
            _PADDLE_OCR = False
        return _PADDLE_OCR


def _paddle_ocr_image(image) -> Tuple[str, float, str]:
    """OCR via PaddleOCR (optional).

    Returns: (text, avg_confidence, error)
    """
    if not USE_PADDLEOCR:
        return "", 0.0, "disabled"
    engine = _get_paddle_ocr()
    if not engine:
        return "", 0.0, "unavailable"

    try:
        if not isinstance(image, Image.Image):
            return "", 0.0, "invalid_image"
        rgb = image.convert("RGB")
        import numpy as np  # type: ignore

        arr = np.array(rgb)
        result = engine.ocr(arr)
        if not result:
            return "", 0.0, "no_text"

        lines: List[str] = []
        confs: List[float] = []

        # PaddleOCR Ergebnisformate variieren zwischen Versionen.
        # Häufige Formen:
        #  A) [ [box, (text, conf)], ... ]
        #  B) [ [ [box, (text, conf)], ... ] ]  (pages)
        entries: List[object] = []
        try:
            if (
                isinstance(result, list)
                and result
                and isinstance(result[0], list)
                and len(result[0]) == 2
            ):
                # Form A
                entries = result  # type: ignore[assignment]
            else:
                # Form B oder andere: flatten
                for page in result:
                    if isinstance(page, list):
                        entries.extend(page)
        except Exception:
            entries = []

        for entry in entries:
            if not entry or not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            text_conf = entry[1]
            if not text_conf or not isinstance(text_conf, (list, tuple)) or len(text_conf) < 2:
                continue
            text_val = str(text_conf[0] or "").strip()
            try:
                conf_val = float(text_conf[1])
            except Exception:
                conf_val = 0.0
            if text_val:
                lines.append(text_val)
                confs.append(conf_val)

        if not lines:
            return "", 0.0, "no_text"

        text = "\n".join(lines)
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        return text, avg_conf, ""
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        return "", 0.0, f"paddle_failed: {exc}"


def _has_pdfinfo(bin_dir: Path) -> bool:
    return has_pdfinfo(bin_dir)


def _first_path_from_env(value: str) -> Optional[Path]:
    return first_path_from_env(value)


def _resolve_tesseract_cmd() -> Tuple[Optional[Path], bool]:
    if config.TESSERACT_CMD:
        candidate = _first_path_from_env(config.TESSERACT_CMD)
        if candidate and candidate.exists():
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate, True
            if candidate.is_dir():
                exe_candidate = candidate / "tesseract.exe"
                if exe_candidate.exists() and os.access(exe_candidate, os.X_OK):
                    return exe_candidate, True
        if candidate and candidate.is_dir():
            exe_candidate = candidate / "tesseract.exe"
            if exe_candidate.exists() and os.access(exe_candidate, os.X_OK):
                return exe_candidate, True
    which_path = shutil.which("tesseract")
    if which_path:
        return Path(which_path), True
    if os.name == "nt":
        fallback_paths = [
            BASE_DIR / "Tesseract OCR Windows installer" / "tesseract.exe",
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        for candidate in fallback_paths:
            if candidate.exists() and os.access(candidate, os.X_OK):
                return candidate, True
    return None, False


def _resolve_poppler_bin() -> Tuple[Optional[Path], bool]:
    if config.POPPLER_BIN:
        candidate = _first_path_from_env(config.POPPLER_BIN)
        if candidate:
            if candidate.is_dir() and _has_pdfinfo(candidate):
                return candidate, True
            if candidate.is_file() and candidate.name.lower().startswith("pdfinfo"):
                return candidate.parent, True

    for folder_name in ("poppler", "Poppler"):
        candidate = BASE_DIR / folder_name / "Library" / "bin"
        if _has_pdfinfo(candidate):
            return candidate, True

    if shutil.which("pdfinfo"):
        return None, True

    return None, False


_TESSERACT_PATH, _TESSERACT_OK = _resolve_tesseract_cmd()
if _TESSERACT_OK and _TESSERACT_PATH:
    pytesseract.pytesseract.tesseract_cmd = str(_TESSERACT_PATH)
elif not _TESSERACT_OK:
    print("Warnung: Tesseract wurde nicht gefunden. OCR kann fehlschlagen.")

_POPPLER_BIN, _POPPLER_OK = _resolve_poppler_bin()
if not _POPPLER_OK:
    print("Warnung: Poppler/pdfinfo nicht gefunden. PDF-Konvertierung kann fehlschlagen.")

SUPPLIER_KEYWORDS = {
    "Liebherr-Werk Ehingen": "Liebherr_Ehingen",
    "Liebherr-Werk Nenzing": "Liebherr_Nenzing",
    "DB Schenker": "DBSchenker",
    "DHL Paket": "DHL",
    "Linde Material Handling": "Linde",
    "Manitowoc": "Manitowoc",
    "Pirtek": "Pirtek",
    "Vergoelst": "Vergoelst",
    "Tadano": "Tadano",
    "Georg Zopf": "Zopf",
    "WM Fahrzeugteile": "WM",
    "WM SE": "WM",
    "WFI Wireless Funk": "WFI",
    "Hofmeister & Meincke": "Hofmeister",
    "Foerch GmbH": "Foerch",
    "Borgmann": "VW Borgmann",
    "Fuchs Lubricants Germany GmbH": "Fuchs",
    "Ortjohann und Kraft Werkzeug und Maschinenhandel GmbH": "Ortjohann+ Kraft",
    "PV Automotive GmbH": "PV Automotive",
    "PV Automotive": "PV Automotive",
    "Foerch": "Foerch",
    "Liebherr": "Liebherr",
}

VERGOELST_ALIASES = [
    "verg lst",
    "verglst",
    "verg-lst",
    "vergolst",
    "vergolst gmbh",
    "vergölst",
    "vergölst gmbh",
    "vergoelst",
    "vergoelst gmbh",
    "vergoelst reifen",
]

LS_KEYWORDS = [
    "lieferschein",
    "delivery note",
    "lieferdatum",
    "lieferscheindatum",
    "lieferscheintermin",
    "liefertermin",
    "belegdatum",
    "beleg-datum",
    "rechnungsdatum",
    "auftragsdatum",
    "warenausgang",
    "ausgang",
    "document date",
    "tag der lieferung",
    "druckdatum",
]

DATE_LABELS = [
    "lieferdatum",
    "lieferscheindatum",
    "lieferscheintermin",
    "liefertermin",
    "tag der lieferung",
    "beleg-datum",
    "belegdatum",
    "beleg datum",
    "rechnungsdatum",
    "druckdatum",
    "auftragsdatum",
    "datum",
]

DELIVERY_NOTE_KEYWORDS = [
    "lieferschein-nr",
    "lieferscheinnr",
    "lieferscheinnummer",
    "ls-nr",
    "lieferschein nr",
]

ORDER_KEYWORDS = [
    "auftragsnummer",
    "auftrag nr",
    "auftrag-nr",
    "auftrag",
    "bestellnummer",
    "bestellung",
    "order no",
    "order",
]

_DOCNO_TOKEN = re.compile(r"\b([A-Z0-9][A-Z0-9\-/]{2,})\b", re.IGNORECASE)
# Liebherr-spezifisch: Lieferschein gefolgt von 8-10 Ziffern, auch über Zeilenumbrüche hinweg
_LIEBHERR_LIEFERSCHEIN = re.compile(r"lieferschein[\s:]*([\d\s]{8,12})", re.IGNORECASE | re.DOTALL)
_LIEFERSCHEIN_TITLE_NO = re.compile(r"\blieferschein\b[^0-9]{0,25}(\d{7,10})\b", re.IGNORECASE | re.DOTALL)
_DATE_LIKE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b")
_IBAN_LIKE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_PHONE_LIKE = re.compile(r"\b\+?\d[\d /()\-]{6,}\d\b")
_AMOUNT_LIKE = re.compile(r"\b\d{1,3}(?:[\.,]\d{3})*(?:[\.,]\d{2})\b")


def _clean_doc_number(value: str) -> str:
    val = (value or "").strip().strip(".:;,")
    val = re.sub(r"\s+", "", val)
    return val


def _is_plausible_doc_number(token: str, *, allow_5digit_numeric: bool) -> bool:
    t = _clean_doc_number(token)
    if not t or len(t) < 4:
        return False
    if _DATE_LIKE.search(t):
        return False
    if _IBAN_LIKE.search(t):
        return False
    if _PHONE_LIKE.search(t):
        return False
    if _AMOUNT_LIKE.fullmatch(t):
        return False
    if t.isdigit() and len(t) == 5 and not allow_5digit_numeric:
        # häufig PLZ; ohne Keyword nicht akzeptieren
        return False
    if not any(ch.isdigit() for ch in t):
        return False
    return True


def _find_number_near_keywords(text: str, keywords: list[str]) -> Optional[str]:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    for idx, line in enumerate(lines):
        lower = line.lower()
        hit = None
        for kw in keywords:
            if kw in lower:
                hit = kw
                break
        if not hit:
            continue

        # 1) gleiche Zeile: nach dem Keyword einen Token suchen
        try:
            pos = lower.find(hit)
        except Exception:
            pos = -1
        tail = line[pos + len(hit) :] if pos >= 0 else line
        for m in _DOCNO_TOKEN.finditer(tail):
            cand = _clean_doc_number(m.group(1))
            if _is_plausible_doc_number(cand, allow_5digit_numeric=True):
                return cand

        # 2) nächste 1–2 Zeilen
        for j in range(idx + 1, min(idx + 3, len(lines))):
            for m in _DOCNO_TOKEN.finditer(lines[j]):
                cand = _clean_doc_number(m.group(1))
                if _is_plausible_doc_number(cand, allow_5digit_numeric=True):
                    return cand
    return None


def extract_document_numbers(text: str) -> Dict[str, object]:
    """Extrahiert Lieferschein-/Auftragsnummer aus Text.

    Priorität: Lieferschein > Auftrag.
    confidence: "high" (mit Keyword), "low" (heuristisch), "none".
    """

    combined = text or ""

    # Liebherr-spezifisches Pattern: "Lieferschein" gefolgt von Ziffern (mit Zeilenumbrüchen)
    m = _LIEBHERR_LIEFERSCHEIN.search(combined)
    if m:
        # Entferne alle Whitespace-Zeichen aus der Zifferngruppe
        digits = re.sub(r"\s", "", m.group(1))
        if len(digits) >= 7 and len(digits) <= 10:
            cand = _clean_doc_number(digits)
            if _is_plausible_doc_number(cand, allow_5digit_numeric=False):
                return {"delivery_note_no": cand, "order_no": None, "confidence": "high"}

    # Spezielles Muster: "Lieferschein 200541642" (ohne "-Nr" Label)
    # (häufig bei Hersteller-Lieferscheinen wie Liebherr)
    m = _LIEFERSCHEIN_TITLE_NO.search(combined)
    if m:
        cand = _clean_doc_number(m.group(1))
        if _is_plausible_doc_number(cand, allow_5digit_numeric=False):
            return {"delivery_note_no": cand, "order_no": None, "confidence": "high"}

    delivery = _find_number_near_keywords(combined, DELIVERY_NOTE_KEYWORDS)
    if delivery:
        return {"delivery_note_no": delivery, "order_no": None, "confidence": "high"}

    order_no = _find_number_near_keywords(combined, ORDER_KEYWORDS)
    if order_no:
        return {"delivery_note_no": None, "order_no": order_no, "confidence": "high"}

    # Heuristik: erster plausibler Token (ohne Keyword) -> low
    for m in _DOCNO_TOKEN.finditer(combined):
        cand = _clean_doc_number(m.group(1))
        if _is_plausible_doc_number(cand, allow_5digit_numeric=False):
            return {"delivery_note_no": None, "order_no": cand, "confidence": "low"}

    return {"delivery_note_no": None, "order_no": None, "confidence": "none"}

def extract_delivery_note_number(text: str) -> Optional[str]:
    """
    Extracts the delivery note number from the text.
    Searches for keywords and extracts the following number.
    """
    found = _find_number_near_keywords(text or "", DELIVERY_NOTE_KEYWORDS)
    return found



CANONICAL_SUPPLIERS = {
    "vergoelst": "Vergoelst",
    "vergolst": "Vergoelst",
    "verglst": "Vergoelst",
}

# LABEL_PATTERNS und LABEL_PRIORITY aus constants.py verwendet

MONTH_MAP = {
    "jan": "01",
    "januar": "01",
    "feb": "02",
    "februar": "02",
    "mar": "03",
    "maer": "03",
    "maerz": "03",
    "marz": "03",
    "apr": "04",
    "april": "04",
    "mai": "05",
    "may": "05",
    "jun": "06",
    "juni": "06",
    "jul": "07",
    "juli": "07",
    "aug": "08",
    "august": "08",
    "sep": "09",
    "sept": "09",
    "september": "09",
    "oct": "10",
    "okt": "10",
    "oktober": "10",
    "nov": "11",
    "november": "11",
    "dec": "12",
    "dez": "12",
    "dezember": "12",
}

# Regex-Patterns aus constants.py verwenden
ISO_REGEX = DATE_REGEX_PATTERNS["iso"]
YMD_SLASH_REGEX = DATE_REGEX_PATTERNS["ymd_slash"]
DMY_DOT_REGEX = DATE_REGEX_PATTERNS["dmy_dot"]
DMY_DASH_REGEX = DATE_REGEX_PATTERNS["dmy_dash"]
DMY_SLASH_REGEX = DATE_REGEX_PATTERNS["dmy_slash"]
DMY_DOT_SHORT_REGEX = DATE_REGEX_PATTERNS["dmy_dot_short"]
DMY_DASH_SHORT_REGEX = DATE_REGEX_PATTERNS["dmy_dash_short"]
DMY_SLASH_SHORT_REGEX = DATE_REGEX_PATTERNS["dmy_slash_short"]
MONTH_NAME_REGEX = DATE_REGEX_PATTERNS["month_name"]
DMY_MONTH_DASH_REGEX = DATE_REGEX_PATTERNS["dmy_month_dash"]
VERGOELST_REGEX = DATE_REGEX_PATTERNS["vergoelst"]
TADANO_REGEX = DATE_REGEX_PATTERNS["tadano"]

DATE_REGEXES = list(DATE_REGEX_PATTERNS.values())


def _has_osd_traineddata() -> bool:
    tessdata_prefix = os.getenv("TESSDATA_PREFIX")
    candidates = []
    if tessdata_prefix:
        candidates.append(Path(tessdata_prefix) / "osd.traineddata")
    if _TESSERACT_PATH:
        candidates.append(_TESSERACT_PATH.parent / "tessdata" / "osd.traineddata")
    return any(candidate.exists() for candidate in candidates)


def _ocr_image(image, rotation: int, config: str = "", timeout: Optional[int] = None) -> str:
    if rotation:
        image = image.rotate(rotation, expand=True)

    image = image.convert("L")
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(1.5)

    effective_timeout = OCR_TIMEOUT_SECONDS if timeout is None else timeout
    return pytesseract.image_to_string(
        image,
        lang="deu",
        config=config,
        timeout=effective_timeout,
    )


def _count_keywords(text: str) -> int:
    lower = text.lower()
    return sum(lower.count(keyword) for keyword in LS_KEYWORDS)


def _score_text(text: str) -> int:
    if not text:
        return 0
    lower = text.lower()
    words = len(text.split())
    alnum_count = sum(1 for ch in text if ch.isalnum())
    keyword_hits = _count_keywords(text)
    label_hits = sum(1 for _, pattern in LABEL_PATTERNS if pattern.search(lower))
    date_hits = _count_date_hits(text)
    # Gewichte so, dass „echter“ Lieferschein-Text klar gewinnt gegenüber OCR-Gibberish.
    return (words * 2) + (alnum_count // 25) + (keyword_hits * 60) + (label_hits * 80) + (date_hits * 180)


def _count_date_hits(text: str) -> int:
    if not text:
        return 0
    return sum(len(regex.findall(text)) for regex in DATE_REGEXES)


def _rotation_score(text: str) -> int:
    return _score_text(text) + (_count_date_hits(text) * 50)


def _crop_regions(width: int, height: int) -> List[Tuple[int, int, int, int]]:
    top_h = int(height * 0.35)
    left_w = int(width * 0.6)
    right_w_start = int(width * 0.4)
    return [
        (0, 0, width, top_h),
        (0, 0, left_w, top_h),
        (right_w_start, 0, width, top_h),
    ]


def _rotation_candidates_from_crops(image) -> List[Tuple[int, int]]:
    candidates: List[Tuple[int, int]] = []
    for rotation in (0, 90, 180, 270):
        try:
            rotated = image.rotate(rotation, expand=True) if rotation else image
        except (OSError, ValueError):
            candidates.append((rotation, 0))
            continue
        width, height = rotated.size
        score = 0
        for crop_box in _crop_regions(width, height):
            try:
                crop = rotated.crop(crop_box)
                text = _ocr_image(
                    crop,
                    rotation=0,
                    config="--psm 6",
                    timeout=min(ROTATION_OCR_TIMEOUT, OCR_TIMEOUT_SECONDS),
                )
            except (pytesseract.TesseractError, TimeoutError):
                continue
            score = max(score, _rotation_score(text))
        candidates.append((rotation, score))
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates


def _render_pdf_images(
    pdf_path: Path,
    poppler_bin: Optional[Path],
    pages: int = 1,
) -> Tuple[List[object], str]:
    pages = max(1, min(pages, 5))

    # Optional: force PyMuPDF rendering (avoids Poppler dependency)
    force_pymupdf = os.getenv("DOCARO_RENDER_BACKEND", "").strip().lower() in {"pymupdf", "fitz"}
    if force_pymupdf:
        images, err = _render_pdf_images_pymupdf(pdf_path, pages=pages)
        if images:
            return images, ""
        return [], err or "pymupdf_render_failed"

    try:
        try:
            dpi = _render_dpi()
            images = convert_from_path(
                str(pdf_path),
                dpi=dpi,
                first_page=1,
                last_page=pages,
                poppler_path=str(poppler_bin) if poppler_bin else None,
                timeout=PDF_CONVERT_TIMEOUT,
            )
        except TypeError:
            dpi = _render_dpi()
            images = convert_from_path(
                str(pdf_path),
                dpi=dpi,
                first_page=1,
                last_page=pages,
                poppler_path=str(poppler_bin) if poppler_bin else None,
            )
    except PDFInfoNotInstalledError:
        images, err = _render_pdf_images_pymupdf(pdf_path, pages=pages)
        if images:
            return images, ""
        return [], "Poppler/pdfinfo nicht gefunden - installiere Poppler oder setze DOCARO_POPPLER_BIN"
    except (PDFPageCountError, PDFSyntaxError) as exc:
        return [], f"pdf_read_failed: {exc}"
    except Exception as exc:
        images, err = _render_pdf_images_pymupdf(pdf_path, pages=pages)
        if images:
            return images, ""
        return [], f"pdf_convert_failed: {exc}"
    if not images:
        return [], "Keine Seiten im PDF gefunden."
    return images, ""


def _render_pdf_images_pymupdf(pdf_path: Path, pages: int = 1) -> Tuple[List[object], str]:
    """Render PDF pages to PIL images using PyMuPDF (fitz).

    Returns (images, error). Must never raise.
    """
    pages = max(1, min(pages, 5))
    try:
        import fitz  # type: ignore
    except Exception as exc:
        return [], f"pymupdf_not_available: {exc}"

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        return [], f"pymupdf_open_failed: {exc}"

    images: List[object] = []
    try:
        dpi = float(_render_dpi())
        scale = dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        max_page = min(pages, doc.page_count)
        for page_index in range(max_page):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(img)
    except Exception as exc:
        return [], f"pymupdf_render_failed: {exc}"
    finally:
        try:
            doc.close()
        except Exception:
            pass

    if not images:
        return [], "pymupdf_no_pages"
    return images, ""


def _extract_textlayer(pdf_path: Path, pages: int = 1) -> Tuple[List[str], str]:
    pages = max(1, min(pages, 5))
    texts: List[str] = []
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[:pages]:
                texts.append(page.extract_text() or "")
        if any(t.strip() for t in texts):
            return texts, ""
    except ImportError:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! ACHTUNG: Das Paket 'pdfplumber' zum PDF-Lesen wurde nicht gefunden.")
        print("!!! Dies beeinträchtigt die Datumserkennung.")
        print("!!! Bitte führen Sie den folgenden Befehl in Ihrer Powershell aus:")
        print(r"!!!   .\.venv\Scripts\pip.exe install -r requirements.txt")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        _LOGGER.debug("pdfplumber not installed, falling back to PyPDF2.")
    except ImportError as e:
        _LOGGER.debug("pdfplumber failed, falling back to PyPDF2. Error: %s", e)

    texts = []
    try:
        from PyPDF2 import PdfReader  # type: ignore

        reader = PdfReader(str(pdf_path))
        for page in reader.pages[:pages]:
            texts.append(page.extract_text() or "")
        if any(t.strip() for t in texts):
            return texts, ""
    except ImportError:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! ACHTUNG: Das Paket 'PyPDF2' zum PDF-Lesen wurde nicht gefunden.")
        print("!!! Dies beeinträchtigt die Datumserkennung.")
        print("!!! Bitte führen Sie den folgenden Befehl in Ihrer Powershell aus:")
        print(r"!!!   .\.venv\Scripts\pip.exe install -r requirements.txt")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        return [], "textlayer_failed: PyPDF2 is not installed. Run: .venv\\Scripts\\pip.exe install -r requirements.txt"
    except (OSError, ValueError) as e:
        return [], f"PyPDF2 failed: {e}"
    return [], ""


def _score_rotation_text(text: str) -> int:
    words = len(text.split())
    label_hits = sum(1 for _, pattern in LABEL_PATTERNS if pattern.search(text))
    date_hits = len(NUMERIC_DATE_REGEX.findall(text)) + len(ISO_DATE_REGEX.findall(text)) + len(DMY_MONTH_DASH_REGEX.findall(text))
    return words + (label_hits * 20) + (date_hits * 50)


def _roi_boxes(width: int, height: int) -> Dict[str, Tuple[int, int, int, int]]:
    return {
        "roi1": (0, 0, width, int(height * 0.25)),
        "roi2": (int(width * 0.45), 0, width, int(height * 0.40)),
        "roi3": (int(width * 0.50), int(height * 0.20), width, int(height * 0.60)),
        "roi4": (int(width * 0.25), 0, int(width * 0.75), int(height * 0.25)),
    }


def _ocr_rois(image, rotation: int, roi_keys: List[str]) -> List[str]:
    rotated = image.rotate(rotation, expand=True) if rotation else image
    width, height = rotated.size
    boxes = _roi_boxes(width, height)
    texts: List[str] = []
    for key in roi_keys:
        box = boxes.get(key)
        if not box:
            continue
        try:
            crop = rotated.crop(box)
            text = _ocr_image(
                crop,
                rotation=0,
                config="--psm 6",
                timeout=min(ROTATION_OCR_TIMEOUT, OCR_TIMEOUT_SECONDS),
            )
        except (pytesseract.TesseractError, TimeoutError):
            text = ""
        texts.append(text)
    return texts


def _detect_osd_rotation(image) -> Optional[int]:
    if not _has_osd_traineddata():
        return None
    try:
        osd = pytesseract.image_to_osd(image, timeout=min(ROTATION_OCR_TIMEOUT, OCR_TIMEOUT_SECONDS))
    except (pytesseract.TesseractError, TimeoutError, RuntimeError):
        return None
    match = re.search(r"Rotate:\s*(\d+)", osd)
    if not match:
        return None
    rotation = int(match.group(1))
    if rotation in (0, 90, 180, 270):
        return rotation
    return None


def _ocr_single_image(image, force_best: bool = False) -> Dict[str, str]:
    def _safe_ocr(rotation: int) -> Tuple[str, str, int]:
        try:
            text_value = _ocr_image(image, rotation=rotation)
        except (pytesseract.TesseractError, TimeoutError) as exc:
            message = str(exc)
            if "timeout" in message.lower():
                return "", "ocr_timeout", 0
            return "", f"ocr_failed: {exc}", 0
        return text_value, "", _score_text(text_value)

    if force_best:
        best_rotation = 0
        best_text = ""
        best_score = -1
        candidates = _rotation_candidates_from_crops(image)
        for rotation, _ in candidates:
            text_value, error, score = _safe_ocr(rotation)
            if error:
                continue
            if score > best_score:
                best_score = score
                best_rotation = rotation
                best_text = text_value
        if best_score < 0:
            return {"text": "", "error": "ocr_failed: no_text"}
        return {
            "text": best_text,
            "error": "",
            "rotation": str(best_rotation),
            "rotation_reason": "crop",
            "score": str(best_score),
        }

    text, error, base_score = _safe_ocr(rotation=0)
    if error:
        return {"text": "", "error": error}

    text_length = len(text.strip())
    has_keywords = _count_keywords(text) > 0
    needs_rotation = text_length < 200 or not has_keywords
    if not needs_rotation:
        return {"text": text, "error": "", "rotation": "0", "rotation_reason": "", "score": str(base_score)}

    rotation_reason = "low_text" if text_length < 200 else "no_keywords"
    osd_rotation = _detect_osd_rotation(image)
    if osd_rotation is not None and osd_rotation != 0:
        # Validiere OSD: Prüfe, ob OSD-Rotation wirklich besser ist
        try:
            rotated_text = _ocr_image(image, rotation=osd_rotation)
            osd_score = _score_text(rotated_text)
            # OSD wird nur akzeptiert, wenn es mindestens 1.1x besseren Score hat
            if osd_score > base_score * 1.1:
                _LOGGER.info("osd_rotation accepted: %s (base=%d, osd=%d)", osd_rotation, base_score, osd_score)
                return {
                    "text": rotated_text,
                    "error": "",
                    "rotation": str(osd_rotation),
                    "rotation_reason": "osd",
                    "score": str(osd_score),
                }
            else:
                # OSD rotation ist nicht besser; bleib bei 0°
                _LOGGER.info("osd_rotation rejected: %s (base=%d, osd=%d, need >%.0f)", 
                            osd_rotation, base_score, osd_score, base_score * 1.1)
        except (pytesseract.TesseractError, TimeoutError) as exc:
            _LOGGER.info("osd_rotation failed: %s -> %s", osd_rotation, exc)

    # OSD nicht hilfreich oder nicht gesetzt; versuche Fallback Rotationen
    best_text = text
    best_score = base_score
    best_rotation = 0
    candidates = _rotation_candidates_from_crops(image)
    for rotation, _ in candidates:
        if rotation == 0:
            continue
        rotated_text, error, score = _safe_ocr(rotation)
        if error:
            continue
        if score > best_score:
            best_score = score
            best_rotation = rotation
            best_text = rotated_text

    return {
        "text": best_text,
        "error": "",
        "rotation": str(best_rotation),
        "rotation_reason": "crop" if best_rotation else rotation_reason,
        "score": str(best_score),
    }


def _ocr_images_best(images: List[object], force_best: bool = False) -> Dict[str, str]:
    if not images:
        return {"text": "", "error": "ocr_failed: no_text"}
    best_result: Optional[Dict[str, str]] = None
    best_image = None
    best_score = -1
    last_error = ""
    for idx, image in enumerate(images, start=1):
        result = _ocr_single_image(image, force_best=force_best)
        if result.get("error"):
            last_error = result.get("error") or last_error
            continue
        try:
            score = int(result.get("score", "-1"))
        except ValueError:
            score = -1
        if score > best_score:
            best_score = score
            best_result = result
            best_result["page"] = str(idx)
            best_image = image
    if not best_result:
        result = {"text": "", "error": last_error or "ocr_failed: no_text"}
        result["image"] = images[0]
        return result
    if best_image is not None:
        best_result["image"] = best_image
    return best_result


def ocr_first_page(
    pdf_path: Path,
    poppler_bin: Optional[Path],
    pages: int = 1,
    force_best: bool = False,
) -> Dict[str, str]:
    images, error = _render_pdf_images(pdf_path, poppler_bin, pages=pages)
    if error:
        return {"text": "", "error": error}
    return _ocr_images_best(images, force_best=force_best)


def _normalize_month_key(value: str) -> str:
    key = value.strip().lower()
    return key.replace("\u00df", "ss").replace("\u00e4", "ae").replace("\u00f6", "oe").replace("\u00fc", "ue")


def _valid_day_month(day: int, month: int) -> bool:
    return 1 <= day <= 31 and 1 <= month <= 12


def _build_date(year: int, month: int, day: int) -> Optional[datetime]:
    if not _valid_day_month(day, month):
        return None
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _parse_iso(match: re.Match) -> Optional[datetime]:
    year, month, day = (int(part) for part in match.groups())
    return _build_date(year, month, day)


def _parse_dmy(match: re.Match) -> Optional[datetime]:
    day, month, year = (int(part) for part in match.groups())
    return _build_date(year, month, day)


def _parse_dmy_short(match: re.Match) -> Optional[datetime]:
    day, month, year_short = (int(part) for part in match.groups())
    if not _valid_day_month(day, month):
        return None
    if 0 <= year_short <= 79:
        year = 2000 + year_short
    else:
        year = 1900 + year_short
    return _build_date(year, month, day)


def _parse_month_name(match: re.Match) -> Optional[datetime]:
    day_str, month_name, year_str = match.groups()
    month_key = _normalize_month_key(month_name)
    month = MONTH_MAP.get(month_key)
    if not month:
        return None
    return _build_date(int(year_str), int(month), int(day_str))


def _parse_vergoelst(match: re.Match) -> Optional[datetime]:
    day, month, year_short = (int(part) for part in match.groups())
    if not _valid_day_month(day, month):
        return None
    if 0 <= year_short <= 69:
        year = 2000 + year_short
    else:
        year = 1900 + year_short
    return _build_date(year, month, day)


def _parse_tadano(match: re.Match) -> Optional[datetime]:
    day_str, month_name, year_str = match.groups()
    month_key = _normalize_month_key(month_name)
    month = MONTH_MAP.get(month_key)
    if not month:
        return None
    return _build_date(int(year_str), int(month), int(day_str))


def _find_first_date(text: str, patterns: List[Tuple[re.Pattern, callable]]) -> Optional[datetime]:
    best_pos = None
    best_date = None
    for pattern, parser in patterns:
        for match in pattern.finditer(text):
            parsed = parser(match)
            if not parsed:
                continue
            pos = match.start()
            if best_pos is None or pos < best_pos:
                best_pos = pos
                best_date = parsed
    return best_date


def extract_date(text: str) -> Optional[datetime]:
    patterns = [
        (ISO_REGEX, _parse_iso),
        (YMD_SLASH_REGEX, _parse_iso),
        (DMY_DOT_REGEX, _parse_dmy),
        (DMY_DASH_REGEX, _parse_dmy),
        (DMY_SLASH_REGEX, _parse_dmy),
        (DMY_DOT_SHORT_REGEX, _parse_dmy_short),
        (DMY_DASH_SHORT_REGEX, _parse_dmy_short),
        (DMY_SLASH_SHORT_REGEX, _parse_dmy_short),
        (MONTH_NAME_REGEX, _parse_month_name),
        (DMY_MONTH_DASH_REGEX, _parse_tadano),
    ]
    return _find_first_date(text, patterns)


def _extract_date_from_lines(lines: List[str]) -> Optional[datetime]:
    for line in lines:
        dt = extract_date(line)
        if dt:
            return dt
    return None


def _extract_vergoelst_date(lines: List[str]) -> Optional[datetime]:
    for line in lines:
        dt = _find_first_date(line, [(VERGOELST_REGEX, _parse_vergoelst)])
        if dt:
            return dt
    return None


def _extract_tadano_date(lines: List[str]) -> Optional[datetime]:
    for line in lines:
        dt = _find_first_date(line, [(TADANO_REGEX, _parse_tadano)])
        if dt:
            return dt
    return None


def _extract_date_after_label(line: str, label: str) -> Optional[datetime]:
    lower = line.lower()
    idx = lower.find(label)
    if idx < 0:
        return None
    after = line[idx + len(label) :]
    return extract_date(after)


def _extract_belegdatum_inline(lines: List[str]) -> Optional[datetime]:
    labels = ["beleg-datum", "belegdatum", "beleg datum"]
    for line in lines:
        lower = line.lower()
        for label in labels:
            if label in lower:
                dt = _extract_date_after_label(line, label)
                if dt:
                    return dt
    return _extract_date_from_lines(lines)


def extract_date_with_priority(text: str) -> Tuple[Optional[datetime], str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    def _extract_for_labels(
        labels: List[str],
        extractor=_extract_date_from_lines,
        exclude: Optional[List[str]] = None,
    ) -> Optional[datetime]:
        for idx, line in enumerate(lines):
            lower = line.lower()
            if any(label in lower for label in labels):
                if exclude and any(block in lower for block in exclude):
                    continue
                candidate_lines = [line]
                if idx + 1 < len(lines):
                    candidate_lines.append(lines[idx + 1])
                return extractor(candidate_lines)
        return None

    abholdatum_labels = ["abholdatum", "abhol-datum"]
    has_abholdatum = any(any(label in line.lower() for label in abholdatum_labels) for line in lines)
    if has_abholdatum:
        abhol_date = _extract_for_labels(abholdatum_labels)
        if not abhol_date:
            auftrags_date = _extract_for_labels(["auftragsdatum"])
            if auftrags_date:
                return auftrags_date, "auftragsdatum"

    generic_excludes = [
        "auftragsdatum",
        "lieferdatum",
        "lieferscheindatum",
        "lieferscheintermin",
        "liefertermin",
        "belegdatum",
        "beleg-datum",
        "beleg datum",
        "rechnungsdatum",
        "bestelldatum",
        "druckdatum",
        "versanddatum",
        "abholdatum",
        "abhol-datum",
        "warenausgang",
        "ausgang",
        "delivery by date",
    ]
    priorities = [
        ("lieferdatum", ["lieferdatum", "lieferscheindatum", "datum lieferung", "tag der lieferung"]),
        ("lieferdatum", ["lieferscheintermin", "liefertermin", "lieferschein-termin", "liefertermin-datum"]),
        ("lieferdatum", ["warenausgang", "ausgang", "ausgangsdatum"]),
        ("lieferdatum", ["delivery by date"], _extract_tadano_date),
        ("lieferdatum", ["delivery date", "delivery date:"], _extract_date_from_lines),
        ("belegdatum", ["beleg-datum", "belegdatum", "beleg datum"], _extract_belegdatum_inline),
        ("belegdatum", ["rechnungsdatum"]),
        ("druckdatum", ["druckdatum/-zeit", "druckdatum", "druckdatum - zeit", "druckdatum/zeit"]),
        ("datum", ["document date"], _extract_tadano_date),
        ("datum", ["document date"], _extract_date_from_lines),
        ("datum", ["datum"], _extract_date_from_lines, generic_excludes),
        ("auftragsdatum", ["auftragsdatum"]),
        ("auftragsdatum", ["auftragdatum"]),
    ]

    for source, labels, *maybe_extractor in priorities:
        extractor = maybe_extractor[0] if maybe_extractor else _extract_date_from_lines
        excludes = None
        if len(maybe_extractor) > 1:
            excludes = maybe_extractor[1]
        dt = _extract_for_labels(labels, extractor=extractor, exclude=excludes)
        if dt:
            return dt, source

    fallback_date = extract_date(text)
    return fallback_date, "fallback"


NUMERIC_DATE_REGEX = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b")
ISO_DATE_REGEX = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _normalize_date_text(text: str) -> str:
    cleaned = text.replace(",", ".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"(?<=\d)[oO](?=\d)", "0", cleaned)
    cleaned = re.sub(r"(?<=\d)[oO](?=[./-])", "0", cleaned)
    cleaned = re.sub(r"(?<=[./-])[oO](?=\d)", "0", cleaned)
    return cleaned.strip()


def _parse_numeric_date(day_str: str, month_str: str, year_str: str) -> Optional[datetime]:
    try:
        day = int(day_str)
        month = int(month_str)
    except ValueError:
        return None
    if len(year_str) == 2:
        try:
            year_short = int(year_str)
        except ValueError:
            return None
        year = 2000 + year_short if year_short <= 79 else 1900 + year_short
    else:
        try:
            year = int(year_str)
        except ValueError:
            return None
    return _build_date(year, month, day)


def _collect_date_candidates(text: str) -> List[Tuple[datetime, str]]:
    candidates: List[Tuple[datetime, str]] = []
    normalized = _normalize_date_text(text)
    for match in ISO_DATE_REGEX.finditer(normalized):
        dt = _parse_iso(match)
        if dt:
            candidates.append((dt, match.group(0)))
    for match in NUMERIC_DATE_REGEX.finditer(normalized):
        day_str, month_str, year_str = match.groups()
        dt = _parse_numeric_date(day_str, month_str, year_str)
        if dt:
            candidates.append((dt, match.group(0)))
    for match in DMY_MONTH_DASH_REGEX.finditer(normalized):
        dt = _parse_tadano(match)
        if dt:
            candidates.append((dt, match.group(0)))
    return candidates


def _extract_candidates_from_lines(
    lines: List[str],
    source: str,
    base_confidence: float,
) -> List[Dict[str, object]]:
    candidates: List[Dict[str, object]] = []
    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        normalized_line = _normalize_date_text(line)
        label_type = ""
        for label_name, pattern in LABEL_PATTERNS:
            if pattern.search(lower):
                label_type = label_name
                break
        if not label_type and "vom" in lower and ("lieferschein" in lower or "beleg" in lower):
            label_type = "vom"
        context_lines = [normalized_line]
        if idx + 1 < len(lines):
            context_lines.append(_normalize_date_text(lines[idx + 1]))
        context_text = " ".join(context_lines)
        date_candidates = _collect_date_candidates(context_text)
        if not date_candidates:
            continue
        for date_obj, date_str in date_candidates:
            confidence = base_confidence
            if label_type == "lieferdatum":
                confidence += 0.2
            elif label_type == "belegdatum":
                confidence += 0.15
            elif label_type == "rechnungsdatum":
                confidence += 0.1
            elif label_type == "druckdatum":
                confidence += 0.05
            elif label_type == "vom":
                confidence += 0.05
            confidence = min(confidence, 0.99)
            evidence = raw_line.strip()
            if len(evidence) > 120:
                evidence = evidence[:117] + "..."
            candidates.append(
                {
                    "date": date_obj,
                    "raw": date_str,
                    "label": label_type or "generic",
                    "priority": LABEL_PRIORITY.get(label_type or "generic", 99),
                    "confidence": confidence,
                    "evidence": evidence,
                    "source": source,
                }
            )
    if not candidates:
        for raw_line in lines:
            normalized_line = _normalize_date_text(raw_line)
            date_candidates = _collect_date_candidates(normalized_line)
            for date_obj, date_str in date_candidates:
                evidence = raw_line.strip()
                if len(evidence) > 120:
                    evidence = evidence[:117] + "..."
                candidates.append(
                    {
                        "date": date_obj,
                        "raw": date_str,
                        "label": "generic",
                        "priority": LABEL_PRIORITY.get("generic", 99),
                        "confidence": base_confidence,
                        "evidence": evidence,
                        "source": source,
                    }
                )
    return candidates


def _select_best_candidate(candidates: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            item.get("priority", 99),
            -(item.get("confidence", 0.0) or 0.0),
        ),
    )[0]


def _extract_date_from_filename(filename: str) -> Optional[Dict[str, object]]:
    # Fallback 1: OCR/Regex-basiert (bestehend)
    candidates = _extract_candidates_from_lines([filename], "filename_fallback", 0.40)
    best = _select_best_candidate(candidates)
    if best:
        return best

    # Fallback 2: Scan-Pattern wie scan_20251127071452.pdf (YYYYMMDDHHMMSS) -> 2025-11-27
    match = re.search(r"scan_(20\d{2})(\d{2})(\d{2})", filename, flags=re.IGNORECASE)
    if not match:
        # Allgemeiner Fallback: erste YYYYMMDD-Sequenz im Namen (auch wenn danach weitere Ziffern folgen)
        match = re.search(r"(20\d{2})(\d{2})(\d{2})", filename)
    if not match:
        return None
    try:
        year, month, day = (int(part) for part in match.groups())
    except ValueError:
        return None
    date_obj = _build_date(year, month, day)
    if not date_obj:
        return None
    return {
        "date": date_obj,
        "raw": match.group(0),
        "label": "filename_scan",
        "priority": LABEL_PRIORITY.get("generic", 99),
        "confidence": 0.35,
        "evidence": filename,
        "source": "filename_scan",
    }


def extract_best_date(
    pdf_path: Path,
    images: Optional[List[object]] = None,
    textlayer_pages: Optional[List[str]] = None,
    pages: int = OCR_PAGES,
    known_rotation: Optional[int] = None,
    allow_ocr: bool = True,
    allow_filename_fallback: bool = True,
) -> Dict[str, object]:
    textlayer_pages = textlayer_pages or []
    if not textlayer_pages:
        textlayer_pages, text_err = _extract_textlayer(pdf_path, pages=pages)
        if text_err:
            _LOGGER.warning("date textlayer error: %s", text_err)
    textlayer_text = "\n".join(textlayer_pages)
    textlayer_words = len(textlayer_text.split())
    if textlayer_text.strip() and (len(textlayer_text.strip()) >= 80 or textlayer_words >= 12):
        if date_parser:
            dp_iso, dp_reason = date_parser.extract_date_from_text(textlayer_text)
            if dp_iso:
                try:
                    dp_date = datetime.strptime(dp_iso, "%Y-%m-%d")
                    _LOGGER.info("date_parser (textlayer) found: %s (%s)", dp_iso, dp_reason)
                    return {
                        "date": dp_date,
                        "label": "smart_parser",
                        "priority": 1,
                        "confidence": 0.95,
                        "evidence": dp_reason,
                        "source": "textlayer_smart",
                    }
                except ValueError:
                    pass
        candidates = _extract_candidates_from_lines(textlayer_text.splitlines(), "textlayer", 0.90)
        best = _select_best_candidate(candidates)
        if best:
            _LOGGER.info(
                "date textlayer selected label=%s conf=%.2f",
                best.get("label"),
                best.get("confidence", 0.0),
            )
            return best

    if not allow_ocr:
        images = [] if images is None else images

    if images is None:
        images, img_err = _render_pdf_images(pdf_path, _POPPLER_BIN, pages=pages)
        if img_err:
            _LOGGER.warning("date ocr render error: %s", img_err)
            images = []

    if images:
        # Strategie: Nur Rotation 0° testen; andere Rotationen NUR als Fallback wenn nichts gefunden
        best_image = images[0]
        best_rotation = known_rotation if known_rotation is not None else 0
        
        # Erste Rotation (normalerweise 0° oder bekannte Rotation)
        first_texts = _ocr_rois(best_image, best_rotation, ["roi1", "roi2"])
        combined_text = "\n".join(first_texts)
        first_score = _score_rotation_text(combined_text)
        
        # Prüfe ob erste Rotation bereits gute Ergebnisse liefert
        has_date_hints = _count_date_hits(combined_text) > 0
        has_good_score = first_score > 100
        
        # Rotation-Fallback NUR wenn erste Rotation unzureichend
        if not has_date_hints or not has_good_score:
            _LOGGER.info("date rotation fallback: roi score=%d, date_hits=%d; trying full-page ocr at 0°", 
                        first_score, _count_date_hits(combined_text))
            # Versuche erst Full-Page OCR bei 0° (kann better sein als ROI)
            try:
                full_ocr_text = _ocr_image(best_image, best_rotation, timeout=OCR_TIMEOUT_SECONDS)
                full_score = _score_rotation_text(full_ocr_text)
                if _count_date_hits(full_ocr_text) > 0 or full_score > 150:
                    _LOGGER.info("date rotation: full-page OCR at 0° found dates or high score (%d)", full_score)
                    combined_text = full_ocr_text
                    has_date_hints = True
                    has_good_score = True
            except (pytesseract.TesseractError, TimeoutError):
                pass
        
        # Falls IMMER NOCH keine Daten: Versuche Fallback-Rotationen
        if not has_date_hints or not has_good_score:
            _LOGGER.info("date rotation: still no success; trying 90° and 180°")
            candidates_log: List[Tuple[int, int, int]] = [(1, 0, first_score)]
            best_score = first_score
            
            # 90/180/270 als Fallback testen (90° kann in beide Richtungen auftreten)
            fallback_rotations = [90, 180, 270]
            for rotation in fallback_rotations:
                try:
                    texts = _ocr_rois(best_image, rotation, ["roi1", "roi2"])
                    full = " ".join(texts)
                    score = _score_rotation_text(full)
                    candidates_log.append((1, rotation, score))
                    if score > best_score:
                        best_score = score
                        best_rotation = rotation
                        combined_text = full
                        if _count_date_hits(full) > 0:
                            has_date_hints = True
                except (pytesseract.TesseractError, TimeoutError):
                    pass
            
            if best_rotation != 0:
                _LOGGER.info("date rotation selected=%d from %s", best_rotation, candidates_log)
        else:
            _LOGGER.info("date rotation 0° sufficient (first_score=%d)", first_score)
        
        final_texts = combined_text.splitlines() if isinstance(combined_text, str) else [combined_text]
        if date_parser:
            dp_iso, dp_reason = date_parser.extract_date_from_text(combined_text)
            if dp_iso:
                try:
                    dp_date = datetime.strptime(dp_iso, "%Y-%m-%d")
                    _LOGGER.info("date_parser (ocr) found: %s (%s)", dp_iso, dp_reason)
                    return {
                        "date": dp_date,
                        "label": "smart_parser",
                        "priority": 1,
                        "confidence": 0.90,
                        "evidence": dp_reason,
                        "source": "ocr_smart",
                    }
                except ValueError:
                    pass
        candidates = _extract_candidates_from_lines(final_texts, "ocr", 0.70)
        best = _select_best_candidate(candidates)
        if best:
            _LOGGER.info(
                "date ocr selected label=%s conf=%.2f",
                best.get("label"),
                best.get("confidence", 0.0),
            )
            return best

        crop_date = _extract_date_from_crops(best_image, best_rotation, combined_text)
        if crop_date:
            _LOGGER.info("date ocr_crop selected")
            return {
                "date": crop_date,
                "label": "ocr_crop",
                "priority": 2,
                "confidence": 0.80,
                "evidence": "Targeted OCR on date fields",
                "source": "ocr_crop",
            }

        # Fallback to full page OCR
        _LOGGER.info("ROI OCR found no date. Falling back to full page OCR.")
        try:
            full_text = _ocr_image(best_image, best_rotation, timeout=OCR_TIMEOUT_SECONDS)
            if full_text and date_parser:
                dp_iso, dp_reason = date_parser.extract_date_from_text(full_text)
                if dp_iso:
                    try:
                        dp_date = datetime.strptime(dp_iso, "%Y-%m-%d")
                        _LOGGER.info("date_parser (ocr_full) found: %s (%s)", dp_iso, dp_reason)
                        return {
                            "date": dp_date,
                            "label": "smart_parser_full",
                            "priority": 1,
                            "confidence": 0.85,
                            "evidence": dp_reason,
                            "source": "ocr_smart_full",
                        }
                    except ValueError:
                        pass
            
            if full_text:
                candidates = _extract_candidates_from_lines(full_text.splitlines(), "ocr_full", 0.60)
                best = _select_best_candidate(candidates)
                if best:
                    _LOGGER.info(
                        "date ocr_full selected label=%s conf=%.2f",
                        best.get("label"),
                        best.get("confidence", 0.0),
                    )
                    return best
        except (pytesseract.TesseractError, TimeoutError) as e:
            _LOGGER.warning("Full page OCR fallback failed: %s", e)

    if allow_filename_fallback:
        filename_candidate = _extract_date_from_filename(pdf_path.name)
        if filename_candidate:
            _LOGGER.info("date filename fallback selected conf=%.2f", filename_candidate.get("confidence", 0.0))
            return filename_candidate

    return {
        "date": None,
        "label": "none",
        "priority": LABEL_PRIORITY.get("generic", 99),
        "confidence": 0.0,
        "evidence": "",
        "source": "none",
    }

def load_suppliers_db() -> Dict[str, List[Dict[str, object]]]:
    SUPPLIERS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SUPPLIERS_DB_PATH.exists():
        data = {"suppliers": []}
        SUPPLIERS_DB_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    try:
        return json.loads(SUPPLIERS_DB_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"suppliers": []}


def save_suppliers_db(data: Dict[str, List[Dict[str, object]]]) -> None:
    SUPPLIERS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUPPLIERS_DB_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _normalize_supplier_text(value: str) -> str:
    lowered = value.lower()
    lowered = lowered.replace("\u00df", "ss").replace("\u00e4", "ae").replace("\u00f6", "oe").replace("\u00fc", "ue")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _canonicalize_supplier(name: str) -> str:
    normalized = _normalize_supplier_text(name)
    return CANONICAL_SUPPLIERS.get(normalized, name)


def _detect_supplier_from_db(text: str) -> Optional[Tuple[str, str]]:
    data = load_suppliers_db()
    normalized_text = _normalize_supplier_text(text)
    entries = list(data.get("suppliers", []))
    entries.append({"name": "Vergoelst", "aliases": VERGOELST_ALIASES})
    for entry in entries:
        name = str(entry.get("name", "")).strip()
        aliases = entry.get("aliases", [])
        candidates = [name] + [str(alias) for alias in aliases if alias]
        for alias in candidates:
            normalized_alias = _normalize_supplier_text(alias)
            if normalized_alias and normalized_alias in normalized_text:
                return name or alias, alias
    return None


def _find_supplier_candidates_in_segment(text: str, segment_name: str) -> List[Dict[str, object]]:
    """Findet Supplier-Kandidaten in einem Segment (header/body/recipient)."""
    normalized_text = _normalize_supplier_text(text)
    if not normalized_text:
        return []

    candidates: List[Dict[str, object]] = []

    # DB Hits
    db_hit = _detect_supplier_from_db(text)
    if db_hit:
        supplier_name, alias = db_hit
        candidates.append(
            {
                "canonical": _canonicalize_supplier(supplier_name),
                "confidence": 0.90,
                "source": "db",
                "matched": alias,
                "segment": segment_name,
            }
        )

    # Keyword-Hits (inkl. Vergoelst)
    keyword_candidates = list(SUPPLIER_KEYWORDS.items())
    keyword_candidates.extend((alias, "Vergoelst") for alias in VERGOELST_ALIASES)
    # KSR hard aliases
    keyword_candidates.extend(
        [
            ("ksr", "KSR"),
            ("ksr logistic", "KSR"),
            ("ksr recycling", "KSR"),
            ("ksr gmbh", "KSR"),
        ]
    )

    for keyword, shortname in keyword_candidates:
        normalized_keyword = _normalize_supplier_text(keyword)
        if not normalized_keyword:
            continue
        if normalized_keyword in normalized_text:
            candidates.append(
                {
                    "canonical": _canonicalize_supplier(shortname),
                    "confidence": 0.95,
                    "source": "keywords",
                    "matched": keyword,
                    "segment": segment_name,
                }
            )

    # Regex for KSR variants
    if re.search(r"\bksr\s*(logistic|recycling)?\b", normalized_text, flags=re.IGNORECASE):
        candidates.append(
            {
                "canonical": "KSR",
                "confidence": 0.92,
                "source": "regex",
                "matched": "ksr( logistic| recycling)?",
                "segment": segment_name,
            }
        )

    return candidates


def _heuristic_supplier(text: str) -> Tuple[Optional[str], Optional[str], float]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    top_lines = lines[:40]
    blocked_terms = [
        "datum der uebergabe",
        "datum der uebernahme",
        "uebergabe",
        "uebernahme",
        "kommissionierliste",
        "lieferadresse",
        "lieferadressat",
        "rechnungsadresse",
        "rechnungsadresse",
        "lieferanschrift",
        "lieferschein",
        "lieferscheinnr",
        "versand",
        "versand-",
        "empfaenger",
        "adressat",
        "adresse",
        "datum",
    ]
    endings = [
        "gmbh",
        "ag",
        "kg",
        "gmbh & co",
        "gmbh & co. kg",
        "ltd",
        "inc",
        "sarl",
        "bv",
        "sp. z o.o",
        "sp z o o",
    ]
    address_markers = [
        "strasse",
        "street",
        "postfach",
        "plz",
        "de-",
        "d-",
    ]
    contact_markers = [
        "tel",
        "telefon",
        "fax",
        "ust",
        "ust-id",
        "ustid",
        "ustidnr",
        "steuer",
        "email",
        "mail",
        "web",
        "www",
    ]
    best_line = None
    best_score = 0.0
    for line in top_lines:
        normalized_line = _normalize_supplier_text(line)
        if not normalized_line or any(term in normalized_line for term in blocked_terms):
            continue
        tokens = set(normalized_line.split())
        score = 0.0
        # Endungen nur als ganze Wörter werten ("ag" soll nicht in "tag" matchen).
        for marker in endings:
            if " " in marker:
                if marker in normalized_line:
                    score += 0.9
                    break
            elif marker in tokens:
                score += 0.9
                break
        if any(marker in normalized_line for marker in contact_markers):
            score += 0.4
        if any(marker in normalized_line for marker in address_markers):
            score += 0.25
        digit_ratio = sum(1 for ch in normalized_line if ch.isdigit()) / max(len(normalized_line), 1)
        if digit_ratio > 0.35:
            score -= 0.2
        if score > best_score:
            best_score = score
            best_line = line
    if best_line and best_score >= 0.7:
        return best_line, best_line, min(best_score, 1.0)
    return None, None, 0.0


def detect_supplier(text: str) -> Tuple[str, float, str, str]:
    supplier, confidence, source, guess, _cands = detect_supplier_detailed(text)
    return supplier, confidence, source, guess


def detect_supplier_detailed(
    text: str,
    doc_type_hint: Optional[str] = None,
) -> Tuple[str, float, str, str, List[Dict[str, object]]]:
    """Supplier-Erkennung mit Segmentierung und Kandidatenliste.

    Returns:
        (supplier, confidence, source, guess_line, candidates)
    """

    segmented = segment_text(text, header_max_lines=40, recipient_max_lines=20)
    header_text = "\n".join(segmented.header_lines)
    body_text = "\n".join(segmented.body_lines)
    recipient_text = "\n".join(segmented.recipient_lines)

    # Segmentgewichtung: header > body >> recipient
    segment_multiplier = {"header": 1.0, "body": 0.85, "recipient": 0.20, "role": 0.95}

    candidates: List[Dict[str, object]] = []
    candidates.extend(_find_supplier_candidates_in_segment(header_text, "header"))
    candidates.extend(_find_supplier_candidates_in_segment(body_text, "body"))
    candidates.extend(_find_supplier_candidates_in_segment(recipient_text, "recipient"))

    # ÜBERNAHMESCHEIN: Rollenblöcke priorisieren (Beförderer/Abfallentsorger)
    try:
        if (doc_type_hint or "").strip().upper() == "ÜBERNAHMESCHEIN":
            def _extract_role_block_local(marker: str, max_lines: int = 20) -> str:
                lines = [ln.rstrip() for ln in (text or "").splitlines()]
                if not lines:
                    return ""
                marker_norm = _normalize_supplier_text(marker)
                for idx, ln in enumerate(lines):
                    if marker_norm and marker_norm in _normalize_supplier_text(ln):
                        out: list[str] = [ln]
                        taken = 0
                        j = idx + 1
                        while j < len(lines) and taken < max_lines:
                            if not (lines[j] or "").strip():
                                break
                            out.append(lines[j])
                            taken += 1
                            j += 1
                        return "\n".join(out)
                return ""

            role_texts = [
                _extract_role_block_local("Beförderer (Name, Anschrift)"),
                _extract_role_block_local("Befoerderer (Name, Anschrift)"),
                _extract_role_block_local("Abfallentsorger (Name, Anschrift)"),
                _extract_role_block_local("Abfallentsorger"),
            ]
            role_joined = "\n".join([t for t in role_texts if t])
            role_norm = _normalize_supplier_text(role_joined)
            if re.search(r"\bksr\b", role_norm, flags=re.IGNORECASE) or re.search(r"ks[-\s]?logistic|ks[-\s]?recycling", role_norm, flags=re.IGNORECASE):
                candidates.append(
                    {
                        "canonical": "KSR",
                        "confidence": 0.99,
                        "source": "role_block",
                        "matched": "Beförderer/Abfallentsorger",
                        "segment": "role",
                    }
                )
    except Exception:
        pass

    # Hard Fix Liebherr: nur wenn im Header/Letterhead (nicht Recipient-only)
    # Liebherr als ERSTES einfügen (höchste Priorität vor Heuristik)
    # Wichtig: Liebherr immer auf 0.995 setzen, um Franz Bracht (Heuristik 0.7) zu überschreiben
    header_norm = _normalize_supplier_text(header_text)
    liebherr_detected = (
        "liebherr" in header_norm
        or "liebherr werk" in header_norm
        or "werk ehingen" in header_norm
        or "www.liebherr.com" in header_norm
    )
    
    if liebherr_detected:
        candidates.insert(
            0,
            {
                "canonical": "Liebherr",
                "confidence": 0.995,  # Sehr hoch, damit Heuristik nicht gewinnt
                "source": "hardfix_liebherr",
                "matched": "Liebherr(header_detected)",
                "segment": "header",
            }
        )

    # Heuristik nur auf header/body, nicht auf recipient
    # ABER: wenn Liebherr im Header erkannt wurde, nicht die Heuristik laufen lassen
    if not liebherr_detected:
        guess, guess_line, guess_conf = _heuristic_supplier(header_text + "\n" + body_text)
        if guess:
            candidates.append(
                {
                    "canonical": _canonicalize_supplier(guess),
                    "confidence": float(guess_conf or 0.0),
                    "source": "heuristic",
                    "matched": guess_line or guess,
                    "segment": "header" if _normalize_supplier_text(guess_line or "") in header_norm else "body",
                }
            )

    # Apply segment penalty
    for c in candidates:
        seg = str(c.get("segment") or "body")
        base = float(c.get("confidence") or 0.0)
        c["confidence"] = round(base * segment_multiplier.get(seg, 0.85), 4)

    # Deduplicate by canonical+segment+source+matched, keep max confidence
    dedup: Dict[tuple, Dict[str, object]] = {}
    for c in candidates:
        key = (c.get("canonical"), c.get("segment"), c.get("source"), c.get("matched"))
        if key not in dedup or float(c.get("confidence") or 0.0) > float(dedup[key].get("confidence") or 0.0):
            dedup[key] = c
    candidates = list(dedup.values())

    # Pick best candidate
    candidates.sort(key=lambda x: float(x.get("confidence") or 0.0), reverse=True)
    top = candidates[0] if candidates else None
    if top and str(top.get("canonical") or ""):
        return (
            str(top.get("canonical")),
            float(top.get("confidence") or 0.0),
            str(top.get("source") or "none"),
            str(top.get("matched") or ""),
            candidates[:8],
        )

    return "Unbekannt", 0.0, "none", "", candidates[:8]


def _ocr_date_crop(image, crop_box: Tuple[int, int, int, int]) -> str:
    crop = image.crop(crop_box)
    config = "--psm 7 -c tessedit_char_whitelist=0123456789./-"
    try:
        return _ocr_image(crop, rotation=0, config=config, timeout=min(DATE_CROP_OCR_TIMEOUT, OCR_TIMEOUT_SECONDS))
    except (pytesseract.TesseractError, TimeoutError):
        config = "--psm 6 -c tessedit_char_whitelist=0123456789./-"
        try:
            return _ocr_image(crop, rotation=0, config=config, timeout=min(DATE_CROP_OCR_TIMEOUT, OCR_TIMEOUT_SECONDS))
        except (pytesseract.TesseractError, TimeoutError):
            return ""


def _extract_date_from_crops(image, rotation: int, text: str) -> Optional[datetime]:
    if image is None:
        return None
    rotated = image.rotate(rotation, expand=True) if rotation else image
    width, height = rotated.size
    crops = [
        (0, 0, int(width * 0.6), int(height * 0.35)),
        (int(width * 0.4), 0, width, int(height * 0.35)),
        (0, 0, width, int(height * 0.35)),
    ]
    if text and any(label in text.lower() for label in DATE_LABELS):
        crops.append((0, 0, width, int(height * 0.45)))
    for crop_box in crops:
        try:
            crop_text = _ocr_date_crop(rotated, crop_box)
        except (pytesseract.TesseractError, TimeoutError):
            continue
        dt = extract_date(crop_text)
        if dt:
            return dt
    return None


def _debug_extract_log(payload: Dict[str, str]) -> None:
    if not DEBUG_EXTRACT:
        return
    with _LOG_LOCK:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _is_ocr_gibberish(value: str) -> bool:
    if not value:
        return False
    letters = sum(1 for ch in value if ch.isalpha())
    if letters < 3:
        return True
    total = len(value)
    non_alnum = sum(1 for ch in value if not ch.isalnum())
    if total >= 8 and letters / total < 0.3 and non_alnum / total > 0.4:
        return True
    return False


_FILENAME_ALLOWED = re.compile(r"[^a-zA-Z0-9_\-\.äöüÄÖÜß]+")


def sanitize_filename(value: str) -> str:
    cleaned = value.strip()
    cleaned = (
        cleaned.replace("\u00df", "ss")
        .replace("\u00e4", "ae")
        .replace("\u00f6", "oe")
        .replace("\u00fc", "ue")
    )
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = _FILENAME_ALLOWED.sub("_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._")
    return cleaned or "Unbekannt"


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:6]


def _truncate_with_hash(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    suffix = f"_{_short_hash(value)}"
    keep_len = max_len - len(suffix)
    if keep_len < 1:
        return value[:max_len]
    return f"{value[:keep_len]}{suffix}"


def build_new_filename(
    supplier: str,
    date_obj: Optional[datetime],
    delivery_note_nr: Optional[str] = None,
    date_format: str = DEFAULT_DATE_FORMAT,
    max_supplier_len: int = 40,
    max_base_len: int = 120,
) -> str:
    if date_obj is not None:
        date_part = date_obj.strftime(date_format)
    else:
        date_part = "unbekanntes-Datum"

    if not supplier:
        supplier = "Unbekannt"

    safe_supplier = sanitize_filename(supplier)
    safe_supplier = _truncate_with_hash(safe_supplier, max_supplier_len)

    base_parts = [safe_supplier, date_part]
    if delivery_note_nr:
        safe_delivery_nr = sanitize_filename(delivery_note_nr)
        # Truncate to avoid extremely long parts
        safe_delivery_nr = _truncate_with_hash(safe_delivery_nr, 30)
        base_parts.append(safe_delivery_nr)

    base_name = "_".join(base_parts)
    base_name = sanitize_filename(base_name)  # Sanitize the final combined name
    base_name = _truncate_with_hash(base_name, max_base_len)
    return f"{base_name}.pdf"


def get_unique_path(target_dir: Path, filename: str) -> Path:
    candidate = target_dir / filename
    counter = 1
    while candidate.exists():
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        candidate = target_dir / f"{stem}_{counter:02d}{suffix}"
        counter += 1
    return candidate


def _move_pdf_with_name(pdf_path: Path, output_dir: Path, filename: str) -> Tuple[Optional[Path], str]:
    try:
        with _FS_LOCK:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path = output_dir / filename
            # Nur bei echtem Konflikt (andere Datei) unique path generieren
            if target_path.exists():
                try:
                    if pdf_path.resolve() == target_path.resolve():
                        # Quelle = Ziel, nichts tun
                        return target_path, ""
                except (OSError, ValueError):
                    pass
                # Echtes Duplikat: unique path
                target_path = get_unique_path(output_dir, filename)
            pdf_path.replace(target_path)
        return target_path, ""
    except OSError as exc:
        return None, f"move_failed: {exc}"


def process_pdf(pdf_path: Path, output_dir: Path, date_format: str = DEFAULT_DATE_FORMAT) -> Dict[str, object]:
    result: Dict[str, object] = {
        "supplier": "",
        "supplier_raw": "",
        "supplier_canonical": "",
        "supplier_confidence": "",
        "supplier_source": "",
        "supplier_guess_line": "",
        "supplier_matched_alias": "",
        "supplier_candidates": [],
        "supplier_gibberish": "",
        "date": "",
        "date_source": "",
        "date_confidence": "",
        "date_evidence": "",
        "out_name": "",
        "status": "error",
        "error": "",
        "tesseract_path": str(_TESSERACT_PATH) if _TESSERACT_PATH else "",
        "poppler_bin": str(_POPPLER_BIN) if _POPPLER_BIN else "",
        "tesseract_status": "ok" if _TESSERACT_OK else "not_found",
        "poppler_status": "ok" if _POPPLER_OK else "not_found",
        "ocr_rotation": "",
        "ocr_rotation_reason": "",
        "rotate_hint": "",
        "doc_type_scores": {},
        "doc_type_evidence_by_type": {},
        "parsing_failed": False,
    }

    # 1) Zuerst Text-Layer versuchen (deutlich schneller als OCR)
    textlayer_pages, textlayer_err = _extract_textlayer(pdf_path, pages=OCR_PAGES)
    textlayer_text = "\n".join(textlayer_pages) if textlayer_pages else ""

    supplier = ""
    supplier_confidence = 0.0
    supplier_source = "none"
    supplier_guess_line = ""
    supplier_candidates: List[Dict[str, object]] = []

    # Wenn Textlayer vorhanden, verwende ihn zur Lieferantenerkennung
    if textlayer_text.strip():
        s, c, src, guess, cands = detect_supplier_detailed(textlayer_text)
        supplier, supplier_confidence, supplier_source, supplier_guess_line = s, c, src, guess
        supplier_candidates = cands or []
        
        # Canonicalize supplier
        supplier_raw = supplier
        supplier_canonical = supplier
        supplier_matched_alias = ""
        
        if canonicalize_supplier is not None and supplier and supplier != "Unbekannt":
            try:
                match = canonicalize_supplier(supplier, textlayer_text)
                if match:
                    supplier_canonical = match.canonical_name
                    supplier_matched_alias = match.matched_alias
                    # Update confidence wenn Canonicalizer höher ist
                    if match.confidence > supplier_confidence:
                        supplier_confidence = match.confidence
            except Exception as exc:
                _LOGGER.warning(f"Canonicalization failed: {exc}")

    # 2) Datum über Textlayer versuchen; KEIN OCR/Render hier (sonst doppelte PDF->Image Konvertierung)
    date_pick = extract_best_date(
        pdf_path,
        images=None,
        textlayer_pages=textlayer_pages,
        pages=OCR_PAGES,
        known_rotation=None,
        allow_ocr=False,
        allow_filename_fallback=False,
    )
    date_obj = date_pick.get("date")
    date_source = date_pick.get("source", "")
    date_confidence = date_pick.get("confidence", 0.0) or 0.0
    date_evidence = date_pick.get("evidence", "") or ""

    # Early-Exit: Wenn Textlayer ausreichende Konfidenz liefert, überspringe OCR komplett
    skip_ocr = (
        date_obj and date_confidence >= 0.80 and
        supplier and supplier != "Unbekannt" and supplier_confidence >= 0.80
    )

    # 3) Falls Textlayer nicht aussagekräftig: OCR als Fallback durchführen
    rotation_value = 0
    images: List[object] = []
    ocr_text = ""
    if not skip_ocr and ((not textlayer_text.strip()) or (not date_obj)):
        images, render_error = _render_pdf_images(pdf_path, _POPPLER_BIN, pages=OCR_PAGES)
        if render_error and not textlayer_err:
            # Nur melden, wenn nicht bereits textlayer Fehler
            result["error"] = render_error
            result["parsing_failed"] = True
        
        # VEREINFACHT: Kein force_best mehr - normale Rotation mit Fallback
        ocr_result = _ocr_images_best(images or [], force_best=False) if images else {"text": "", "error": render_error or ""}
        if not ocr_result.get("error"):
            ocr_text = ocr_result.get("text", "")
            # Lieferantenerkennung per OCR nur falls vorher unbekannt oder geringe Konfidenz
            if (not supplier) or supplier == "Unbekannt" or supplier_confidence < 0.5:
                s, c, src, guess, cands = detect_supplier_detailed(ocr_text)
                supplier, supplier_confidence, supplier_source, supplier_guess_line = s, c, src, guess
                supplier_candidates = cands or []
                
                # Canonicalize supplier (OCR)
                supplier_raw = supplier
                supplier_canonical = supplier
                supplier_matched_alias = ""
                
                if canonicalize_supplier is not None and supplier and supplier != "Unbekannt":
                    try:
                        combined_text = "\n".join([t for t in (textlayer_text, ocr_text) if t])
                        match = canonicalize_supplier(supplier, combined_text)
                        if match:
                            supplier_canonical = match.canonical_name
                            supplier_matched_alias = match.matched_alias
                            if match.confidence > supplier_confidence:
                                supplier_confidence = match.confidence
                    except Exception as exc:
                        _LOGGER.warning(f"Canonicalization (OCR) failed: {exc}")
        result["ocr_rotation"] = ocr_result.get("rotation", "")
        result["ocr_rotation_reason"] = ocr_result.get("rotation_reason", "")
        result["rotate_hint"] = result["ocr_rotation"]
        try:
            rotation_value = int(result["ocr_rotation"] or 0)
        except ValueError:
            rotation_value = 0
        
        # Datum-Extraktion nur EINMAL mit OCR (nicht doppelt!)
        if not date_obj:
            # Nutze bereits gescannten OCR-Text statt erneut ROI-Scans
            if ocr_text:
                if date_parser:
                    dp_iso, dp_reason = date_parser.extract_date_from_text(ocr_text)
                    if dp_iso:
                        try:
                            date_obj = datetime.strptime(dp_iso, "%Y-%m-%d")
                            date_source = "ocr_smart"
                            date_confidence = 0.85
                            date_evidence = dp_reason
                        except ValueError:
                            pass
                
                # Fallback auf Regex wenn Parser nichts fand
                if not date_obj:
                    candidates = _extract_candidates_from_lines(ocr_text.splitlines(), "ocr", 0.70)
                    best_candidate = _select_best_candidate(candidates)
                    if best_candidate:
                        date_obj = best_candidate.get("date")
                        date_source = best_candidate.get("source", "ocr")
                        date_confidence = best_candidate.get("confidence", 0.70) or 0.70
                        date_evidence = best_candidate.get("evidence", "") or ""

            # Letzter Fallback: gezielte ROI/Crop-OCR OHNE erneutes Rendern
            if not date_obj and images:
                pick2 = extract_best_date(
                    pdf_path,
                    images=images,
                    textlayer_pages=[],
                    pages=OCR_PAGES,
                    known_rotation=rotation_value,
                    allow_ocr=True,
                    allow_filename_fallback=True,
                )
                if pick2.get("date"):
                    date_obj = pick2.get("date")
                    date_source = pick2.get("source", "ocr")
                    date_confidence = float(pick2.get("confidence", 0.0) or 0.0)
                    date_evidence = str(pick2.get("evidence", "") or "")

        # Optional: KI-OCR Fallback (PaddleOCR) nur wenn weiterhin unsicher
        need_paddle = (
            (not date_obj or date_confidence < 0.75)
            or (not supplier or supplier == "Unbekannt" or supplier_confidence < 0.70)
        )
        if need_paddle and images and USE_PADDLEOCR:
            try:
                paddle_text, paddle_conf, paddle_err = _paddle_ocr_image(images[0])
                if paddle_text and not paddle_err:
                    # Lieferant: nur überschreiben, wenn wir dadurch besser werden
                    if (not supplier) or supplier == "Unbekannt" or supplier_confidence < 0.70:
                        s2, c2, src2, guess2, cands2 = detect_supplier_detailed(paddle_text)
                        if s2 and s2 != "Unbekannt" and c2 >= supplier_confidence:
                            supplier, supplier_confidence, supplier_source, supplier_guess_line = s2, c2, "paddle", guess2
                            supplier_candidates = cands2 or []

                    # Datum: nur überschreiben, wenn wir dadurch besser werden
                    if (not date_obj) or (date_confidence < 0.75):
                        if date_parser:
                            dp_iso, dp_reason = date_parser.extract_date_from_text(paddle_text)
                            if dp_iso:
                                try:
                                    date_obj = datetime.strptime(dp_iso, "%Y-%m-%d")
                                    date_source = "paddle_smart"
                                    date_confidence = max(date_confidence, 0.88)
                                    date_evidence = dp_reason
                                except ValueError:
                                    pass
                        if not date_obj:
                            candidates = _extract_candidates_from_lines(paddle_text.splitlines(), "paddle", 0.72)
                            best_candidate = _select_best_candidate(candidates)
                            if best_candidate:
                                date_obj = best_candidate.get("date")
                                date_source = best_candidate.get("source", "paddle")
                                date_confidence = max(date_confidence, float(best_candidate.get("confidence", 0.72) or 0.72))
                                date_evidence = best_candidate.get("evidence", "") or ""
                elif paddle_err and paddle_err not in ("disabled", "unavailable"):
                    _LOGGER.info("PaddleOCR error: %s", paddle_err)
            except Exception as exc:
                _LOGGER.info("PaddleOCR fallback failed: %s", exc)
    gibberish = False
    if supplier_source == "heuristic" and _is_ocr_gibberish(supplier_guess_line or supplier):
        supplier = "Unbekannt"
        supplier_confidence = 0.0
        supplier_source = "none"
        supplier_guess_line = ""
        gibberish = True
    
    # Stelle sicher dass supplier_raw und supplier_canonical gesetzt sind
    # (falls nicht schon durch Canonicalizer gesetzt)
    if 'supplier_raw' not in locals():
        supplier_raw = supplier
    if 'supplier_canonical' not in locals():
        supplier_canonical = supplier
    if 'supplier_matched_alias' not in locals():
        supplier_matched_alias = ""
    
    result["supplier"] = supplier_canonical  # Nutze canonical name
    result["supplier_raw"] = supplier_raw
    result["supplier_canonical"] = supplier_canonical
    result["supplier_matched_alias"] = supplier_matched_alias
    result["supplier_confidence"] = f"{supplier_confidence:.2f}" if supplier_confidence else ""
    result["supplier_source"] = supplier_source
    result["supplier_guess_line"] = supplier_guess_line
    result["supplier_candidates"] = supplier_candidates[:3] if supplier_candidates else []
    result["supplier_gibberish"] = "1" if gibberish else ""
    result["date"] = date_obj.strftime(INTERNAL_DATE_FORMAT) if date_obj else ""
    result["date_source"] = date_source if date_obj else ""
    result["date_confidence"] = f"{date_confidence:.2f}" if date_obj else ""
    result["date_evidence"] = date_evidence if date_obj else ""
    if date_source == "filename_fallback":
        result["parsing_failed"] = True

    # Dokumentnummer: Supplier-spezifische Extraktion (neu)
    combined_text = "\n".join([t for t in (textlayer_text, ocr_text) if t])
    
    # Dokumenttyp-Klassifikation (DocType)
    doc_type = "SONSTIGES"
    doc_type_confidence = 0.50
    doc_type_evidence = ""
    doc_type_scores: Dict[str, float] = {}
    doc_type_evidence_by_type: Dict[str, List[str]] = {}
    
    if classify_doc_type is not None:
        try:
            doctype_result = classify_doc_type(combined_text, supplier_canonical)
            doc_type = doctype_result.doc_type
            doc_type_confidence = doctype_result.confidence
            doc_type_evidence = ", ".join(doctype_result.evidence[:3])  # Top-3 Keywords
            doc_type_scores = getattr(doctype_result, "scores", {}) or {}
            doc_type_evidence_by_type = getattr(doctype_result, "evidence_by_type", {}) or {}
            _LOGGER.info(f"DocType classified as '{doc_type}' (confidence={doc_type_confidence:.2f})")
        except Exception as exc:
            _LOGGER.warning(f"DocType classification failed: {exc}")

    # Supplier + DocType Coupling / Cross-check
    try:
        # 0) Rollenbasierte KSR-Erkennung (Beförderer/Abfallentsorger)
        # Nicht nur für ÜBERNAHMESCHEIN: manche Belege (auch Lieferschein-ähnlich)
        # enthalten eine Spalte "Beförderer" mit "KS- Logistic ...".
        def _extract_role_block(text: str, marker: str, max_lines: int = 20) -> str:
            lines = [ln.rstrip() for ln in (text or "").splitlines()]
            if not lines:
                return ""
            marker_norm = _normalize_supplier_text(marker)
            for idx, ln in enumerate(lines):
                if marker_norm and marker_norm in _normalize_supplier_text(ln):
                    out: list[str] = [ln]
                    taken = 0
                    j = idx + 1
                    while j < len(lines) and taken < max_lines:
                        if not (lines[j] or "").strip():
                            break
                        out.append(lines[j])
                        taken += 1
                        j += 1
                    return "\n".join(out)
            return ""

        role_candidates: List[Dict[str, object]] = []
        role_texts = [
            _extract_role_block(combined_text, "Beförderer (Name, Anschrift)"),
            _extract_role_block(combined_text, "Befoerderer (Name, Anschrift)"),
            _extract_role_block(combined_text, "Beförderer"),
            _extract_role_block(combined_text, "Befoerderer"),
            _extract_role_block(combined_text, "Abfallentsorger (Name, Anschrift)"),
            _extract_role_block(combined_text, "Abfallentsorger"),
        ]
        role_joined = "\n".join([t for t in role_texts if t])
        role_norm = _normalize_supplier_text(role_joined)
        if re.search(r"\bksr\b", role_norm, flags=re.IGNORECASE) or re.search(
            r"ks[-\s]?logistic|ks[-\s]?recycling", role_norm, flags=re.IGNORECASE
        ):
            role_candidates.append(
                {
                    "canonical": "KSR",
                    "confidence": 0.99,
                    "source": "role_block",
                    "matched": "Beförderer/Abfallentsorger",
                    "segment": "role",
                }
            )

        if role_candidates:
            best_role = sorted(role_candidates, key=lambda x: float(x.get("confidence") or 0.0), reverse=True)[0]
            current = (supplier_canonical or "").strip()
            # Override nur wenn sinnvoll: falscher Kunde erkannt oder niedrigere Confidence
            if current.lower() in ("franz bracht", "unbekannt") or float(supplier_confidence or 0.0) < 0.90:
                supplier_canonical = str(best_role.get("canonical") or supplier_canonical)
                supplier_source = str(best_role.get("source") or supplier_source)
                supplier_confidence = max(float(best_role.get("confidence") or 0.0), float(supplier_confidence or 0.0))
                supplier_candidates = [best_role] + [c for c in (supplier_candidates or []) if c != best_role]

        # 1) Franz Bracht aus Recipient-Kontext verwerfen
        if supplier_candidates:
            current = (supplier_canonical or "").strip()
            if current.lower() == "franz bracht":
                fb = [c for c in supplier_candidates if str(c.get("canonical") or "").lower() == "franz bracht"]
                if fb and all(str(c.get("segment") or "") == "recipient" for c in fb):
                    alt = next(
                        (
                            c
                            for c in supplier_candidates
                            if str(c.get("segment") or "") != "recipient" and str(c.get("canonical") or "")
                        ),
                        None,
                    )
                    if alt:
                        supplier_canonical = str(alt.get("canonical"))
                        supplier_source = str(alt.get("source") or supplier_source)
                        supplier_confidence = float(alt.get("confidence") or supplier_confidence)
                    else:
                        supplier_canonical = "Unbekannt"
                        supplier_source = "recipient_blocked"
                        supplier_confidence = 0.0

        # 1b) Franz Bracht als Kunde/Warenempfänger erkennen und als Supplier verwerfen
        # Hintergrund: Viele Belege enthalten "Kunde: Franz Bracht" (Empfänger), der eigentliche Lieferant ist jemand anders.
        if supplier_candidates:
            current = (supplier_canonical or "").strip()
            if current.lower() == "franz bracht":
                norm = _normalize_supplier_text(combined_text)
                customer_markers = [
                    "kunde",
                    "warenempfaenger",
                    "empfaenger",
                    "lieferadresse",
                    "rechnungsadresse",
                    "rechnungsempfaenger",
                    "ship to",
                    "sold to",
                    "bill to",
                ]
                is_customer_context = any(
                    re.search(rf"\b{re.escape(m)}\b.*\bfranz\b.*\bbracht\b", norm)
                    for m in customer_markers
                )
                if is_customer_context:
                    # Bevorzuge KSR falls vorhanden (typisch bei Entsorgung/Abfall-Belegen)
                    ksr = next(
                        (
                            c
                            for c in supplier_candidates
                            if str(c.get("canonical") or "").strip().upper() == "KSR"
                        ),
                        None,
                    )
                    if ksr:
                        supplier_canonical = "KSR"
                        supplier_source = str(ksr.get("source") or "customer_blocked")
                        supplier_confidence = max(supplier_confidence or 0.0, float(ksr.get("confidence") or 0.0))
                    else:
                        # Sonst: bestes alternatives Matching, aber nicht aus recipient wenn möglich
                        alts = [
                            c
                            for c in supplier_candidates
                            if str(c.get("canonical") or "").strip() and str(c.get("canonical") or "").lower() != "franz bracht"
                        ]
                        alts.sort(key=lambda x: float(x.get("confidence") or 0.0), reverse=True)
                        alt = next((c for c in alts if str(c.get("segment") or "") != "recipient"), None) or (alts[0] if alts else None)
                        if alt:
                            supplier_canonical = str(alt.get("canonical"))
                            supplier_source = str(alt.get("source") or "customer_blocked")
                            supplier_confidence = float(alt.get("confidence") or supplier_confidence)
                        else:
                            supplier_canonical = "Unbekannt"
                            supplier_source = "customer_blocked"
                            supplier_confidence = 0.0

        # 2) ÜBERNAHMESCHEIN: KSR boost (Fallback wenn role_block nichts ergab)
        if doc_type == "ÜBERNAHMESCHEIN":
            seg = segment_text(combined_text, header_max_lines=40, recipient_max_lines=20)
            hb_norm = _normalize_supplier_text("\n".join(seg.header_lines + seg.body_lines))
            if re.search(r"\bksr\b", hb_norm, flags=re.IGNORECASE):
                supplier_canonical = "KSR"
                supplier_confidence = max(supplier_confidence, 0.90)
                supplier_source = "doctype_boost"

            # WM deaktivieren, wenn WM nur im recipient vorkommt
            if supplier_canonical in ("WM", "WM SE"):
                rec_norm = _normalize_supplier_text("\n".join(seg.recipient_lines))
                if ("wm" in rec_norm) and ("wm" not in hb_norm):
                    supplier_canonical = "Unbekannt"
                    supplier_confidence = 0.0
                    supplier_source = "wm_recipient_blocked"
    except Exception:
        pass
    
    result["doc_type"] = doc_type
    result["doc_type_confidence"] = f"{doc_type_confidence:.2f}"
    result["doc_type_evidence"] = doc_type_evidence
    result["doc_type_scores"] = doc_type_scores
    result["doc_type_evidence_by_type"] = doc_type_evidence_by_type

    # Update supplier fields after coupling
    result["supplier"] = supplier_canonical
    result["supplier_canonical"] = supplier_canonical
    result["supplier_confidence"] = f"{supplier_confidence:.2f}" if supplier_confidence else ""
    result["supplier_source"] = supplier_source
    # Kandidaten nach Coupling erneut kappen (damit role_block/override sichtbar bleibt)
    if supplier_candidates:
        result["supplier_candidates"] = list(supplier_candidates)[:3]
    
    # Dokumentnummer: Supplier-spezifische Extraktion mit DocType
    doc_number = None
    doc_number_source = None
    doc_number_confidence = "none"
    
    if extract_doc_number is not None:
        try:
            # Verwende supplier-spezifische Extraktion mit CANONICAL name + DocType
            doc_result = extract_doc_number(combined_text, supplier_canonical, doc_type)
            if doc_result.doc_number:
                doc_number = doc_result.doc_number
                doc_number_source = doc_result.source_field
                doc_number_confidence = doc_result.confidence
        except Exception as exc:
            _LOGGER.warning(f"doc_number extraction failed: {exc}")
    
    # Fallback: alte Methode
    if not doc_number:
        numbers = extract_document_numbers(combined_text)
        doc_number = numbers.get("delivery_note_no") or numbers.get("order_no")
        if doc_number:
            doc_number_confidence = numbers.get("confidence", "medium")
            doc_number_source = "legacy_extraction"
    
    # Wenn keine Nummer gefunden: ohneNr + Hash
    if not doc_number:
        if generate_fallback_identifier is not None:
            fallback_hash = generate_fallback_identifier(combined_text)
            doc_number = f"ohneNr_{fallback_hash}"
        else:
            doc_number = "ohneNr"
        doc_number_confidence = "none"
        doc_number_source = "fallback"
    
    # Speichere in result dict
    result["doc_number"] = doc_number
    result["doc_number_source"] = doc_number_source or ""
    result["doc_number_confidence"] = doc_number_confidence
    
    # Review-Status-Berechnung (Gate Check)
    if decide_review_status is not None and load_review_settings is not None:
        try:
            settings_path = config.DATA_DIR / "settings.json"
            review_settings = load_review_settings(settings_path)
            review_decision = decide_review_status(result, review_settings)
            result["review_status"] = review_decision.status
            result["review_reasons"] = review_decision.reasons
            _LOGGER.info(f"Review Status: {review_decision.status}, Reasons: {review_decision.reasons}")
        except Exception as exc:
            _LOGGER.warning(f"Review status check failed: {exc}")
            result["review_status"] = "NEW"
            result["review_reasons"] = []
    else:
        result["review_status"] = "NEW"
        result["review_reasons"] = []

    new_filename = build_new_filename(
        supplier_canonical,  # Nutze canonical name für Dateinamen
        date_obj,
        delivery_note_nr=doc_number,
        date_format=date_format,
    )
    target_path, move_error = _move_pdf_with_name(pdf_path, output_dir, new_filename)
    if not target_path:
        shorter_name = build_new_filename(
            supplier,
            date_obj,
            date_format=date_format,
            max_supplier_len=30,
            max_base_len=80,
        )
        target_path, move_error = _move_pdf_with_name(pdf_path, output_dir, shorter_name)
    if not target_path:
        supplier = "Unbekannt"
        result["supplier"] = supplier
        result["supplier_source"] = "none"
        shortest_name = build_new_filename(
            supplier,
            date_obj,
            date_format=date_format,
            max_supplier_len=20,
            max_base_len=60,
        )
        target_path, move_error = _move_pdf_with_name(pdf_path, output_dir, shortest_name)
    if not target_path:
        result["error"] = move_error
        return result

    result["out_name"] = target_path.name
    result["status"] = "ok"
    _debug_extract_log(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "doc_id": pdf_path.name,
            "chosen_rotation": str(rotation_value),
            "date_candidate": result.get("date", ""),
            "date_source_label": result.get("date_source", ""),
            "supplier_candidate": supplier,
            "supplier_normalized": normalize_text(supplier),
            "needs_review": "1"
            if (not date_obj or supplier in ("", "Unbekannt") or supplier_source in ("heuristic", "none"))
            else "0",
            "error": result.get("error", ""),
        }
    )
    return result


def _append_log(log_path: Path, row: Dict[str, str]) -> None:
    log_fields = [
        "timestamp",
        "original",
        "new",
        "supplier",
        "date",
        "date_source",
        "status",
        "error",
        "tesseract_path",
        "poppler_bin",
    ]
    with _LOG_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = log_path.exists()
        with log_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=log_fields,
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        _trim_run_log(log_path, log_fields)


def _trim_run_log(log_path: Path, log_fields: List[str]) -> None:
    if not log_path.exists():
        return
    cutoff = datetime.now() - timedelta(days=max(LOG_RETENTION_DAYS, 1))
    with log_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            if row is None:
                continue
            if None in row:
                row.pop(None, None)
            ts = (row or {}).get("timestamp") or ""
            try:
                ts_dt = datetime.fromisoformat(ts)
            except ValueError:
                rows.append({key: row.get(key, "") for key in log_fields})
                continue
            if ts_dt >= cutoff:
                rows.append({key: row.get(key, "") for key in log_fields})
    with log_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=log_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def process_folder(
    input_dir: Path,
    output_dir: Path,
    date_format: str = DEFAULT_DATE_FORMAT,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    if not input_dir.exists():
        return results

    log_path = BASE_DIR / "data" / "logs" / "run.csv"

    def _process_one(pdf_path: Path) -> Dict[str, str]:
        result = process_pdf(pdf_path, output_dir, date_format=date_format)
        result["original"] = pdf_path.name
        _append_log(
            log_path,
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "original": pdf_path.name,
                "new": result.get("out_name", ""),
                "supplier": result.get("supplier", ""),
                "date": result.get("date", ""),
                "date_source": result.get("date_source", ""),
                "status": result.get("status", ""),
                "error": result.get("error", ""),
                "tesseract_path": result.get("tesseract_path", ""),
                "poppler_bin": result.get("poppler_bin", ""),
            },
        )
        return result

    pdf_files = sorted(
        p
        for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf"
    )
    total = len(pdf_files)
    # Reduziere Parallelität auf 1 Worker für stabilere Performance
    max_workers = 1

    done = 0

    timeout_seconds = int(os.getenv("DOCARO_FOLDER_TIMEOUT", "1800"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="docaro-pdf") as executor:
        future_to_pdf = {executor.submit(_process_one, p): p for p in pdf_files}
        try:
            for future in concurrent.futures.as_completed(future_to_pdf, timeout=timeout_seconds):
                pdf_path = future_to_pdf[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    _LOGGER.error(f"Error processing {pdf_path}: {exc}")
                    results.append(
                        {
                            "original": pdf_path.name,
                            "out_name": pdf_path.name,
                            "supplier": "",
                            "date": "",
                            "status": "error",
                            "error": f"processing_failed: {exc}",
                            "parsing_failed": True,
                        }
                    )
                finally:
                    done += 1
                    if progress_callback is not None:
                        try:
                            progress_callback(done, total, pdf_path.name)
                        except Exception:
                            pass
        except concurrent.futures.TimeoutError:
            # Mark remaining PDFs as failed so the job completes and the UI shows all entries.
            pending = [p for f, p in future_to_pdf.items() if not f.done()]
            for pdf_path in pending:
                results.append(
                    {
                        "original": pdf_path.name,
                        "out_name": pdf_path.name,
                        "supplier": "",
                        "date": "",
                        "status": "error",
                        "error": f"folder_timeout>{timeout_seconds}s",
                        "parsing_failed": True,
                    }
                )
                done += 1
                if progress_callback is not None:
                    try:
                        progress_callback(done, total, pdf_path.name)
                    except Exception:
                        pass

    return results


def _print_date_candidates(paths: List[str]) -> None:
    for raw in paths:
        pdf_path = Path(raw)
        if not pdf_path.exists():
            print(f"{raw} -> not found")
            continue
        images, _ = _render_pdf_images(pdf_path, _POPPLER_BIN, pages=OCR_PAGES)
        pick = extract_best_date(pdf_path, images=images, pages=OCR_PAGES)
        date_obj = pick.get("date")
        date_iso = date_obj.strftime(INTERNAL_DATE_FORMAT) if date_obj else "-"
        print(
            f"{pdf_path.name} -> {date_iso} | {pick.get('source')} | "
            f"{pick.get('confidence', 0.0):.2f} | {pick.get('evidence', '')}"
        )


if __name__ == "__main__":
    # Example: python -m core.extractor "PV_04.11.2025.pdf" "WM_*.pdf"
    import sys

    if len(sys.argv) > 1:
        _print_date_candidates(sys.argv[1:])
