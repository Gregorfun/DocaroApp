"""
Dokumenttyp-Klassifikation (DocType Classification).

Erkennt automatisch den Dokumenttyp basierend auf OCR/Text-Extraktion:
- RECHNUNG
- LIEFERSCHEIN
- ÜBERNAHMESCHEIN
- KOMMISSIONIERLISTE
- PRÜFBERICHT
- SONSTIGES
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.text_segments import segment_header_body_footer

_LOGGER = logging.getLogger(__name__)


@dataclass
class DocTypeResult:
    """Ergebnis der Dokumenttyp-Klassifikation."""
    doc_type: str
    confidence: float
    evidence: List[str]  # Top-5 gefundene Keywords
    scores: Dict[str, float] = field(default_factory=dict)
    evidence_by_type: Dict[str, List[str]] = field(default_factory=dict)


class DocTypeClassifier:
    """Klassifiziert Dokumente nach Typ basierend auf Keywords."""
    
    DOCTYPE_RECHNUNG = "RECHNUNG"
    DOCTYPE_LIEFERSCHEIN = "LIEFERSCHEIN"
    DOCTYPE_UEBERNAHMESCHEIN = "ÜBERNAHMESCHEIN"
    DOCTYPE_KOMMISSIONIERLISTE = "KOMMISSIONIERLISTE"
    DOCTYPE_PRUEFBERICHT = "PRÜFBERICHT"
    DOCTYPE_SONSTIGES = "SONSTIGES"
    
    def __init__(self):
        """Initialisiert Keyword-Dictionaries für jeden Dokumenttyp."""
        
        # RECHNUNG Keywords
        # Wichtig: "iban/mwst" alleine darf NIE eine Rechnung entscheiden.
        self.rechnung_title = [
            "rechnung",
            "invoice",
        ]
        self.rechnung_strong_support = [
            "rechnungsnummer",
            "rechnungs-nr",
            "invoice number",
            "zahlungsziel",
            "payment terms",
            "fällig",
        ]
        self.rechnung_weak_support = [
            "betrag",
            "netto",
            "brutto",
            "summe",
            "total",
            "gesamt",
            "steuer",
            "tax",
            "mehrwertsteuer",
            "mwst",
            "iban",
            "bic",
            "bankverbindung",
        ]
        self.rechnung_negative = [
            "lieferschein",
            "delivery note",
            "uebernahmeschein",
            "übernahmeschein",
        ]
        
        # LIEFERSCHEIN Keywords
        self.lieferschein_strong = [
            "lieferschein",
            "delivery note",
            "lieferschein-nr",
            "lieferscheinnr",
            "lieferdatum",
            "delivery date",
            "warenempfänger",
        ]
        self.lieferschein_support = [
            "belegnummer",
            "versand",
            "shipment",
            "warenausgang",
            "lieferung",
        ]
        
        # ÜBERNAHMESCHEIN Keywords (Top-Priority)
        self.uebernahmeschein_strong = [
            "uebernahmeschein",
            "übernahmeschein",
            "entsorgungsnachweis",
            "entsorgung",
        ]
        self.uebernahmeschein_support = [
            "abfall",
            "recycling",
            "container",
            "tonne",
            "mulde",
            "abfallart",
            "abfallschluessel",
            "avv-nr",
            "avv",
            "kilogramm",
            "kg",
            "tonnen",
            "kubikmeter",
            "m3",
            "abholung",
            "anlieferung",
        ]
        
        # KOMMISSIONIERLISTE Keywords
        self.kommissionierliste_stark = [
            "kommissionierliste", "picking list", "kommissionierung",
            "pickliste", "entnahmeliste", "auftragsliste",
            "kommissionierauftrag", "picking", "kommission"
        ]
        self.kommissionierliste_unterstuetzend = [
            "lager", "lagerplatz", "regal", "fach", "position",
            "entnehmen", "bereitstellen"
        ]

        # PRÜFBERICHT Keywords (z.B. DEKRA Prüfbericht / HU/AU)
        self.pruefbericht_strong = [
            "pruefbericht",
            "prüfbericht",
            "untersuchungsbericht",
            "hauptuntersuchung",
            "hu-bericht",
            "hu bericht",
        ]
        self.pruefbericht_support = [
            "stvzo",
            "§ 29",
            "maengel",
            "mängel",
            "kennz",
            "kennzeichen",
            "fahrzeug",
            "fahrzeugschein",
            "plakette",
        ]
    
    def _normalize_text(self, text: str) -> str:
        """Normalisiert Text für robuste Keyword-Suche."""
        text = text.lower()
        text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        text = re.sub(r'\s+', ' ', text)
        return text

    def _weighted_hits(self, segment_text: str, keywords: List[str], *, weight: float, add: float) -> tuple[float, List[str]]:
        score = 0.0
        evidence: List[str] = []
        norm = self._normalize_text(segment_text)
        for kw in keywords:
            kw_norm = self._normalize_text(kw)
            if kw_norm and kw_norm in norm:
                score += add * weight
                evidence.append(kw)
        return score, evidence
    
    def _score_kommissionierliste(self, text_norm: str) -> tuple[float, List[str]]:
        """Berechnet Score für KOMMISSIONIERLISTE-Typ."""
        score = 0.0
        evidence = []
        
        for kw in self.kommissionierliste_stark:
            kw_norm = self._normalize_text(kw)
            if kw_norm in text_norm:
                score += 0.25
                evidence.append(kw)
        
        for kw in self.kommissionierliste_unterstuetzend:
            kw_norm = self._normalize_text(kw)
            if kw_norm in text_norm:
                score += 0.10
                evidence.append(kw)
        
        return score, evidence
    
    def _apply_supplier_hints(self, scores: dict, supplier_canonical: Optional[str]) -> dict:
        """Wendet Supplier-spezifische Hints an."""
        if not supplier_canonical:
            return scores
        
        # Manitowoc-Rechnungen oft ohne "Rechnung" Keyword
        if supplier_canonical == "Manitowoc":
            scores[self.DOCTYPE_RECHNUNG] += 0.10

        # DEKRA-Dokumente sind sehr häufig PRÜFBERICHT
        if supplier_canonical == "Dekra" and self.DOCTYPE_PRUEFBERICHT in scores:
            scores[self.DOCTYPE_PRUEFBERICHT] += 0.30
        
        return scores
    
    def classify_doc_type(self, text: str, supplier_canonical: Optional[str] = None) -> DocTypeResult:
        """
        Klassifiziert Dokumenttyp basierend auf Text und optionalem Supplier.
        
        Args:
            text: OCR-Text (kombiniert aus Textlayer + OCR)
            supplier_canonical: Kanonischer Supplier-Name (optional)
        
        Returns:
            DocTypeResult mit doc_type, confidence, evidence
        """
        supplier_norm = (supplier_canonical or "").strip().upper()
        if supplier_norm in {"WM", "WM SE", "WMSE"}:
            scores: Dict[str, float] = {
                self.DOCTYPE_RECHNUNG: 0.0,
                self.DOCTYPE_LIEFERSCHEIN: 1.0,
                self.DOCTYPE_UEBERNAHMESCHEIN: 0.0,
                self.DOCTYPE_KOMMISSIONIERLISTE: 0.0,
                self.DOCTYPE_PRUEFBERICHT: 0.0,
            }
            evidence_by_type: Dict[str, List[str]] = {
                self.DOCTYPE_LIEFERSCHEIN: ["supplier_hint:WM"],
            }
            return DocTypeResult(
                doc_type=self.DOCTYPE_LIEFERSCHEIN,
                confidence=0.99,
                evidence=["supplier_hint:WM"],
                scores=scores,
                evidence_by_type=evidence_by_type,
            )

        segments = segment_header_body_footer(text, header_lines=35, footer_lines=35)
        header_text = "\n".join(segments.header_lines)
        body_text = "\n".join(segments.body_lines)
        footer_text = "\n".join(segments.footer_lines)

        weights = {"header": 2.0, "body": 1.0, "footer": 0.5}

        scores: Dict[str, float] = {
            self.DOCTYPE_RECHNUNG: 0.0,
            self.DOCTYPE_LIEFERSCHEIN: 0.0,
            self.DOCTYPE_UEBERNAHMESCHEIN: 0.0,
            self.DOCTYPE_KOMMISSIONIERLISTE: 0.0,
            self.DOCTYPE_PRUEFBERICHT: 0.0,
        }
        evidences: Dict[str, List[str]] = {k: [] for k in scores.keys()}

        # ÜBERNAHMESCHEIN: Top-Priority sobald Keyword in header/body
        for seg_name, seg_text in (("header", header_text), ("body", body_text), ("footer", footer_text)):
            w = weights[seg_name]
            s, ev = self._weighted_hits(seg_text, self.uebernahmeschein_strong, weight=w, add=0.40)
            scores[self.DOCTYPE_UEBERNAHMESCHEIN] += s
            evidences[self.DOCTYPE_UEBERNAHMESCHEIN].extend([f"{e}@{seg_name}" for e in ev])
            s2, ev2 = self._weighted_hits(seg_text, self.uebernahmeschein_support, weight=w, add=0.12)
            scores[self.DOCTYPE_UEBERNAHMESCHEIN] += s2
            evidences[self.DOCTYPE_UEBERNAHMESCHEIN].extend([f"{e}@{seg_name}" for e in ev2])

        # LIEFERSCHEIN
        for seg_name, seg_text in (("header", header_text), ("body", body_text), ("footer", footer_text)):
            w = weights[seg_name]
            s, ev = self._weighted_hits(seg_text, self.lieferschein_strong, weight=w, add=0.35)
            scores[self.DOCTYPE_LIEFERSCHEIN] += s
            evidences[self.DOCTYPE_LIEFERSCHEIN].extend([f"{e}@{seg_name}" for e in ev])
            s2, ev2 = self._weighted_hits(seg_text, self.lieferschein_support, weight=w, add=0.10)
            scores[self.DOCTYPE_LIEFERSCHEIN] += s2
            evidences[self.DOCTYPE_LIEFERSCHEIN].extend([f"{e}@{seg_name}" for e in ev2])

        # RECHNUNG: Nur wenn "rechnung" oder "invoice" im HEADER
        header_norm = self._normalize_text(header_text)
        has_invoice_title = any(self._normalize_text(k) in header_norm for k in self.rechnung_title)
        if has_invoice_title:
            s, ev = self._weighted_hits(header_text, self.rechnung_title, weight=weights["header"], add=0.45)
            scores[self.DOCTYPE_RECHNUNG] += s
            evidences[self.DOCTYPE_RECHNUNG].extend([f"{e}@header" for e in ev])

            for seg_name, seg_text in (("header", header_text), ("body", body_text), ("footer", footer_text)):
                w = weights[seg_name]
                s2, ev2 = self._weighted_hits(seg_text, self.rechnung_strong_support, weight=w, add=0.18)
                scores[self.DOCTYPE_RECHNUNG] += s2
                evidences[self.DOCTYPE_RECHNUNG].extend([f"{e}@{seg_name}" for e in ev2])
                s3, ev3 = self._weighted_hits(seg_text, self.rechnung_weak_support, weight=w, add=0.05)
                scores[self.DOCTYPE_RECHNUNG] += s3
                evidences[self.DOCTYPE_RECHNUNG].extend([f"{e}@{seg_name}" for e in ev3])

        # KOMMISSIONIERLISTE (unverändert, aber gewichtet)
        for seg_name, seg_text in (("header", header_text), ("body", body_text), ("footer", footer_text)):
            w = weights[seg_name]
            s, ev = self._weighted_hits(seg_text, self.kommissionierliste_stark, weight=w, add=0.25)
            scores[self.DOCTYPE_KOMMISSIONIERLISTE] += s
            evidences[self.DOCTYPE_KOMMISSIONIERLISTE].extend([f"{e}@{seg_name}" for e in ev])
            s2, ev2 = self._weighted_hits(seg_text, self.kommissionierliste_unterstuetzend, weight=w, add=0.10)
            scores[self.DOCTYPE_KOMMISSIONIERLISTE] += s2
            evidences[self.DOCTYPE_KOMMISSIONIERLISTE].extend([f"{e}@{seg_name}" for e in ev2])

        # PRÜFBERICHT
        for seg_name, seg_text in (("header", header_text), ("body", body_text), ("footer", footer_text)):
            w = weights[seg_name]
            s, ev = self._weighted_hits(seg_text, self.pruefbericht_strong, weight=w, add=0.40)
            scores[self.DOCTYPE_PRUEFBERICHT] += s
            evidences[self.DOCTYPE_PRUEFBERICHT].extend([f"{e}@{seg_name}" for e in ev])
            s2, ev2 = self._weighted_hits(seg_text, self.pruefbericht_support, weight=w, add=0.08)
            scores[self.DOCTYPE_PRUEFBERICHT] += s2
            evidences[self.DOCTYPE_PRUEFBERICHT].extend([f"{e}@{seg_name}" for e in ev2])

        # Negative Keywords: Rechnung runter, wenn Lieferschein/Übernahme klar
        all_text_norm = self._normalize_text(text)
        for kw in self.rechnung_negative:
            if self._normalize_text(kw) in all_text_norm:
                scores[self.DOCTYPE_RECHNUNG] -= 0.15
        
        # Supplier-Hints
        scores = self._apply_supplier_hints(scores, supplier_canonical)
        
        # Übernahmeschein sofort, wenn strong keyword in header/body
        header_body_norm = self._normalize_text(header_text + "\n" + body_text)
        if any(self._normalize_text(k) in header_body_norm for k in self.uebernahmeschein_strong):
            conf = min(0.99, 0.88 + min(scores[self.DOCTYPE_UEBERNAHMESCHEIN], 1.0) * 0.10)
            return DocTypeResult(
                doc_type=self.DOCTYPE_UEBERNAHMESCHEIN,
                confidence=conf,
                evidence=evidences.get(self.DOCTYPE_UEBERNAHMESCHEIN, [])[:5],
                scores=scores,
                evidence_by_type={k: v[:8] for k, v in evidences.items()},
            )

        # Bester Typ
        if not scores or all(s <= 0 for s in scores.values()):
            return DocTypeResult(
                doc_type=self.DOCTYPE_SONSTIGES,
                confidence=0.50,
                evidence=["keine eindeutigen keywords"],
                scores=scores,
                evidence_by_type={k: v[:8] for k, v in evidences.items()},
            )
        
        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]
        second_best = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0

        # Lieferschein: wenn starker Header-Hit => priorisieren
        if best_type != self.DOCTYPE_LIEFERSCHEIN:
            header_norm2 = self._normalize_text(header_text)
            if any(self._normalize_text(k) in header_norm2 for k in self.lieferschein_strong):
                # Nur überschreiben, wenn Rechnung nicht klar im Header ist
                if not has_invoice_title:
                    best_type = self.DOCTYPE_LIEFERSCHEIN
                    best_score = scores[best_type]
                    second_best = max(v for k, v in scores.items() if k != best_type)

        # Confidence Berechnung
        confidence = min(0.99, 0.55 + min(best_score, 1.0) * 0.35 + max(0.0, best_score - second_best) * 0.25)

        # Fallback SONSTIGES nur wenn keine Klasse confidence >= 0.60
        if confidence < 0.60:
            return DocTypeResult(
                doc_type=self.DOCTYPE_SONSTIGES,
                confidence=confidence,
                evidence=evidences.get(best_type, [])[:5],
                scores=scores,
                evidence_by_type={k: v[:8] for k, v in evidences.items()},
            )

        return DocTypeResult(
            doc_type=best_type,
            confidence=confidence,
            evidence=evidences.get(best_type, [])[:5],
            scores=scores,
            evidence_by_type={k: v[:8] for k, v in evidences.items()},
        )


# Singleton
_classifier = None


def get_doctype_classifier() -> DocTypeClassifier:
    """Liefert Singleton-Instanz."""
    global _classifier
    if _classifier is None:
        _classifier = DocTypeClassifier()
    return _classifier


def classify_doc_type(text: str, supplier_canonical: Optional[str] = None) -> DocTypeResult:
    """
    Convenience-Funktion für Dokumenttyp-Klassifikation.
    
    Args:
        text: OCR-Text
        supplier_canonical: Kanonischer Supplier-Name
    
    Returns:
        DocTypeResult
    """
    classifier = get_doctype_classifier()
    return classifier.classify_doc_type(text, supplier_canonical)
