"""
ML-Analyzer für Docaro - Lieferant, Datum, Dokumenttyp-Klassifikation.

Integriert MLflow für Experiment-Tracking und Modell-Management.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


@dataclass
class MLAnalysisResult:
    """Ergebnis der ML-Analyse."""
    
    supplier: Optional[str] = None
    supplier_confidence: float = 0.0
    supplier_candidates: List[Tuple[str, float]] = None
    
    date: Optional[str] = None
    date_confidence: float = 0.0
    date_candidates: List[Tuple[str, float]] = None
    
    document_type: Optional[str] = None
    doctype_confidence: float = 0.0
    doctype_probabilities: Dict[str, float] = None
    
    metadata: Dict[str, Any] = None


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
        
        # Lazy-Loading
        self._supplier_predictor = None
        self._date_predictor = None
        self._doctype_predictor = None
    
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
            docling_result.text,
            docling_result.layout_elements
        )
        
        # 2. Datums-Extraktion
        date, date_conf, date_candidates = self._extract_date(
            docling_result.text,
            docling_result.layout_elements
        )
        
        # 3. Dokumenttyp-Klassifikation
        doctype, doctype_conf, doctype_probs = self._predict_document_type(
            docling_result.text,
            docling_result.tables,
            docling_result.layout_elements
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
                'text_length': len(docling_result.text),
                'tables_count': len(docling_result.tables),
                'layout_elements_count': len(docling_result.layout_elements),
                'supplier_text': text[:200] if supplier else "",
                'supplier_reasons': [c[2] for c in supplier_candidates[:1]] if supplier_candidates else [],
                'date_text': text[:200] if date else "",
                'date_reasons': ["multi_candidate_scoring"],
                'doctype_reasons': [f"{k}={v:.2f}" for k, v in doctype_probs.items()]
            }
        )
    
    def _predict_supplier(
        self,
        text: str,
        layout_elements: List
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
    
    def _find_supplier_candidates(
        self,
        text: str,
        layout_elements: List,
        suppliers_db: List[Dict]
    ) -> List[Tuple[str, float]]:
        """
        Findet Lieferanten-Kandidaten im Text via Fuzzy-Matching.
        """
        from difflib import SequenceMatcher
        
        candidates = []
        
        # Normalisiere Text
        text_lower = text.lower()
        
        for supplier in suppliers_db:
            name = supplier['name']
            aliases = supplier.get('aliases', [])
            
            # Prüfe exakte Matches
            if name.lower() in text_lower:
                candidates.append((name, 0.95))
                continue
            
            # Prüfe Aliases
            for alias in aliases:
                if alias.lower() in text_lower:
                    candidates.append((name, 0.90))
                    continue
            
            # Fuzzy-Matching
            ratio = SequenceMatcher(None, name.lower(), text_lower).ratio()
            
            if ratio > 0.6:  # Threshold
                # Bonus für Position im Dokument (oben = wahrscheinlicher)
                position_bonus = self._calculate_position_score(name, layout_elements)
                score = ratio * 0.7 + position_bonus * 0.3
                candidates.append((name, score))
        
        return candidates
    
    def _calculate_position_score(self, name: str, layout_elements: List) -> float:
        """
        Berechnet Score basierend auf Position im Dokument.
        
        Header/erste Seite = höherer Score
        """
        if not layout_elements:
            return 0.5
        
        for element in layout_elements[:10]:  # Erste 10 Elemente
            if element.element_type in ['header', 'heading_1'] and element.page == 0:
                if name.lower() in element.text.lower():
                    return 1.0
        
        # Suche in ersten Elementen
        for i, element in enumerate(layout_elements[:20]):
            if name.lower() in element.text.lower():
                # Je früher, desto höher der Score
                return 1.0 - (i / 20) * 0.5
        
        return 0.3  # Fallback
    
    def _extract_date(
        self,
        text: str,
        layout_elements: List
    ) -> Tuple[Optional[str], float, List[Tuple[str, float]]]:
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
        date_iso = best.date_obj.strftime('%Y-%m-%d')
        
        _LOGGER.debug(f"Date-Match: {date_iso} (Conf: {best.confidence:.2f}, Label: {best.label}, Gründe: {best.reasons})")
        
        # Konvertiere zu Tuple-Format
        candidates_tuples = [(c.date_str, c.confidence) for c in candidates[:5]]
        
        return date_iso, best.confidence, candidates_tuples
    
    def _find_date_candidates(
        self,
        text: str,
        layout_elements: List
    ) -> List[Tuple[str, float]]:
        """
        Findet Datum-Kandidaten mit Regex-Patterns.
        """
        from constants import DATE_REGEX_PATTERNS, DATE_LABELS
        
        candidates = []
        
        # Regex-Patterns
        patterns = [
            (r'\b(\d{1,2}\.\d{1,2}\.\d{4})\b', 'dd.mm.yyyy'),  # 15.01.2026
            (r'\b(\d{4}-\d{2}-\d{2})\b', 'yyyy-mm-dd'),        # 2026-01-15
            (r'\b(\d{1,2}/\d{1,2}/\d{4})\b', 'mm/dd/yyyy'),    # 01/15/2026
        ]
        
        for pattern, format_name in patterns:
            matches = re.findall(pattern, text)
            
            for match in matches:
                # Prüfe auf Label-Keywords in der Nähe
                label_score = self._check_date_label_proximity(match, text)
                
                # Position-Score
                position_score = self._calculate_date_position_score(match, layout_elements)
                
                # Kombinierter Score
                score = label_score * 0.6 + position_score * 0.4
                
                candidates.append((match, score))
        
        return candidates
    
    def _check_date_label_proximity(self, date_str: str, text: str) -> float:
        """
        Prüft, ob Date-Labels in der Nähe sind.
        
        z.B. "Rechnungsdatum: 15.01.2026" → höherer Score
        """
        date_labels = [
            'rechnungsdatum', 'datum', 'lieferdatum', 'bestelldatum',
            'date', 'invoice date', 'delivery date'
        ]
        
        # Finde Position des Datums im Text
        date_pos = text.lower().find(date_str.lower())
        
        if date_pos == -1:
            return 0.5
        
        # Prüfe 50 Zeichen vor dem Datum
        context = text[max(0, date_pos - 50):date_pos].lower()
        
        for label in date_labels:
            if label in context:
                return 1.0
        
        return 0.5
    
    def _calculate_date_position_score(self, date_str: str, layout_elements: List) -> float:
        """Score basierend auf Position (Header = wichtiger)."""
        if not layout_elements:
            return 0.5
        
        for element in layout_elements[:15]:
            if element.element_type in ['header', 'heading_1', 'heading_2']:
                if date_str in element.text:
                    return 1.0
        
        return 0.6
    
    def _normalize_date(self, date_str: str) -> Optional[str]:
        """Konvertiert Datum zu ISO-Format (YYYY-MM-DD)."""
        from dateutil import parser
        
        try:
            parsed = parser.parse(date_str, dayfirst=True)
            return parsed.strftime('%Y-%m-%d')
        except:
            _LOGGER.debug(f"Datum-Parsing fehlgeschlagen: {date_str}")
            return date_str
    
    def _predict_document_type(
        self,
        text: str,
        tables: List,
        layout_elements: List
    ) -> Tuple[Optional[str], float, Dict[str, float]]:
        """
        Dokumenttyp-Klassifikation.
        
        **Typen**:
        - Rechnung
        - Lieferschein
        - Bestellung
        - Gutschrift
        - Sonstige
        
        **Features**:
        - Keywords ("Rechnung", "Lieferschein", etc.)
        - Tabellenanzahl
        - Layout-Struktur
        - BERT-Embeddings (optional)
        
        Returns:
            (dokumenttyp, confidence, probabilities_dict)
        """
        # 1. Keyword-basierte Klassifikation
        keyword_scores = self._classify_by_keywords(text)
        
        # 2. Struktur-basierte Features
        structure_score = self._calculate_structure_features(tables, layout_elements)
        Returns:
            (dokumenttyp, confidence, probabilities_dict)
        """
        from core.doctype_classifier import DoctypeClassifier
        
        # Nutze regel-basierten Classifier
        classifier = DoctypeClassifier(min_confidence=0.6)
        result = classifier.classify(text)
        
        _LOGGER.debug(f"Doctype: {result.doctype} (Conf: {result.confidence:.2f}, Gründe: {result.reasons})")
        
        return result.doctype, result.confidence, result.scor
            
            # Normalisiere
            scores[doc_type] = min(score / (len(keywords) + 1), 1.0) if keywords else 0.1
        
        # Normalisiere zu Wahrscheinlichkeiten
        total = sum(scores.values())
        if total > 0:
            scores = {k: v / total for k, v in scores.items()}
        
        return scores
    
    def _calculate_structure_features(self, tables: List, layout_elements: List) -> Dict[str, float]:
        """Extrahiert strukturelle Features."""
        return {
            'table_count': len(tables),
            'has_table': 1.0 if tables else 0.0,
            'layout_complexity': len(layout_elements) / 100.0,  # Normalisiert
        }
    
    def _load_suppliers_db(self) -> List[Dict]:
        """Lädt Lieferanten-Datenbank."""
        import json
        from config import Config
        
        config = Config()
        db_path = config.DATA_DIR / "suppliers.json"
        
        if not db_path.exists():
            _LOGGER.warning(f"Lieferanten-DB nicht gefunden: {db_path}")
            return []
        
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('suppliers', [])
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Lieferanten-DB: {e}")
            return []
    
    def _get_supplier_predictor(self):
        """Lazy-Loading für Lieferanten-Predictor."""
        if self._supplier_predictor is not None:
            return self._supplier_predictor
        
        try:
            from ml.inference.supplier_predictor import SupplierPredictor
            
            model_path = self.models_dir / "supplier_classifier"
            
            if model_path.exists():
                self._supplier_predictor = SupplierPredictor(model_path)
                return self._supplier_predictor
        except Exception as e:
            _LOGGER.debug(f"Supplier-Predictor nicht verfügbar: {e}")
        
        return None
    
    def _get_date_predictor(self):
        """Lazy-Loading für Datums-Predictor."""
        if self._date_predictor is not None:
            return self._date_predictor
        
        try:
            from ml.inference.date_predictor import DatePredictor
            
            model_path = self.models_dir / "date_extractor"
            
            if model_path.exists():
                self._date_predictor = DatePredictor(model_path)
                return self._date_predictor
        except Exception as e:
            _LOGGER.debug(f"Date-Predictor nicht verfügbar: {e}")
        
        return None
    
    def _get_doctype_predictor(self):
        """Lazy-Loading für Dokumenttyp-Predictor."""
        if self._doctype_predictor is not None:
            return self._doctype_predictor
        
        try:
            from ml.inference.doctype_predictor import DoctypePredictor
            
            model_path = self.models_dir / "doctype_classifier"
            
            if model_path.exists():
                self._doctype_predictor = DoctypePredictor(model_path)
                return self._doctype_predictor
        except Exception as e:
            _LOGGER.debug(f"Doctype-Predictor nicht verfügbar: {e}")
        
        return None
