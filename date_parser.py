import re
import logging
from datetime import datetime
from typing import Optional, Tuple

from config import Config
from constants import DATE_REGEX_PATTERNS

config = Config()

# Setup Logger
logger = logging.getLogger(__name__)
DEBUG_MODE = config.DEBUG

if DEBUG_MODE:
    logger.setLevel(logging.DEBUG)


def normalize_date(date_str: str, fmt: str) -> Optional[str]:
    """Versucht, ein Datum zu parsen und als ISO YYYY-MM-DD zurückzugeben."""
    try:
        dt = datetime.strptime(date_str, fmt)
        # Plausibilitäts-Check: Jahr muss zwischen 1990 und 2100 liegen
        if 1990 <= dt.year <= 2100:
            return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    return None


def fix_two_digit_year(day: str, month: str, year: str) -> str:
    """Wandelt 2-stellige Jahre in 4-stellige um (Threshold 70)."""
    if len(year) == 2:
        y = int(year)
        prefix = "19" if y >= 70 else "20"
        year = prefix + year
    return f"{day}.{month}.{year}"


MONTH_MAP = {
    "jan": "01",
    "januar": "01",
    "feb": "02",
    "februar": "02",
    "mar": "03",
    "maer": "03",
    "maerz": "03",
    "märz": "03",
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
    "okt": "10",
    "oktober": "10",
    "nov": "11",
    "november": "11",
    "dez": "12",
    "dezember": "12",
}

VEHICLE_DATE_CONTEXT = (
    "ez",
    "erstzulassung",
    "erstzulassungsdatum",
    "zulassung",
)

FUTURE_DUE_DATE_CONTEXT = (
    "nächste hu",
    "naechste hu",
    "fällig",
    "faellig",
)


def _is_excluded_date_context(line: str) -> bool:
    """True für Fahrzeug-/Fristdaten, die nicht das Dokumentdatum sind."""
    lower = (line or "").lower()
    if re.search(r"\bez\b", lower):
        return True
    if any(keyword in lower for keyword in VEHICLE_DATE_CONTEXT[1:]):
        return True
    if any(keyword in lower for keyword in FUTURE_DUE_DATE_CONTEXT):
        return True
    return False


def _score_context_line(line: str, *, month_name: bool = False) -> int:
    lower = (line or "").lower()
    score = 60 if month_name else 10
    if "datum" in lower:
        score += 50 if not month_name else 40
    if "liefer" in lower:
        score += 30 if not month_name else 20
    if "rechnung" in lower:
        score += 20
    if re.search(r"\bvom\b", lower):
        score += 35
    if "bericht" in lower or "prüfbericht" in lower or "pruefbericht" in lower:
        score += 15
    return score


def _parse_dmy_to_iso(raw: str) -> Optional[str]:
    match = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b", raw or "")
    if not match:
        return None
    d, m, y = match.group(1), match.group(2), match.group(3)
    return normalize_date(fix_two_digit_year(d, m, y), "%d.%m.%Y")


def _looks_like_dekra_report(text: str) -> bool:
    lower = (text or "").lower()
    markers = (
        "dekra",
        "prüfbericht",
        "pruefbericht",
        "untersuchungsbericht",
        "hauptuntersuchung",
        "hu-prüfung",
        "hu-pruefung",
        "berichts-nr",
        "berichtsnr",
    )
    return any(marker in lower for marker in markers)


def _extract_dekra_report_date(text: str) -> Tuple[Optional[str], str]:
    """Bevorzugt das Prüfbericht-Datum, nicht Fahrzeugdaten wie EZ/Erstzulassung."""
    if not _looks_like_dekra_report(text):
        return None, "not_dekra_report"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates = []
    report_markers = (
        "berichts-nr",
        "berichtsnr",
        "untersuchungsbericht",
        "prüfbericht",
        "pruefbericht",
        "hauptuntersuchung",
        "hu-prüfung",
        "hu-pruefung",
    )

    for idx, line in enumerate(lines):
        lower = line.lower()
        if _is_excluded_date_context(lower):
            continue

        has_report_marker = any(marker in lower for marker in report_markers)
        has_vom = re.search(r"\bvom\b", lower) is not None
        if not (has_report_marker or has_vom):
            continue

        window = [line]
        if has_report_marker:
            window.extend(lines[idx + 1 : idx + 3])

        for offset, candidate_line in enumerate(window):
            candidate_lower = candidate_line.lower()
            if _is_excluded_date_context(candidate_lower):
                continue
            iso = _parse_dmy_to_iso(candidate_line)
            if not iso:
                continue
            score = 100
            if re.search(r"\bvom\b", candidate_lower):
                score += 50
            if has_report_marker:
                score += 40
            # Aktuelle/nahe Folgezeilen sind stärker als weit entfernte Treffer.
            score -= offset * 5
            candidates.append((score, idx + offset, iso))

    if not candidates:
        return None, "dekra_report_no_date"

    _, _, best_iso = sorted(candidates, key=lambda item: (-item[0], item[1]))[0]
    return best_iso, "dekra_report_date"


