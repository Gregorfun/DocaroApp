"""
ML-Analyzer für Docaro - Lieferant, Datum, Dokumenttyp-Klassifikation.

Integriert MLflow für Experiment-Tracking und Modell-Management.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


@dataclass
class MLAnalysisResult:
    """Ergebnis der ML-Analyse."""

    supplier: Optional[str] = None
    supplier_confidence: float = 0.0
    supplier_candidates: List[Tuple[str, float]] = field(default_factory=list)

    date: Optional[str] = None
    date_confidence: float = 0.0
    date_candidates: List[Tuple[str, float]] = field(default_factory=list)

    document_type: Optional[str] = None
    doctype_confidence: float = 0.0
    doctype_probabilities: Dict[str, float] = field(default_factory=dict)

    metadata: Dict[str, Any] = field(default_factory=dict)


class MLAnalyzer:
    """
    ML-basierte Analyse für Dokumenten-Extraktion.

    **Komponenten**:
    1. Lieferanten-Klassifikation (ML-Modell)
    2. Datums-Extraktion (Hybrid: Regex + ML)
    3. Dokumenttyp-Klassifikation (ML-Modell)

    **ML-Stack**:
    - MLflow: Modell-Tracking & Registry
    - Scikit-learn: Klassifikation
    - Transformers: BERT-basierte Klassifikation (optional)
    """

    def __init__(self, models_dir: Path = None):
        """
        Args:
            models_dir: Pfad zu trainierten Modellen (default: ml/models/)
        """
        if models_dir is None:
            models_dir = Path(__file__).parent.parent / "ml" / "models"

        self.models_dir = models_dir

        pass

    def analyze(self, docling_result) -> MLAnalysisResult:
        """
        Analysiert Docling-Ergebnis mit ML-Modellen.

        Args:
            docling_result: DoclingProcessingResult aus document_processor

        Returns:
            MLAnalysisResult mit extrahierten Informationen
        """
        _LOGGER.debug("Starte ML-Analyse...")

        # 1. Lieferanten-Klassifikation
        supplier, supplier_conf, supplier_candidates = self._predict_supplier(
            docling_result.text, docling_result.layout_elements
        )

        # 2. Datums-Extraktion
        date, date_conf, date_candidates = self._extract_date(docling_result.text, docling_result.layout_elements)

        # 3. Dokumenttyp-Klassifikation
        doctype, doctype_conf, doctype_probs = self._predict_document_type(
            docling_result.text, docling_result.tables, docling_result.layout_elements
        )

        return MLAnalysisResult(
            supplier=supplier,
            supplier_confidence=supplier_conf,
            supplier_candidates=supplier_candidates,
            date=date,
            date_confidence=date_conf,
            date_candidates=date_candidates,
            document_type=doctype,
            doctype_confidence=doctype_conf,
            doctype_probabilities=doctype_probs,
            metadata={
                "text_length": len(docling_result.text),
                "tables_count": len(docling_result.tables),
                "layout_elements_count": len(docling_result.layout_elements),
                "supplier_text": docling_result.text[:200] if supplier else "",
                "supplier_reasons": [c[2] for c in supplier_candidates[:1]] if supplier_candidates else [],
                "date_text": docling_result.text[:200] if date else "",
                "date_reasons": ["multi_candidate_scoring"],
                "doctype_reasons": [f"{k}={v:.2f}" for k, v in doctype_probs.items()],
            },
        )

    def _predict_supplier(
        self, text: str, layout_elements: List
    ) -> Tuple[Optional[str], float, List[Tuple[str, float]]]:
        """
        Lieferanten-Klassifikation mit Fingerprinting.

        Returns:
            (lieferant, confidence, kandidaten_liste)
        """
        from core.supplier_fingerprint import SupplierMatcher
        from config import Config

        # Nutze robustes Fingerprinting
        matcher = SupplierMatcher(Config.DATA_DIR / "suppliers.json")
        matches = matcher.match(text, top_n=5)

        if not matches:
            _LOGGER.warning("Keine Lieferanten-Kandidaten gefunden")
            return None, 0.0, []

        best_supplier, best_score, best_reason = matches[0]
        _LOGGER.debug(f"Supplier-Match: {best_supplier} (Score: {best_score:.2f}, Grund: {best_reason})")

        return best_supplier, best_score, matches

    def _extract_date(self, text: str, layout_elements: List) -> Tuple[Optional[str], float, List[Tuple[str, float]]]:
        """
        Datums-Extraktion mit Multi-Kandidaten-Scoring.

        Returns:
            (datum_iso, confidence, kandidaten_liste)
        """
        from core.date_scorer import DateScorer

        # Nutze intelligenten Date-Scorer
        scorer = DateScorer(max_future_days=30, max_past_years=2, min_confidence=0.5)
        candidates = scorer.extract_dates(text, page=0, context_window=50)

        if not candidates:
            _LOGGER.warning("Keine Datums-Kandidaten gefunden")
            return None, 0.0, []

        best = scorer.get_best_date(candidates)
        date_iso = best.date_obj.strftime("%Y-%m-%d")

        _LOGGER.debug(
            f"Date-Match: {date_iso} (Conf: {best.confidence:.2f}, Label: {best.label}, Gründe: {best.reasons})"
        )

        # Konvertiere zu Tuple-Format
        candidates_tuples = [(c.date_str, c.confidence) for c in candidates[:5]]

        return date_iso, best.confidence, candidates_tuples

    def _predict_document_type(
        self, text: str, tables: List, layout_elements: List
    ) -> Tuple[Optional[str], float, Dict[str, float]]:
        """
        Dokumenttyp-Klassifikation.

        Returns:
            (dokumenttyp, confidence, probabilities_dict)
        """
        from core.doctype_classifier import DoctypeClassifier

        classifier = DoctypeClassifier(min_confidence=0.6)
        result = classifier.classify(text)

        _LOGGER.debug(f"Doctype: {result.doctype} (Conf: {result.confidence:.2f}, Gründe: {result.reasons})")

        return result.doctype, result.confidence, result.scores
