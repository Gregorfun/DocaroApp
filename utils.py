"""
Gemeinsame Hilfsfunktionen für Docaro.
"""

import re
import shlex
from pathlib import Path
from typing import Optional


def normalize_text(value: str) -> str:
    """Normalisiert Text: Entfernt Zeilenumbrüche, Tabs und extra Leerzeichen."""
    if not value:
        return ""
    # Ersetze Zeilenumbrüche und Tabs durch Leerzeichen
    normalized = re.sub(r"[\n\r\t]", " ", value)
    # Entferne extra Leerzeichen
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def first_path_from_env(value: str) -> Optional[Path]:
    """Extrahiert den ersten Pfad aus einer Umgebungsvariable."""
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


def has_pdfinfo(bin_dir: Path) -> bool:
    """Prüft, ob pdfinfo in einem Verzeichnis vorhanden ist."""
    if not bin_dir or not bin_dir.exists():
        return False
    return (bin_dir / "pdfinfo.exe").exists() or (bin_dir / "pdfinfo").exists()