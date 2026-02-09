from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Monatnamen auf Deutsch
_MONTHS_DE = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]

_FORBIDDEN_CHARS = re.compile(r"[\\/:*?\"<>|]")
_SPACE_CLEANUP = re.compile(r"\s+")


@dataclass
class AutoSortSettings:
    enabled: bool = False
    base_dir: Path = Path()
    folder_format: str = "A"
    mode: str = "move"  # move | copy
    confidence_threshold: float = 0.80
    fallback_folder: str = "_Unsortiert (Prüfen)"

    # Inbox / Eingang verarbeiten
    inbox_dir: Path = Path()
    inbox_interval_minutes: int = 0

    def normalized_format(self) -> str:
        fmt = (self.folder_format or "A").upper()
        return fmt if fmt in ("A", "B", "C") else "A"

    def normalized_mode(self) -> str:
        mode = (self.mode or "move").lower()
        return mode if mode in ("move", "copy") else "move"


class AutoSortResult:
    def __init__(
        self,
        path: Optional[Path],
        status: str,
        reason: str = "",
        reason_code: str = "",
        details: Optional[dict] = None,
    ) -> None:
        self.path = path
        self.status = status  # sorted | fallback | skipped | failed
        self.reason = reason
        self.reason_code = reason_code
        self.details = details or {}

    def as_tuple(self) -> Tuple[Optional[Path], str, str]:
        return self.path, self.status, self.reason


def load_settings(path: Path, defaults: AutoSortSettings) -> AutoSortSettings:
    if not path.exists():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    base_dir_raw = str(raw.get("base_dir", str(defaults.base_dir)) or "").strip()
    base_dir = Path(base_dir_raw).expanduser() if base_dir_raw else defaults.base_dir

    inbox_dir_raw = str(raw.get("inbox_dir", str(defaults.inbox_dir)) or "").strip()
    inbox_dir = Path(inbox_dir_raw).expanduser() if inbox_dir_raw else defaults.inbox_dir

    inbox_interval_raw = raw.get("inbox_interval_minutes", defaults.inbox_interval_minutes)
    try:
        inbox_interval_minutes = int(str(inbox_interval_raw).strip() or "0")
    except (TypeError, ValueError):
        inbox_interval_minutes = int(defaults.inbox_interval_minutes or 0)
    if inbox_interval_minutes < 0:
        inbox_interval_minutes = 0

    return AutoSortSettings(
        enabled=bool(raw.get("enabled", defaults.enabled)),
        base_dir=base_dir,
        folder_format=str(raw.get("folder_format", defaults.folder_format)),
        mode=str(raw.get("mode", defaults.mode)),
        confidence_threshold=float(raw.get("confidence_threshold", defaults.confidence_threshold)),
        fallback_folder=str(raw.get("fallback_folder", defaults.fallback_folder)),
        inbox_dir=inbox_dir,
        inbox_interval_minutes=inbox_interval_minutes,
    )


