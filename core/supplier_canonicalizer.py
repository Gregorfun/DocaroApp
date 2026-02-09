"""
Supplier Canonicalizer für stabile Lieferanten-Erkennung.

Vereinheitlicht Supplier-Namen aus OCR/Text-Extraktion zu kanonischen Namen.
Unterstützt Aliases, Regex-Pattern und Fuzzy-Matching.
"""

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    import yaml
except ImportError:
    yaml = None

_LOGGER = logging.getLogger(__name__)


# Global LRU cache for text normalization (common operation)
@lru_cache(maxsize=512)
def _normalize_text_cached(text: str, umlauts_tuple: tuple, remove_chars: str, collapse_ws: bool) -> str:
    """
    Cached text normalization for performance.
    
    Args:
        text: Text to normalize
        umlauts_tuple: Tuple of (umlaut, replacement) pairs
        remove_chars: Characters to remove
        collapse_ws: Whether to collapse whitespace
    """
    if not text:
        return ""
    
    # Lowercase
    text = text.lower()
    
    # Umlaut-Ersetzungen
    for umlaut, replacement in umlauts_tuple:
        text = text.replace(umlaut, replacement)
    
    # Entferne Sonderzeichen
    for char in remove_chars:
        text = text.replace(char, "")
    
    # Whitespace kollabieren
    if collapse_ws:
        text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


@dataclass
class SupplierMatch:
    """Ergebnis der Supplier-Canonicalization."""
    canonical_name: str
    confidence: float
    matched_alias: str
    match_type: str  # "exact", "regex", "fuzzy", "context"


