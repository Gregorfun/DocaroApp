"""
Supplier Fingerprinting für robuste Lieferantenerkennung bei schlechtem OCR.
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_LOGGER = logging.getLogger(__name__)


@dataclass
class SupplierFingerprint:
    """Eindeutiger Fingerprint eines Lieferanten."""
    name: str
    keywords: Set[str] = field(default_factory=set)
    patterns: List[str] = field(default_factory=list)
    char_signature: str = ""
    hash_signature: str = ""
    aliases: List[str] = field(default_factory=list)
    
    def calculate_hash(self) -> str:
        """Berechnet Hash aus Keywords + Patterns."""
        text = "|".join(sorted(self.keywords)) + "|" + "|".join(sorted(self.patterns))
        return hashlib.md5(text.encode()).hexdigest()[:8]


class SupplierMatcher:
    """
    Robuste Lieferanten-Matching-Engine.
    
    Strategien:
    1. Exakte Übereinstimmung (normalisiert)
    2. Fuzzy-Match mit Levenshtein
    3. Keyword-basiert (OCR-fehlertolerant)
    4. Pattern-basiert (Regex)
    5. Character-Signature (n-gram)
    """
    
    def __init__(self, suppliers_db_path: Path):
        self.db_path = suppliers_db_path
        self.fingerprints: Dict[str, SupplierFingerprint] = {}
        self._load_suppliers()
    
    def _load_suppliers(self):
        """Lädt Lieferanten und erstellt Fingerprints."""
        import json
        if not self.db_path.exists():
            _LOGGER.warning(f"Suppliers DB nicht gefunden: {self.db_path}")
            return
        
        with open(self.db_path, encoding="utf-8") as f:
            data = json.load(f)
        
        for supplier in data.get("suppliers", []):
            name = supplier["name"]
            fp = SupplierFingerprint(name=name)
            fp.aliases = supplier.get("aliases", [])
            
            # Keywords extrahieren
            fp.keywords = self._extract_keywords(name)
            for alias in fp.aliases:
                fp.keywords.update(self._extract_keywords(alias))
            
            # Patterns erstellen
            fp.patterns = self._create_patterns(name)
            
            # Character-Signature
            fp.char_signature = self._char_signature(name)
            fp.hash_signature = fp.calculate_hash()
            
            self.fingerprints[name] = fp
        
        _LOGGER.info(f"Geladen: {len(self.fingerprints)} Lieferanten-Fingerprints")
    
    def _extract_keywords(self, text: str) -> Set[str]:
        """Extrahiert relevante Keywords aus Text."""
        text = self._normalize(text)
        words = re.findall(r'\b\w{3,}\b', text)
        return {w.lower() for w in words if len(w) >= 3}
    
    def _create_patterns(self, name: str) -> List[str]:
        """Erstellt Regex-Patterns für OCR-Fehlertoleranz."""
        patterns = []
        norm = self._normalize(name)
        
        # Pattern 1: Exakt (case-insensitive)
        patterns.append(re.escape(norm))
        
        # Pattern 2: Mit optionalen Sonderzeichen
        fuzzy = re.sub(r'\s+', r'\\s*', re.escape(norm))
        patterns.append(fuzzy)
        
        # Pattern 3: Character-Class für häufige OCR-Fehler
        ocr_map = {
            'o': '[o0]',
            'i': '[i1l]',
            's': '[s5]',
            'e': '[e3]',
            'a': '[a4]',
            'b': '[b8]',
        }
        ocr_pattern = norm
        for char, repl in ocr_map.items():
            ocr_pattern = ocr_pattern.replace(char, repl)
        patterns.append(ocr_pattern)
        
        return patterns
    
    def _normalize(self, text: str) -> str:
        """Normalisiert Text: lowercase, whitespace."""
        text = text.lower().strip()
        text = re.sub(r'[^\w\säöüß]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text
    
    def _char_signature(self, text: str) -> str:
        """Character-Signature (trigram)."""
        norm = self._normalize(text).replace(' ', '')
        trigrams = [norm[i:i+3] for i in range(len(norm)-2)]
        return '|'.join(sorted(set(trigrams))[:10])
    
    def match(self, ocr_text: str, top_n: int = 3) -> List[Tuple[str, float, str]]:
        """
        Matched OCR-Text gegen alle Lieferanten.
        
        Returns:
            List[(supplier_name, confidence, reason)]
        """
        ocr_norm = self._normalize(ocr_text)
        ocr_keywords = self._extract_keywords(ocr_text)
        ocr_sig = self._char_signature(ocr_text)
        
        scores = []
        
        for name, fp in self.fingerprints.items():
            score = 0.0
            reasons = []
            
            # 1. Exakte Übereinstimmung
            if name.lower() in ocr_norm:
                score += 1.0
                reasons.append("exact_match")
            
            # 2. Alias-Match
            for alias in fp.aliases:
                if self._normalize(alias) in ocr_norm:
                    score += 0.95
                    reasons.append("alias_match")
                    break
            
            # 3. Pattern-Match
            for pattern in fp.patterns:
                if re.search(pattern, ocr_norm, re.IGNORECASE):
                    score += 0.8
                    reasons.append("pattern_match")
                    break
            
            # 4. Keyword-Overlap
            overlap = len(fp.keywords & ocr_keywords)
            if overlap > 0 and len(fp.keywords) > 0:
                keyword_score = overlap / len(fp.keywords)
                score += keyword_score * 0.7
                reasons.append(f"keywords={overlap}/{len(fp.keywords)}")
            
            # 5. Character-Signature-Similarity
            sig_sim = self._signature_similarity(fp.char_signature, ocr_sig)
            if sig_sim > 0.3:
                score += sig_sim * 0.5
                reasons.append(f"sig_sim={sig_sim:.2f}")
            
            if score > 0:
                scores.append((name, score, "; ".join(reasons)))
        
        # Normalisiere Scores
        scores.sort(key=lambda x: x[1], reverse=True)
        if scores and scores[0][1] > 1.0:
            max_score = scores[0][1]
            scores = [(n, min(s/max_score, 1.0), r) for n, s, r in scores]
        
        return scores[:top_n]
    
    def _signature_similarity(self, sig1: str, sig2: str) -> float:
        """Berechnet Ähnlichkeit zwischen Char-Signatures."""
        if not sig1 or not sig2:
            return 0.0
        set1 = set(sig1.split('|'))
        set2 = set(sig2.split('|'))
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0
    
    def add_supplier(self, name: str, aliases: Optional[List[str]] = None):
        """Fügt neuen Lieferanten hinzu und aktualisiert DB."""
        import json
        
        aliases = aliases or []
        fp = SupplierFingerprint(name=name, aliases=aliases)
        fp.keywords = self._extract_keywords(name)
        for alias in aliases:
            fp.keywords.update(self._extract_keywords(alias))
        fp.patterns = self._create_patterns(name)
        fp.char_signature = self._char_signature(name)
        fp.hash_signature = fp.calculate_hash()
        
        self.fingerprints[name] = fp
        
        # Aktualisiere DB
        with open(self.db_path, encoding="utf-8") as f:
            data = json.load(f)
        
        data.setdefault("suppliers", []).append({
            "name": name,
            "aliases": aliases,
            "created_at": datetime.now().isoformat()
        })
        
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        _LOGGER.info(f"Neuer Lieferant hinzugefügt: {name}")


from datetime import datetime
