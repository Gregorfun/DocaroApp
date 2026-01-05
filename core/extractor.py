from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import shlex
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pdf2image import convert_from_path
from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError, PDFSyntaxError
import pytesseract

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATE_FORMAT = "%Y-%m-%d"
INTERNAL_DATE_FORMAT = "%Y-%m-%d"
SUPPLIERS_DB_PATH = BASE_DIR / "data" / "suppliers.json"
OCR_TIMEOUT_SECONDS = int(os.getenv("DOCARO_OCR_TIMEOUT", "20"))
PDF_CONVERT_TIMEOUT = int(os.getenv("DOCARO_PDF_CONVERT_TIMEOUT", "40"))
ROTATION_OCR_TIMEOUT = int(os.getenv("DOCARO_ROTATION_OCR_TIMEOUT", "8"))
DATE_CROP_OCR_TIMEOUT = int(os.getenv("DOCARO_DATE_CROP_OCR_TIMEOUT", "10"))
OCR_PAGES = max(1, min(int(os.getenv("DOCARO_OCR_PAGES", "2")), 5))
LOG_RETENTION_DAYS = int(os.getenv("DOCARO_LOG_RETENTION_DAYS", "90"))
DEBUG_EXTRACT = os.getenv("DOCARO_DEBUG_EXTRACT") == "1"
DEBUG_LOG_PATH = BASE_DIR / "data" / "logs" / "extract_debug.log"


def _has_pdfinfo(bin_dir: Path) -> bool:
    if not bin_dir or not bin_dir.exists():
        return False
    return (bin_dir / "pdfinfo.exe").exists() or (bin_dir / "pdfinfo").exists()


def _first_path_from_env(value: str) -> Optional[Path]:
    if not value:
        return None
    cleaned = value.strip().strip('"').strip("'")
    if not cleaned:
        return None
    try:
        parts = shlex.split(cleaned, posix=False)
    except ValueError:
        parts = [cleaned]
    if not parts:
        return None
    return Path(parts[0])