def save_settings(path: Path, settings: AutoSortSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    payload["base_dir"] = str(settings.base_dir)
    payload["inbox_dir"] = str(settings.inbox_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def sanitize_supplier_name(name: str) -> str:
    if not name:
        return "Unbekannt"
    cleaned = _FORBIDDEN_CHARS.sub(" ", name)
    cleaned = _SPACE_CLEANUP.sub(" ", cleaned).strip()
    cleaned = cleaned.strip(". ")
    if not cleaned:
        return "Unbekannt"
    # Windows verbotene Endungen vermeiden
    cleaned = cleaned.rstrip(".")
    return cleaned or "Unbekannt"


def _sanitize_component(value: str) -> str:
    if not value:
        return ""
    cleaned = _FORBIDDEN_CHARS.sub("_", value)
    cleaned = _SPACE_CLEANUP.sub(" ", cleaned).strip()
    cleaned = re.sub(r"[^\w .-]", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._ ")
    return cleaned


def _truncate_component(value: str, max_len: int) -> str:
    if not value:
        return ""
    value = value.strip()
    if len(value) <= max_len:
        return value
    return value[:max_len].rstrip(" ._-_")


def _parse_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if not raw:
        return 0.0
    raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _parse_date(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d-%m-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _is_default_doc_type(doc_type: str) -> bool:
    dt = (doc_type or "").strip().lower()
    return dt in ("", "dokument", "document", "unknown", "unklar", "n/a", "na")


@dataclass
class AutoSortDecision:
    should_sort: bool
    reason_code: str
    details: dict
    target_dir: Optional[Path] = None


def decide_auto_sort(result: dict, settings: AutoSortSettings) -> AutoSortDecision:
    details: dict = {
        "enabled": bool(settings.enabled),
        "threshold": float(settings.confidence_threshold or 0),
    }

    if not settings.enabled:
        return AutoSortDecision(False, "AUTOSORT_DISABLED", details, target_dir=None)

    if not settings.base_dir or str(settings.base_dir).strip() == "":
        return AutoSortDecision(False, "BASEDIR_NOT_SET", details, target_dir=None)

    supplier = (result.get("supplier") or "").strip()
    details["supplier"] = supplier
    if not supplier or supplier == "Unbekannt":
        return AutoSortDecision(False, "MISSING_SUPPLIER", details, target_dir=settings.base_dir / sanitize_supplier_name(settings.fallback_folder))

    conf = _parse_float(result.get("supplier_confidence"))
    details["supplier_confidence"] = conf
    if conf < float(settings.confidence_threshold or 0):
        return AutoSortDecision(False, "SUPPLIER_CONF_LOW", details, target_dir=settings.base_dir / sanitize_supplier_name(settings.fallback_folder))

    date_raw = result.get("date")
    details["date_raw"] = "" if date_raw is None else str(date_raw)
    date_obj = _parse_date(date_raw)
    if date_raw is None or str(date_raw).strip() == "":
        return AutoSortDecision(False, "MISSING_DATE", details, target_dir=settings.base_dir / sanitize_supplier_name(settings.fallback_folder))
    if not date_obj:
        return AutoSortDecision(False, "DATE_PARSE_FAIL", details, target_dir=settings.base_dir / sanitize_supplier_name(settings.fallback_folder))

    details["parsed_date"] = date_obj.strftime("%Y-%m-%d")
    doc_type = (result.get("document_type") or result.get("doctype") or "").strip()
    details["doc_type"] = doc_type
    if doc_type and doc_type.strip() and doc_type.lower() != "lieferschein" and not _is_default_doc_type(doc_type):
        return AutoSortDecision(False, "DOC_TYPE_BLOCKED", details, target_dir=settings.base_dir / sanitize_supplier_name(settings.fallback_folder))

    # OK -> Zielordner nach Supplier/YYYY-MM
    return AutoSortDecision(True, "OK", details, target_dir=build_target_folder(settings, supplier, date_obj))


def month_name_de(month: int) -> str:
    try:
        return _MONTHS_DE[month - 1]
    except Exception:
        return "Monat"


def build_target_folder(settings: AutoSortSettings, supplier: str, date_obj: datetime) -> Path:
    supplier_folder = sanitize_supplier_name(supplier)
    fmt = settings.normalized_format()
    year_month = date_obj.strftime("%Y-%m")
    if fmt == "B":
        month_label = month_name_de(date_obj.month)
        subfolder = f"{month_label} {date_obj.year}"
        return settings.base_dir / supplier_folder / subfolder
    if fmt == "C":
        subfolder = f"{year_month}_{sanitize_supplier_name(supplier)}"
        return settings.base_dir / supplier_folder / subfolder
    # Default (A)
    return settings.base_dir / supplier_folder / year_month


def ensure_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def make_unique_filename(target_dir: Path, filename: str) -> Path:
    target = target_dir / filename
    if not target.exists():
        return target
    # Nur bei echten Duplikaten Suffix hinzufügen
    stem = target.stem
    suffix = target.suffix or ".pdf"
    counter = 1
    while True:
        candidate = target_dir / f"{stem}_{counter:02d}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _open_unique_target(target_dir: Path, filename: str):
    """Öffnet ein eindeutiges Ziel exklusiv (race-safe) und liefert (Path, Handle)."""
    target_dir.mkdir(parents=True, exist_ok=True)
    base = target_dir / filename
    stem = base.stem
    suffix = base.suffix or ".pdf"

    counter = 0
    while True:
        candidate = base if counter == 0 else (target_dir / f"{stem}_{counter:02d}{suffix}")
        try:
            handle = candidate.open("xb")
            return candidate, handle
        except FileExistsError:
            counter += 1


def build_target_filename(supplier: str, date_obj: datetime, doc_type: str, original_name: str) -> str:
    supplier_clean = _sanitize_component(supplier) or "Unbekannt"
    date_part = date_obj.strftime("%Y-%m-%d")
    original_stem = Path(original_name or "").stem
    original_clean = _sanitize_component(original_stem) or "Original"

    supplier_clean = _truncate_component(supplier_clean, 60) or "Unbekannt"
    original_clean = _truncate_component(original_clean, 80) or "Original"

    parts = [supplier_clean, date_part]
    if not _is_default_doc_type(doc_type):
        doc_type_clean = _truncate_component(_sanitize_component(doc_type), 40)
        if doc_type_clean:
            parts.append(doc_type_clean)
    parts.append(original_clean)

    return "_".join(parts) + ".pdf"


def should_auto_sort(result: dict, settings: AutoSortSettings) -> Tuple[bool, str]:
    decision = decide_auto_sort(result, settings)
    if decision.should_sort:
        return True, ""
    # Legacy reason string for existing UI
    mapping = {
        "AUTOSORT_DISABLED": "disabled",
        "BASEDIR_NOT_SET": "basedir_not_set",
        "MISSING_SUPPLIER": "supplier_missing",
        "SUPPLIER_CONF_LOW": "supplier_confidence_low",
        "MISSING_DATE": "date_missing",
        "DATE_PARSE_FAIL": "date_invalid",
        "DOC_TYPE_BLOCKED": f"doctype_is_{(decision.details.get('doc_type') or '').lower()}",
    }
    return False, mapping.get(decision.reason_code, decision.reason_code)


def export_document(pdf_path: Path, result: dict, settings: AutoSortSettings) -> AutoSortResult:
    if not pdf_path or not pdf_path.exists():
        return AutoSortResult(pdf_path, "failed", "source_missing", reason_code="SOURCE_MISSING")

    decision = decide_auto_sort(result, settings)
    can_sort = decision.should_sort
    if not settings.enabled:
        # Feature deaktiviert: nichts verschieben/kopieren, aber Reason liefern.
        return AutoSortResult(pdf_path, "skipped", "Nicht sortiert: AUTOSORT_DISABLED", reason_code="AUTOSORT_DISABLED", details=decision.details)

    if decision.reason_code == "BASEDIR_NOT_SET":
        return AutoSortResult(pdf_path, "failed", "Nicht sortiert: BASEDIR_NOT_SET", reason_code="BASEDIR_NOT_SET", details=decision.details)

    target_dir = decision.target_dir
    if not target_dir:
        # Fallback als letzte Absicherung
        target_dir = settings.base_dir / sanitize_supplier_name(settings.fallback_folder or "_Unsortiert (Prüfen)")

    status = "sorted" if decision.should_sort else "fallback"
    reason_code = "OK" if decision.should_sort else decision.reason_code
    mode = settings.normalized_mode()
    filename = pdf_path.name

    if decision.should_sort:
        logger.info("AUTOSORT OK -> %s", str(target_dir))
    else:
        logger.info("AUTOSORT FAIL %s -> %s", decision.reason_code, str(target_dir))

    try:
        target_path, handle = _open_unique_target(target_dir, filename)
        try:
            with pdf_path.open("rb") as src:
                shutil.copyfileobj(src, handle)
        finally:
            handle.close()

        try:
            shutil.copystat(pdf_path, target_path)
        except OSError:
            pass

        if mode == "move":
            try:
                pdf_path.unlink(missing_ok=True)
            except TypeError:  # pragma: no cover (py<3.8)
                if pdf_path.exists():
                    pdf_path.unlink()

        if decision.should_sort:
            reason_msg = f"Ablage: {target_path}"
        else:
            reason_msg = f"Nicht sortiert: {decision.reason_code}"
        return AutoSortResult(target_path, status, reason_msg, reason_code=reason_code, details=decision.details)
    except FileNotFoundError:
        return AutoSortResult(None, "failed", "source_missing", reason_code="SOURCE_MISSING", details=decision.details)
    except OSError as exc:
        return AutoSortResult(None, "failed", f"io_error:{exc}", reason_code="IO_ERROR", details={**decision.details, "error": str(exc)})