def extract_date_from_text(text: str) -> Tuple[Optional[str], str]:
    """
    Extrahiert das wahrscheinlichste Datum aus dem Text.
    Returns: (date_iso, confidence_reason)
    """
    if not text:
        if DEBUG_MODE:
            logger.debug("Textlayer ist leer.")
        return None, "empty_text"

    if DEBUG_MODE:
        logger.debug(f"Analysiere Text (Länge: {len(text)})...")

    dekra_iso, dekra_reason = _extract_dekra_report_date(text)
    if dekra_iso:
        return dekra_iso, dekra_reason

    candidates = []

    # Regex-Patterns aus constants.py verwenden
    regex_de_dot = DATE_REGEX_PATTERNS["dmy_dot"]
    regex_de_slash = DATE_REGEX_PATTERNS["dmy_slash"]
    regex_iso = DATE_REGEX_PATTERNS["iso"]
    regex_month_name = DATE_REGEX_PATTERNS["month_name"]

    # Suche Deutsche Formate (Punkt und Slash)
    for regex in [regex_de_dot, regex_de_slash]:
        for match in regex.finditer(text):
            raw = match.group(0)
            d, m, y = match.group(1), match.group(2), match.group(3)

            # Normalisiere 2-stellige Jahre
            date_str = fix_two_digit_year(d, m, y)
            iso = normalize_date(date_str, "%d.%m.%Y")

            if iso:
                # Score berechnen: Keywords auf der gleichen Zeile
                start_pos = match.start()
                line_start = text.rfind("\n", 0, start_pos) + 1
                line_end = text.find("\n", start_pos)
                if line_end == -1:
                    line_end = len(text)
                line = text[line_start:line_end].lower()
                if _is_excluded_date_context(line):
                    continue

                score = _score_context_line(line)
                candidates.append({"iso": iso, "raw": raw, "pos": start_pos, "score": score, "type": "de"})

    # Suche ISO Formate
    for match in regex_iso.finditer(text):
        raw = match.group(0)
        y, m, d = match.group(1), match.group(2), match.group(3)
        iso = normalize_date(f"{y}-{m}-{d}", "%Y-%m-%d")

        if iso:
            start_pos = match.start()
            line_start = text.rfind("\n", 0, start_pos) + 1
            line_end = text.find("\n", start_pos)
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end].lower()
            if _is_excluded_date_context(line):
                continue

            score = _score_context_line(line)

            candidates.append({"iso": iso, "raw": raw, "pos": start_pos, "score": score, "type": "iso"})

    # Suche Formate mit Monatsnamen
    for match in regex_month_name.finditer(text):
        raw = match.group(0)
        day, month_str, year = match.groups()
        month_key = month_str.lower().replace(".", "")

        if month_key in MONTH_MAP:
            month = MONTH_MAP[month_key]
            iso = normalize_date(f"{day}.{month}.{year}", "%d.%m.%Y")
            if iso:
                start_pos = match.start()
                line_start = text.rfind("\n", 0, start_pos) + 1
                line_end = text.find("\n", start_pos)
                if line_end == -1:
                    line_end = len(text)
                line = text[line_start:line_end].lower()
                if _is_excluded_date_context(line):
                    continue

                score = _score_context_line(line, month_name=True)

                candidates.append({"iso": iso, "raw": raw, "pos": start_pos, "score": score, "type": "month_name"})

    # B) Instrumentierung: Logge Kandidaten
    if DEBUG_MODE:
        logger.debug(f"Gefundene Kandidaten: {len(candidates)}")
        for i, c in enumerate(sorted(candidates, key=lambda x: x["score"], reverse=True)[:5]):
            logger.debug(f"  [{i}] {c['iso']} (Score: {c['score']}, Raw: '{c['raw']}')")

    if not candidates:
        return None, "no_candidates_found"

    # Auswahl des besten Kandidaten (höchster Score, dann Position im Dokument)
    # Sortierung: Score absteigend, dann Position aufsteigend (früher im Dokument ist oft besser bei gleichem Score)
    best = sorted(candidates, key=lambda x: (-x["score"], x["pos"]))[0]

    reason = f"score_{best['score']}_type_{best['type']}"

    if DEBUG_MODE:
        logger.debug(f"FINAL DECISION: {best['iso']} ({reason})")

    return best["iso"], reason