def _resolve_tesseract_cmd() -> Tuple[Optional[Path], bool]:
    for env_key in ("DOCARO_TESSERACT_CMD", "TESSERACT_CMD", "DOCARO_TESSERACT"):
        env_path = os.getenv(env_key)
        if env_path:
            candidate = _first_path_from_env(env_path)
            if candidate and candidate.exists():
                return candidate, True
            if candidate and candidate.is_dir():
                exe_candidate = candidate / "tesseract.exe"
                if exe_candidate.exists():
                    return exe_candidate, True
    fallback_paths = [
        BASE_DIR / "Tesseract OCR Windows installer" / "tesseract.exe",
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    for candidate in fallback_paths:
        if candidate.exists():
            return candidate, True
    which_path = shutil.which("tesseract")
    if which_path:
        return Path(which_path), True
    return None, False


def _resolve_poppler_bin() -> Tuple[Optional[Path], bool]:
    env_path = os.getenv("DOCARO_POPPLER_BIN")
    if env_path:
        candidate = _first_path_from_env(env_path)
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

CANONICAL_SUPPLIERS = {
    "vergoelst": "Vergoelst",
    "vergolst": "Vergoelst",
    "verglst": "Vergoelst",
}

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

MONTH_NAME_REGEX = re.compile(r"\b(\d{1,2})[.\s]+([A-Za-z]+)[.\s]+(\d{4})\b", flags=re.IGNORECASE)
DMY_MONTH_DASH_REGEX = re.compile(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", flags=re.IGNORECASE)
ISO_REGEX = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
YMD_SLASH_REGEX = re.compile(r"\b(\d{4})/(\d{2})/(\d{2})\b")
DMY_DOT_REGEX = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
DMY_DASH_REGEX = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b")
DMY_SLASH_REGEX = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
DMY_DOT_SHORT_REGEX = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b")
DMY_DASH_SHORT_REGEX = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{2})\b")
DMY_SLASH_SHORT_REGEX = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b")
VERGOELST_REGEX = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b")
TADANO_REGEX = re.compile(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", flags=re.IGNORECASE)
DATE_REGEXES = [
    ISO_REGEX,
    YMD_SLASH_REGEX,
    DMY_DOT_REGEX,
    DMY_DASH_REGEX,
    DMY_SLASH_REGEX,
    DMY_DOT_SHORT_REGEX,
    DMY_DASH_SHORT_REGEX,
    DMY_SLASH_SHORT_REGEX,
    MONTH_NAME_REGEX,
    DMY_MONTH_DASH_REGEX,
]


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
    alnum_count = sum(1 for ch in text if ch.isalnum())
    return alnum_count + _count_keywords(text)


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
        except Exception:
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
            except Exception:
                continue
            score = max(score, _rotation_score(text))
        candidates.append((rotation, score))
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates


def _detect_osd_rotation(image) -> Optional[int]:
    if not _has_osd_traineddata():
        return None
    try:
        osd = pytesseract.image_to_osd(image, timeout=min(ROTATION_OCR_TIMEOUT, OCR_TIMEOUT_SECONDS))
    except Exception:
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
        except Exception as exc:
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
    if osd_rotation is not None:
        if osd_rotation == 0:
            return {
                "text": text,
                "error": "",
                "rotation": "0",
                "rotation_reason": "osd",
                "score": str(base_score),
            }
        try:
            rotated_text = _ocr_image(image, rotation=osd_rotation)
        except Exception as exc:
            return {"text": "", "error": f"ocr_failed: {exc}"}
        score = _score_text(rotated_text)
        return {
            "text": rotated_text,
            "error": "",
            "rotation": str(osd_rotation),
            "rotation_reason": "osd",
            "score": str(score),
        }

    best_rotation = 0
    best_text = text
    best_score = base_score
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


def ocr_first_page(
    pdf_path: Path,
    poppler_bin: Optional[Path],
    pages: int = 1,
    force_best: bool = False,
) -> Dict[str, str]:
    pages = max(1, min(pages, 5))
    try:
        try:
            images = convert_from_path(
                str(pdf_path),
                dpi=300,
                first_page=1,
                last_page=pages,
                poppler_path=str(poppler_bin) if poppler_bin else None,
                timeout=PDF_CONVERT_TIMEOUT,
            )
        except TypeError:
            images = convert_from_path(
                str(pdf_path),
                dpi=300,
                first_page=1,
                last_page=pages,
                poppler_path=str(poppler_bin) if poppler_bin else None,
            )
    except PDFInfoNotInstalledError:
        return {"text": "", "error": "Poppler/pdfinfo nicht gefunden - installiere Poppler oder setze DOCARO_POPPLER_BIN"}
    except (PDFPageCountError, PDFSyntaxError) as exc:
        return {"text": "", "error": f"pdf_read_failed: {exc}"}
    except Exception as exc:
        return {"text": "", "error": f"pdf_convert_failed: {exc}"}

    if not images:
        return {"text": "", "error": "Keine Seiten im PDF gefunden."}

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
        if images:
            result["image"] = images[0]
        return result

    if best_image is not None:
        best_result["image"] = best_image
    return best_result


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
    if 0 <= year_short <= 69:
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


def normalize_text(value: str) -> str:
    lowered = value.lower()
    lowered = lowered.replace("\u00df", "ss").replace("\u00e4", "ae").replace("\u00f6", "oe").replace("\u00fc", "ue")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _canonicalize_supplier(name: str) -> str:
    normalized = normalize_text(name)
    return CANONICAL_SUPPLIERS.get(normalized, name)


def _detect_supplier_from_db(text: str) -> Optional[Tuple[str, str]]:
    data = load_suppliers_db()
    normalized_text = normalize_text(text)
    entries = list(data.get("suppliers", []))
    entries.append({"name": "Vergoelst", "aliases": VERGOELST_ALIASES})
    for entry in entries:
        name = str(entry.get("name", "")).strip()
        aliases = entry.get("aliases", [])
        candidates = [name] + [str(alias) for alias in aliases if alias]
        for alias in candidates:
            normalized_alias = normalize_text(alias)
            if normalized_alias and normalized_alias in normalized_text:
                return name or alias, alias
    return None


def _heuristic_supplier(text: str) -> Tuple[Optional[str], Optional[str], float]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    top_lines = lines[:40]
    blocked_terms = [
        "datum der uebergabe",
        "uebergabe",
        "kommissionierliste",
        "lieferadresse",
        "rechnungsadresse",
        "lieferanschrift",
        "lieferschein",
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
        normalized_line = normalize_text(line)
        if not normalized_line or any(term in normalized_line for term in blocked_terms):
            continue
        score = 0.0
        if any(marker in normalized_line for marker in endings):
            score += 0.9
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
    normalized_text = normalize_text(text)
    normalized_head = normalized_text[: max(1, int(len(normalized_text) * 0.25))] if normalized_text else ""
    db_hit = _detect_supplier_from_db(text)
    if db_hit:
        supplier_name, alias = db_hit
        supplier_name = _canonicalize_supplier(supplier_name)
        normalized_alias = normalize_text(alias)
        confidence = 0.90
        if normalized_alias and normalized_alias in normalized_head:
            confidence = min(confidence + 0.1, 1.0)
        return supplier_name, confidence, "db", alias

    keyword_candidates = list(SUPPLIER_KEYWORDS.items())
    keyword_candidates.extend((alias, "Vergoelst") for alias in VERGOELST_ALIASES)
    for keyword, shortname in keyword_candidates:
        normalized_keyword = normalize_text(keyword)
        if not normalized_keyword:
            continue
        if normalized_keyword in normalized_text:
            shortname = _canonicalize_supplier(shortname)
            confidence = 0.95
            if normalized_keyword in normalized_head:
                confidence = min(confidence + 0.1, 1.0)
            return shortname, confidence, "keywords", keyword

    guess, guess_line, confidence = _heuristic_supplier(text)
    if guess:
        guess = _canonicalize_supplier(guess)
        return guess, confidence, "heuristic", guess_line or ""

    return "Unbekannt", 0.0, "none", ""


def _ocr_date_crop(image, crop_box: Tuple[int, int, int, int]) -> str:
    crop = image.crop(crop_box)
    config = "--psm 7 -c tessedit_char_whitelist=0123456789./-"
    try:
        return _ocr_image(crop, rotation=0, config=config, timeout=min(DATE_CROP_OCR_TIMEOUT, OCR_TIMEOUT_SECONDS))
    except Exception:
        config = "--psm 6 -c tessedit_char_whitelist=0123456789./-"
        return _ocr_image(crop, rotation=0, config=config, timeout=min(DATE_CROP_OCR_TIMEOUT, OCR_TIMEOUT_SECONDS))


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
        except Exception:
            continue
        dt = extract_date(crop_text)
        if dt:
            return dt
    return None


def _debug_extract_log(payload: Dict[str, str]) -> None:
    if not DEBUG_EXTRACT:
        return
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
    base_name = sanitize_filename(f"{safe_supplier}_{date_part}")
    base_name = _truncate_with_hash(base_name, max_base_len)
    return f"{base_name}.pdf"


def get_unique_path(target_dir: Path, filename: str) -> Path:
    candidate = target_dir / filename
    counter = 1
    while candidate.exists():
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        candidate = target_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _move_pdf_with_name(pdf_path: Path, output_dir: Path, filename: str) -> Tuple[Optional[Path], str]:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        target_path = get_unique_path(output_dir, filename)
        pdf_path.replace(target_path)
        return target_path, ""
    except Exception as exc:
        return None, f"move_failed: {exc}"


def process_pdf(pdf_path: Path, output_dir: Path, date_format: str = DEFAULT_DATE_FORMAT) -> Dict[str, str]:
    result: Dict[str, str] = {
        "supplier": "",
        "supplier_confidence": "",
        "supplier_source": "",
        "supplier_guess_line": "",
        "supplier_gibberish": "",
        "date": "",
        "date_source": "",
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
        "parsing_failed": False,
    }

    ocr_result = ocr_first_page(pdf_path, _POPPLER_BIN, pages=OCR_PAGES, force_best=True)
    text = ""
    if ocr_result["error"]:
        result["error"] = ocr_result["error"]
        result["parsing_failed"] = True
    else:
        text = ocr_result["text"]
    result["ocr_rotation"] = ocr_result.get("rotation", "")
    result["ocr_rotation_reason"] = ocr_result.get("rotation_reason", "")
    result["rotate_hint"] = result["ocr_rotation"]
    try:
        rotation_value = int(result["ocr_rotation"] or 0)
    except ValueError:
        rotation_value = 0
    supplier, supplier_confidence, supplier_source, supplier_guess_line = detect_supplier(text)
    gibberish = False
    if supplier_source == "heuristic" and _is_ocr_gibberish(supplier_guess_line or supplier):
        supplier = "Unbekannt"
        supplier_confidence = 0.0
        supplier_source = "none"
        supplier_guess_line = ""
        gibberish = True
    date_obj, date_source = extract_date_with_priority(text)
    if not date_obj:
        date_obj = _extract_date_from_crops(ocr_result.get("image"), rotation_value, text)
        if date_obj:
            date_source = "crop"
    result["supplier"] = supplier
    result["supplier_confidence"] = f"{supplier_confidence:.2f}" if supplier_confidence else ""
    result["supplier_source"] = supplier_source
    result["supplier_guess_line"] = supplier_guess_line
    result["supplier_gibberish"] = "1" if gibberish else ""
    result["date"] = date_obj.strftime(INTERNAL_DATE_FORMAT) if date_obj else ""
    result["date_source"] = date_source if date_obj else ""

    new_filename = build_new_filename(supplier, date_obj, date_format=date_format)
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
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as handle:
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


def process_folder(input_dir: Path, output_dir: Path, date_format: str = DEFAULT_DATE_FORMAT) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    if not input_dir.exists():
        return results

    log_path = BASE_DIR / "data" / "logs" / "run.csv"

    for pdf_path in sorted(input_dir.glob("*.pdf")):
        result = process_pdf(pdf_path, output_dir, date_format=date_format)
        result["original"] = pdf_path.name
        results.append(result)
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

    return results