class SupplierCanonicalizer:
    """
    Canonicalizer für Lieferanten-Namen.
    
    Lädt Alias-Mappings aus Config und matched Supplier-Text gegen kanonische Namen.
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Args:
            config_path: Pfad zu supplier_aliases.yaml
        """
        self.config_path = config_path or (Path(__file__).parent.parent / "config" / "supplier_aliases.yaml")
        self.suppliers: Dict[str, Dict] = {}
        self.normalization_rules: Dict = {}
        self.confidence_thresholds: Dict = {}
        self._compiled_patterns: Dict[str, List[Tuple[re.Pattern, str]]] = {}  # Cache compiled regex
        # Initialize normalization params with defaults
        self._umlauts_tuple = ()
        self._remove_chars = ""
        self._collapse_ws = True
        self._load_config()
    
    def _load_config(self):
        """Lädt Supplier-Alias-Config."""
        if not self.config_path.exists():
            _LOGGER.warning(f"Config nicht gefunden: {self.config_path}")
            self._prepare_normalization_params()  # Initialize with defaults
            return
        
        if yaml is None:
            _LOGGER.warning("PyYAML nicht installiert")
            self._prepare_normalization_params()  # Initialize with defaults
            return
        
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            
            self.suppliers = config.get("suppliers", {})
            self.normalization_rules = config.get("normalization", {})
            self.confidence_thresholds = config.get("confidence", {})
            
            # Pre-compile regex patterns for performance
            self._compile_regex_patterns()
            
            # Prepare normalization parameters for caching
            self._prepare_normalization_params()
            
            # Clear the normalization cache when config changes
            _normalize_text_cached.cache_clear()
            
            _LOGGER.info(f"Geladen: {len(self.suppliers)} Supplier-Mappings")
        except Exception as exc:
            _LOGGER.error(f"Config-Ladefehler: {exc}")
            self._prepare_normalization_params()  # Initialize with defaults even on error
    
    def _compile_regex_patterns(self):
        """Pre-kompiliert alle Regex-Patterns für Performance."""
        self._compiled_patterns.clear()
        
        for supplier_key, supplier_config in self.suppliers.items():
            canonical = supplier_config.get("canonical", supplier_key)
            patterns = supplier_config.get("regex_patterns", [])
            
            compiled_list = []
            for pattern_str in patterns:
                try:
                    compiled_pattern = re.compile(pattern_str)
                    compiled_list.append((compiled_pattern, pattern_str))
                except re.error as exc:
                    _LOGGER.warning(f"Invalid regex pattern '{pattern_str}' for {supplier_key}: {exc}")
            
            if compiled_list:
                self._compiled_patterns[supplier_key] = compiled_list
    
    def _prepare_normalization_params(self):
        """Bereitet Normalization-Parameter für Caching vor."""
        # Convert umlauts dict to tuple for hashing
        umlauts = self.normalization_rules.get("umlauts", {})
        umlaut_pairs = []
        for umlaut, replacements in umlauts.items():
            if replacements:
                umlaut_pairs.append((umlaut, replacements[0]))
        
        self._umlauts_tuple = tuple(umlaut_pairs)
        self._remove_chars = self.normalization_rules.get("remove_chars", "")
        self._collapse_ws = self.normalization_rules.get("collapse_whitespace", True)
    
    def canonicalize_supplier(
        self,
        raw_supplier_text: str,
        full_ocr_text: Optional[str] = None
    ) -> Optional[SupplierMatch]:
        """
        Canonicalisiert Supplier-Name.
        
        Args:
            raw_supplier_text: Erkannter Supplier-Text (z.B. "Vergolst", "LKQ PV")
            full_ocr_text: Vollständiger OCR-Text (für Kontext-Prüfung)
        
        Returns:
            SupplierMatch oder None wenn kein Match
        """
        if not raw_supplier_text or not raw_supplier_text.strip():
            return None
        
        # Normalisiere Input
        normalized_input = self._normalize_text(raw_supplier_text)
        
        # 1. Exakte Alias-Matches
        match = self._check_exact_aliases(raw_supplier_text, normalized_input)
        if match:
            return match
        
        # 2. Regex-Pattern-Matches
        # Wichtig: Regex nur auf dem erkannten Supplier-Text anwenden.
        # Das Voll-OCR enthält oft Empfänger/Lieferanschrift und darf die
        # Canonicalisierung nicht auf einen anderen Supplier "umkippen".
        match = self._check_regex_patterns(raw_supplier_text)
        if match:
            return match
        
        # 3. Kontext-basierte Matches (z.B. "Hofmeister" nur wenn "Meincke" auch vorkommt)
        if full_ocr_text:
            match = self._check_context_patterns(raw_supplier_text, full_ocr_text)
            if match:
                return match
        
        return None
    
    def _check_exact_aliases(
        self,
        raw_text: str,
        normalized_text: str
    ) -> Optional[SupplierMatch]:
        """Prüft exakte String-Matches gegen Alias-Liste."""
        for supplier_key, supplier_config in self.suppliers.items():
            canonical = supplier_config.get("canonical", supplier_key)
            aliases = supplier_config.get("aliases", [])
            
            # Check original text
            for alias in aliases:
                # Case-insensitive exact match
                if alias.lower() == raw_text.lower():
                    confidence = self.confidence_thresholds.get("exact_match", 0.95)
                    return SupplierMatch(
                        canonical_name=canonical,
                        confidence=confidence,
                        matched_alias=alias,
                        match_type="exact"
                    )
                
                # Normalized match
                normalized_alias = self._normalize_text(alias)
                if normalized_alias == normalized_text:
                    confidence = self.confidence_thresholds.get("exact_match", 0.95)
                    return SupplierMatch(
                        canonical_name=canonical,
                        confidence=confidence,
                        matched_alias=alias,
                        match_type="exact"
                    )
                
                # Substring match (alias in raw_text oder umgekehrt)
                if alias.lower() in raw_text.lower() or raw_text.lower() in alias.lower():
                    # Nur wenn signifikanter Teil matched (mindestens 70% der kürzeren Länge)
                    min_len = min(len(alias), len(raw_text))
                    max_len = max(len(alias), len(raw_text))
                    if min_len / max_len >= 0.7:
                        confidence = self.confidence_thresholds.get("fuzzy_high", 0.85)
                        return SupplierMatch(
                            canonical_name=canonical,
                            confidence=confidence,
                            matched_alias=alias,
                            match_type="substring"
                        )
        
        return None
    
    def _check_regex_patterns(self, raw_text: str) -> Optional[SupplierMatch]:
        """Prüft Regex-Pattern-Matches mit pre-compiled patterns."""
        search_text = raw_text
        
        for supplier_key, compiled_list in self._compiled_patterns.items():
            canonical = self.suppliers[supplier_key].get("canonical", supplier_key)
            
            for pattern, pattern_str in compiled_list:
                match = pattern.search(search_text)
                
                if match:
                    confidence = self.confidence_thresholds.get("regex_match", 0.90)
                    matched_text = match.group(0)
                    return SupplierMatch(
                        canonical_name=canonical,
                        confidence=confidence,
                        matched_alias=matched_text,
                        match_type="regex"
                    )
        
        return None
    
    def _check_context_patterns(
        self,
        raw_text: str,
        full_text: str
    ) -> Optional[SupplierMatch]:
        """
        Prüft kontext-abhängige Matches.
        
        Beispiel: "Hofmeister" nur akzeptieren wenn "Meincke" auch im Text vorkommt.
        """
        normalized_full = self._normalize_text(full_text)
        
        for supplier_key, supplier_config in self.suppliers.items():
            canonical = supplier_config.get("canonical", supplier_key)
            context_patterns = supplier_config.get("context_patterns", {})
            
            if not context_patterns:
                continue
            
            # Prüfe ob raw_text einem der Trigger entspricht
            for trigger, required_context in context_patterns.items():
                if trigger.lower() in raw_text.lower():
                    # Prüfe ob mindestens ein Kontext-Pattern im full_text vorkommt
                    for context_keyword in required_context:
                        if context_keyword.lower() in normalized_full.lower():
                            confidence = self.confidence_thresholds.get("fuzzy_medium", 0.75)
                            return SupplierMatch(
                                canonical_name=canonical,
                                confidence=confidence,
                                matched_alias=trigger,
                                match_type="context"
                            )
        
        return None
    
    def _normalize_text(self, text: str) -> str:
        """
        Normalisiert Text für Matching (cached for performance).
        
        - Lowercase
        - Umlaut-Varianten
        - Entferne Sonderzeichen
        - Whitespace kollabieren
        """
        if not text:
            return ""
        
        # Use cached normalization for better performance
        return _normalize_text_cached(
            text,
            self._umlauts_tuple,
            self._remove_chars,
            self._collapse_ws
        )
    
    def get_canonical_name(self, supplier_key: str) -> Optional[str]:
        """Gibt kanonischen Namen für Supplier-Key zurück."""
        supplier_config = self.suppliers.get(supplier_key)
        if supplier_config:
            return supplier_config.get("canonical", supplier_key)
        return None
    
    def list_all_canonical_names(self) -> List[str]:
        """Gibt alle kanonischen Supplier-Namen zurück."""
        return [
            config.get("canonical", key)
            for key, config in self.suppliers.items()
        ]


# Globale Instanz (lazy loading)
_CANONICALIZER: Optional[SupplierCanonicalizer] = None


def get_supplier_canonicalizer() -> SupplierCanonicalizer:
    """Liefert globale SupplierCanonicalizer-Instanz."""
    global _CANONICALIZER
    if _CANONICALIZER is None:
        _CANONICALIZER = SupplierCanonicalizer()
    return _CANONICALIZER


def canonicalize_supplier(
    raw_supplier_text: str,
    full_ocr_text: Optional[str] = None
) -> Optional[SupplierMatch]:
    """
    Convenience-Funktion: Canonicalisiert Supplier-Name.
    
    Args:
        raw_supplier_text: Erkannter Supplier-Text
        full_ocr_text: Vollständiger OCR-Text (optional, für Kontext)
    
    Returns:
        SupplierMatch oder None
    """
    canonicalizer = get_supplier_canonicalizer()
    return canonicalizer.canonicalize_supplier(raw_supplier_text, full_ocr_text)
