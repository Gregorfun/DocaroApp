"""
Dokumenttyp-Klassifikation mit ML.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


@dataclass
class DoctypeResult:
    """Ergebnis der Dokumenttyp-Klassifikation."""
    doctype: str
    confidence: float
    reasons: List[str]
    scores: Dict[str, float]


class DoctypeClassifier:
    """
    Regel-basierter Dokumenttyp-Klassifikator.
    
    Typen:
    - Rechnung
    - Lieferschein
    - Gutschrift
    - Servicebericht
    - Angebot
    - Auftrag
    - Unklar
    """
    
    # Keyword-basierte Regeln
    RULES = {
        "Rechnung": {
            "keywords": ["rechnung", "invoice", "rechnungsnummer", "rg-nr", "faktura"],
            "negative_keywords": ["gutschrift", "angebot", "lieferschein"],
            "weight": 1.0
        },
        "Lieferschein": {
            "keywords": ["lieferschein", "delivery note", "lieferschein-nr", "ls-nr"],
            "negative_keywords": ["rechnung", "gutschrift"],
            "weight": 1.0
        },
        "Gutschrift": {
            "keywords": ["gutschrift", "credit note", "stornier"],
            "negative_keywords": [],
            "weight": 1.0
        },
        "Servicebericht": {
            "keywords": ["servicebericht", "wartung", "service", "instandhaltung", "protokoll"],
            "negative_keywords": ["rechnung", "lieferschein"],
            "weight": 0.8
        },
        "Angebot": {
            "keywords": ["angebot", "quote", "angebots-nr", "offerte"],
            "negative_keywords": ["rechnung", "auftrag"],
            "weight": 0.9
        },
        "Auftrag": {
            "keywords": ["auftrag", "order", "auftrags-nr", "bestellung"],
            "negative_keywords": ["angebot", "rechnung"],
            "weight": 0.9
        },
    }
    
    def __init__(self, min_confidence: float = 0.6):
        """
        Args:
            min_confidence: Min. Confidence für eindeutiges Ergebnis
        """
        self.min_confidence = min_confidence
    
    def classify(self, text: str) -> DoctypeResult:
        """
        Klassifiziert Dokumenttyp.
        
        Args:
            text: OCR-Text (erste Seite meist ausreichend)
        
        Returns:
            DoctypeResult mit Typ, Confidence und Scores
        """
        text_lower = text.lower()
        scores = {}
        reasons_map = {}
        
        for doctype, rules in self.RULES.items():
            score = 0.0
            reasons = []
            
            # Positive Keywords
            for kw in rules["keywords"]:
                count = text_lower.count(kw)
                if count > 0:
                    score += count * rules["weight"]
                    reasons.append(f"{kw}={count}")
            
            # Negative Keywords (Abzug)
            for neg_kw in rules["negative_keywords"]:
                count = text_lower.count(neg_kw)
                if count > 0:
                    score -= count * 0.5
                    reasons.append(f"!{neg_kw}={count}")
            
            scores[doctype] = max(score, 0.0)
            reasons_map[doctype] = reasons
        
        # Normalisiere Scores
        total = sum(scores.values())
        if total > 0:
            scores = {k: v / total for k, v in scores.items()}
        
        # Bester Kandidat
        best_type = max(scores, key=scores.get) if scores else "Unklar"
        best_score = scores.get(best_type, 0.0)
        
        # Confidence-Schwelle
        if best_score < self.min_confidence:
            best_type = "Unklar"
            best_score = 0.0
        
        return DoctypeResult(
            doctype=best_type,
            confidence=best_score,
            reasons=reasons_map.get(best_type, []),
            scores=scores
        )
