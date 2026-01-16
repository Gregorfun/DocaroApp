"""
Multi-Kandidaten Datum-Extraktion mit Kontext-Scoring.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


@dataclass
class DateCandidate:
    """Ein Datum-Kandidat mit Metadaten."""
    date_str: str
    date_obj: datetime
    confidence: float = 0.0
    source_text: str = ""
    page: int = 0
    position: Tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h
    label: Optional[str] = None  # "Rechnungsdatum", "Lieferdatum", etc.
    reasons: List[str] = field(default_factory=list)


class DateScorer:
    """
    Intelligenter Datum-Extraktor mit Kontext-Analyse.
    
    Strategien:
    1. Mehrere Kandidaten finden
    2. Kontext-Labels erkennen (Rechnung, Lieferung, etc.)
    3. Plausibilität prüfen (Zukunftsdaten, zu alt, etc.)
    4. Best-Pick mit Confidence + Erklärung
    """
    
    # Label-Keywords
    LABEL_KEYWORDS = {
        "Rechnungsdatum": ["rechnung", "invoice", "datum", "date", "rg"],
        "Lieferdatum": ["liefer", "delivery", "auslieferung"],
        "Bestelldatum": ["bestell", "order", "auftrag"],
        "Fälligkeitsdatum": ["fällig", "zahlung", "due"],
    }
    
    # Date-Patterns (DD.MM.YYYY, DD/MM/YYYY, YYYY-MM-DD, etc.)
    DATE_PATTERNS = [
        r'\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b',  # DD.MM.YYYY
        r'\b(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\b',  # YYYY-MM-DD
        r'\b(\d{1,2})\s+(jan|feb|mär|apr|mai|jun|jul|aug|sep|okt|nov|dez)\w*\s+(\d{4})\b',  # DD. Monat YYYY
    ]
    
    def __init__(
        self,
        max_future_days: int = 30,
        max_past_years: int = 2,
        min_confidence: float = 0.5
    ):
        """
        Args:
            max_future_days: Max. Tage in Zukunft
            max_past_years: Max. Jahre in Vergangenheit
            min_confidence: Min. Confidence für Rückgabe
        """
        self.max_future_days = max_future_days
        self.max_past_years = max_past_years
        self.min_confidence = min_confidence
    
    def extract_dates(
        self,
        text: str,
        page: int = 0,
        context_window: int = 50
    ) -> List[DateCandidate]:
        """
        Extrahiert alle Datum-Kandidaten aus Text.
        
        Args:
            text: OCR-Text
            page: Seitennummer
            context_window: Zeichen vor/nach für Kontext
        
        Returns:
            Liste von DateCandidate, sortiert nach Confidence
        """
        candidates = []
        
        for pattern in self.DATE_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                date_str = match.group(0)
                date_obj = self._parse_date(date_str)
                
                if not date_obj:
                    continue
                
                # Extrahiere Kontext
                start = max(0, match.start() - context_window)
                end = min(len(text), match.end() + context_window)
                context = text[start:end]
                
                # Erkenne Label
                label = self._detect_label(context)
                
                # Berechne Confidence
                confidence, reasons = self._score_date(date_obj, label, context)
                
                if confidence >= self.min_confidence:
                    candidates.append(DateCandidate(
                        date_str=date_str,
                        date_obj=date_obj,
                        confidence=confidence,
                        source_text=context,
                        page=page,
                        label=label,
                        reasons=reasons
                    ))
        
        # Sortiere nach Confidence
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parsed Datum-String zu datetime."""
        formats = [
            "%d.%m.%Y",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y-%m-%d",
            "%Y/%m/%d",
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        # Monatsnamen
        month_map = {
            "jan": 1, "feb": 2, "mär": 3, "apr": 4, "mai": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dez": 12
        }
        
        match = re.match(r'(\d{1,2})\s+(\w+)\s+(\d{4})', date_str, re.IGNORECASE)
        if match:
            day, month_str, year = match.groups()
            month_str = month_str[:3].lower()
            if month_str in month_map:
                try:
                    return datetime(int(year), month_map[month_str], int(day))
                except ValueError:
                    pass
        
        return None
    
    def _detect_label(self, context: str) -> Optional[str]:
        """Erkennt Datum-Label aus Kontext."""
        context_lower = context.lower()
        
        for label, keywords in self.LABEL_KEYWORDS.items():
            for kw in keywords:
                if kw in context_lower:
                    return label
        
        return None
    
    def _score_date(
        self,
        date_obj: datetime,
        label: Optional[str],
        context: str
    ) -> Tuple[float, List[str]]:
        """
        Bewertet Datum-Kandidat.
        
        Returns:
            (confidence, reasons)
        """
        score = 0.5
        reasons = []
        
        now = datetime.now()
        
        # 1. Plausibilität: Datum in vernünftigem Zeitraum
        days_diff = (date_obj - now).days
        
        if -365 * self.max_past_years <= days_diff <= self.max_future_days:
            score += 0.3
            reasons.append("plausible_range")
        else:
            score -= 0.5
            reasons.append("implausible_date")
        
        # 2. Label erkannt → höhere Confidence
        if label:
            score += 0.3
            reasons.append(f"label={label}")
        
        # 3. Rechnungsdatum bevorzugt
        if label == "Rechnungsdatum":
            score += 0.2
            reasons.append("invoice_date_priority")
        
        # 4. Nähe zu "heute" → höhere Wahrscheinlichkeit
        days_from_now = abs(days_diff)
        if days_from_now <= 30:
            score += 0.1
            reasons.append("recent")
        elif days_from_now <= 90:
            score += 0.05
        
        # 5. Position im Dokument (heuristisch: oben = wichtiger)
        # (könnte erweitert werden mit Bounding-Box-Info)
        
        return min(score, 1.0), reasons
    
    def get_best_date(self, candidates: List[DateCandidate]) -> Optional[DateCandidate]:
        """Gibt besten Kandidaten zurück."""
        if not candidates:
            return None
        return candidates[0]  # Bereits sortiert
