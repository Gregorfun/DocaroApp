import re
import os
import logging
from datetime import datetime
from typing import Optional, Tuple, List

from config import Config

config = Config()
from constants import DATE_REGEX_PATTERNS

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
    "jan": "01", "januar": "01",
    "feb": "02", "februar": "02",
    "mar": "03", "maer": "03", "maerz": "03", "märz": "03",
    "apr": "04", "april": "04",
    "mai": "05", "may": "05",
    "jun": "06", "juni": "06",
    "jul": "07", "juli": "07",
    "aug": "08", "august": "08",
    "sep": "09", "sept": "09", "september": "09",
    "okt": "10", "oktober": "10",
    "nov": "11", "november": "11",
    "dez": "12", "dezember": "12",
}

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
                line_start = text.rfind('\n', 0, start_pos) + 1
                line_end = text.find('\n', start_pos)
                if line_end == -1:
                    line_end = len(text)
                line = text[line_start:line_end].lower()
                
                score = 10
                if "datum" in line: score += 50
                if "liefer" in line: score += 30
                if "rechnung" in line: score += 20                
                candidates.append({
                    "iso": iso,
                    "raw": raw,
                    "pos": start_pos,
                    "score": score,
                    "type": "de"
                })

    # Suche ISO Formate
    for match in regex_iso.finditer(text):
        raw = match.group(0)
        y, m, d = match.group(1), match.group(2), match.group(3)
        iso = normalize_date(f"{y}-{m}-{d}", "%Y-%m-%d")
        
        if iso:
            start_pos = match.start()
            line_start = text.rfind('\n', 0, start_pos) + 1
            line_end = text.find('\n', start_pos)
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end].lower()

            score = 10
            if "datum" in line: score += 50
            
            candidates.append({
                "iso": iso,
                "raw": raw,
                "pos": start_pos,
                "score": score,
                "type": "iso"
            })

    # Suche Formate mit Monatsnamen
    for match in regex_month_name.finditer(text):
        raw = match.group(0)
        day, month_str, year = match.groups()
        month_key = month_str.lower().replace('.', '')
        
        if month_key in MONTH_MAP:
            month = MONTH_MAP[month_key]
            iso = normalize_date(f"{day}.{month}.{year}", "%d.%m.%Y")
            if iso:
                start_pos = match.start()
                line_start = text.rfind('\n', 0, start_pos) + 1
                line_end = text.find('\n', start_pos)
                if line_end == -1:
                    line_end = len(text)
                line = text[line_start:line_end].lower()

                score = 60 # Höherer Basis-Score, da Monatsname sehr zuverlässig ist
                if "datum" in line: score += 40
                if "liefer" in line: score += 20
                
                candidates.append({
                    "iso": iso,
                    "raw": raw,
                    "pos": start_pos,
                    "score": score,
                    "type": "month_name"
                })


    # B) Instrumentierung: Logge Kandidaten
    if DEBUG_MODE:
        logger.debug(f"Gefundene Kandidaten: {len(candidates)}")
        for i, c in enumerate(sorted(candidates, key=lambda x: x['score'], reverse=True)[:5]):
            logger.debug(f"  [{i}] {c['iso']} (Score: {c['score']}, Raw: '{c['raw']}')")

    if not candidates:
        return None, "no_candidates_found"

    # Auswahl des besten Kandidaten (höchster Score, dann Position im Dokument)
    # Sortierung: Score absteigend, dann Position aufsteigend (früher im Dokument ist oft besser bei gleichem Score)
    best = sorted(candidates, key=lambda x: (-x['score'], x['pos']))[0]

    reason = f"score_{best['score']}_type_{best['type']}"
    
    if DEBUG_MODE:
        logger.debug(f"FINAL DECISION: {best['iso']} ({reason})")

    return best['iso'], reason