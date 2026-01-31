"""
Supplier-spezifische Dokumentnummern-Extraktion.

Extrahiert Beleg-/Auftrags-/Lieferschein-/Rechnungsnummern anhand supplier-spezifischer Feldnamen.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None

_LOGGER = logging.getLogger(__name__)


@dataclass
class DocNumberResult:
    """Ergebnis der Dokumentnummern-Extraktion."""
    doc_number: Optional[str]
    source_field: Optional[str]
    confidence: str  # "high", "medium", "low", "none"


class DocNumberExtractor:
    """Extrahiert Dokumentnummern supplier-spezifisch."""
    
    # Pre-compile regex patterns at class level for performance
    _DOC_NUMBER_PATTERNS = [
        re.compile(r'\b([A-Z0-9][-A-Z0-9/]{2,})\b', re.IGNORECASE),  # Alphanumerisch mit Sonderzeichen
        re.compile(r'\b(\d{6,})\b'),  # Rein numerisch, mindestens 6 Ziffern
    ]
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Args:
            config_path: Pfad zu supplier_field_aliases.yaml
        """
        self.config_path = config_path or (Path(__file__).parent.parent / "config" / "supplier_field_aliases.yaml")
        self.supplier_mappings: Dict[str, Dict] = {}
        self.fallback_keywords: Dict[str, List[str]] = {}
        self._load_config()
    
    def _load_config(self):
        """Lädt Supplier-Mappings aus YAML-Config."""
        if not self.config_path.exists():
            _LOGGER.warning(f"Config nicht gefunden: {self.config_path}")
            return
        
        if yaml is None:
            _LOGGER.warning("PyYAML nicht installiert, nutze Fallback")
            return
        
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            
            self.supplier_mappings = config.get("suppliers", {})
            self.fallback_keywords = config.get("fallback_keywords", {})
            _LOGGER.info(f"Geladen: {len(self.supplier_mappings)} Supplier-Mappings")
        except Exception as exc:
            _LOGGER.error(f"Config-Ladefehler: {exc}")
    
    def extract_doc_number(
        self,
        text: str,
        supplier_canonical: Optional[str] = None,
        doc_type: Optional[str] = None
    ) -> DocNumberResult:
        """
        Extrahiert Dokumentnummer aus Text.
        
        Args:
            text: OCR/Text-Extraktion
            supplier_canonical: Kanonischer Supplier-Name (z.B. "WM", "OK", "FUCHS")
            doc_type: Optional Dokumenttyp ("Lieferschein", "Rechnung", etc.)
        
        Returns:
            DocNumberResult mit doc_number, source_field, confidence
        """
        if not text or not text.strip():
            return DocNumberResult(None, None, "none")
        
        # 1) Supplier-spezifische Extraktion
        if supplier_canonical and supplier_canonical in self.supplier_mappings:
            result = self._extract_supplier_specific(text, supplier_canonical, doc_type)
            if result.doc_number:
                return result
        
        # 2) Fallback: generische Keywords
        result = self._extract_fallback(text, doc_type)
        if result.doc_number:
            return result
        
        return DocNumberResult(None, None, "none")
    
    def _extract_supplier_specific(
        self,
        text: str,
        supplier_canonical: str,
        doc_type: Optional[str]
    ) -> DocNumberResult:
        """Extrahiert Nummer mit supplier-spezifischen Feldnamen."""
        mapping = self.supplier_mappings.get(supplier_canonical, {})
        
        # Primäre Felder - mit DocType-Priorisierung
        primary_fields = mapping.get("doc_number_fields", [])
        
        # Reorder fields basierend auf doc_type
        if doc_type:
            primary_fields = self._reorder_fields_by_doctype(primary_fields, doc_type)
        
        result = self._search_fields(text, primary_fields)
        if result.doc_number:
            result.confidence = "high"
            return result
        
        # Sekundäre Felder (falls vorhanden)
        secondary_fields = mapping.get("secondary_fields", [])
        if secondary_fields:
            if doc_type:
                secondary_fields = self._reorder_fields_by_doctype(secondary_fields, doc_type)
            result = self._search_fields(text, secondary_fields)
            if result.doc_number:
                result.confidence = "medium"
                return result
        
        return DocNumberResult(None, None, "none")
    
    def _reorder_fields_by_doctype(self, fields: List[str], doc_type: str) -> List[str]:
        """
        Priorisiert Felder basierend auf Dokumenttyp.
        
        Beispiel:
        - RECHNUNG → "Rechnungsnummer" zuerst
        - LIEFERSCHEIN → "Lieferschein-Nr" zuerst
        - ÜBERNAHMESCHEIN → "Übernahmeschein-Nr" zuerst
        """
        if not fields:
            return fields
        
        doc_type_upper = doc_type.upper()
        priority_keywords = []
        
        if doc_type_upper == "RECHNUNG":
            priority_keywords = ["rechnung", "invoice", "re-"]
        elif doc_type_upper == "LIEFERSCHEIN":
            priority_keywords = ["lieferschein", "delivery", "ls-"]
        elif doc_type_upper == "ÜBERNAHMESCHEIN":
            priority_keywords = ["übernahmeschein", "uebernahmeschein", "entsorgungs"]
        elif doc_type_upper == "KOMMISSIONIERLISTE":
            priority_keywords = ["kommission", "picking", "auftrag"]
        else:
            return fields  # keine Änderung
        
        # Sortiere: Felder mit priority_keywords zuerst
        prioritized = []
        others = []
        
        for field in fields:
            field_lower = field.lower()
            if any(kw in field_lower for kw in priority_keywords):
                prioritized.append(field)
            else:
                others.append(field)
        
        return prioritized + others
    
    def _extract_fallback(
        self,
        text: str,
        doc_type: Optional[str]
    ) -> DocNumberResult:
        """Fallback-Extraktion mit generischen Keywords."""
        # Wähle Keywords basierend auf doc_type
        keywords = []
        if doc_type and doc_type.lower() in self.fallback_keywords:
            keywords = self.fallback_keywords[doc_type.lower()]
        else:
            # Alle Fallback-Keywords durchsuchen
            for kw_list in self.fallback_keywords.values():
                keywords.extend(kw_list)
        
        if not keywords:
            # Hardcoded Fallback wenn keine Config
            keywords = [
                "Lieferschein-Nr", "Lieferscheinnr", "Lieferschein Nr",
                "Rechnungsnummer", "Rechnung Nr", "RE-",
                "Auftragsnummer", "Auftrag-Nr", "Auftrag Nr",
                "Belegnummer", "Beleg-Nr", "Beleg Nr"
            ]
        
        result = self._search_fields(text, keywords)
        if result.doc_number:
            result.confidence = "medium"
        return result
    
    def _search_fields(
        self,
        text: str,
        field_names: List[str]
    ) -> DocNumberResult:
        """
        Sucht nach Feldnamen und extrahiert Wert.
        
        Strategie:
        1. Suche Feldname in Zeile (case-insensitive)
        2. Extrahiere Wert nach Feldname (gleiche Zeile oder nächste 1-2 Zeilen)
        3. Validiere Wert (keine Datumsangaben, PLZ, IBAN, etc.)
        """
        lines = text.splitlines()
        
        for field in field_names:
            field_lower = field.lower()
            
            for idx, line in enumerate(lines):
                line_lower = line.lower()
                
                # Feldname in dieser Zeile?
                if field_lower not in line_lower:
                    continue
                
                # WICHTIG: Filtere Datums-Kontext
                # Wenn "datum" direkt vor/nach dem Feldnamen steht, ignoriere diese Zeile
                datum_pattern = r'datum[:\s-]*' + re.escape(field_lower) + r'|' + re.escape(field_lower) + r'[:\s-]*datum'
                if re.search(datum_pattern, line_lower):
                    continue
                
                # 1) Gleiche Zeile: suche Wert nach Feldname
                # Finde Position des Feldnamens
                pos = line_lower.find(field_lower)
                if pos >= 0:
                    # Extrahiere Text nach dem Feldnamen
                    tail = line[pos + len(field):]
                    
                    # Entferne führende Doppelpunkte/Leerzeichen
                    tail = tail.lstrip(': \t')
                    
                    number = self._extract_number_from_text(tail)
                    if number:
                        return DocNumberResult(number, field, "high")
                
                # 2) Nächste 1-2 Zeilen
                for j in range(idx + 1, min(idx + 3, len(lines))):
                    number = self._extract_number_from_text(lines[j])
                    if number:
                        return DocNumberResult(number, field, "high")
        
        return DocNumberResult(None, None, "none")
    
    def _extract_number_from_text(self, text: str) -> Optional[str]:
        """
        Extrahiert plausible Dokumentnummer aus Text.
        
        Unterstützt:
        - Alphanumerisch: D018017955, LS20250982
        - Mit Bindestrichen: RE-2025-90879
        - Mit Slash: RE-2025/90879
        - Rein numerisch: 226267189, 3814300
        
        Filtert:
        - Datumsangaben (dd.mm.yyyy, yyyy-mm-dd)
        - PLZ (5-stellige reine Zahlen ohne Kontext)
        - IBAN, Telefonnummern, Beträge
        """
        # Use pre-compiled patterns for better performance
        for pattern in self._DOC_NUMBER_PATTERNS:
            matches = pattern.finditer(text)
            
            for match in matches:
                candidate = match.group(1).strip()
                
                # Bereinige
                candidate = self._clean_number(candidate)
                
                if self._is_plausible_doc_number(candidate):
                    return candidate
        
        return None
    
    def _clean_number(self, value: str) -> str:
        """Bereinigt Dokumentnummer."""
        if not value:
            return ""
        # Entferne trailing Doppelpunkte, Punkte, Kommas
        value = value.strip().strip(".:;,")
        return value
    
    def _is_plausible_doc_number(self, token: str) -> bool:
        """
        Prüft ob Token eine plausible Dokumentnummer ist.
        
        Filtert:
        - Datumswerte: dd.mm.yyyy, yyyy-mm-dd, dd/mm/yyyy
        - PLZ: 5-stellige reine Zahlen (ohne Keyword-Kontext nicht akzeptiert)
        - IBAN: DE12345...
        - Telefonnummern: +49...
        - Beträge: 1.234,56
        """
        if not token or len(token) < 4:
            return False
        
        # Filter: Datumswerte
        date_pattern = r'\b(\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b'
        if re.search(date_pattern, token):
            return False
        
        # Filter: IBAN
        iban_pattern = r'\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b'
        if re.match(iban_pattern, token):
            return False
        
        # Filter: Telefonnummern (muss Leerzeichen oder Sonderzeichen enthalten)
        # Nur filtern wenn + am Anfang oder Leerzeichen/Klammern/Bindestriche im Text
        if token.startswith('+') or any(ch in token for ch in ' ()/-'):
            phone_pattern = r'^\+?\d[\d\s/()\-]{4,}\d$'
            if re.match(phone_pattern, token) and any(ch in token for ch in ' ()-/'):
                return False
        
        # Filter: Beträge (z.B. 1.234,56 oder 1,234.56)
        amount_pattern = r'^\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})$'
        if re.match(amount_pattern, token):
            return False
        
        # Filter: 5-stellige reine Zahlen (PLZ) - nur im Kontext ohne Feldname
        # Im Kontext mit Feldname (aus _search_fields) sind 5-stellige Zahlen OK
        # Dieser Filter gilt nur für generische Suche ohne Feldname
        # Da wir hier aus _search_fields kommen, erlauben wir 5-stellige Zahlen
        
        # Muss mindestens eine Ziffer enthalten
        if not any(ch.isdigit() for ch in token):
            return False
        
        return True


def generate_fallback_identifier(text: str) -> str:
    """
    Generiert stabilen Hash für 'ohneNr'-Fallback.
    
    Args:
        text: OCR/Text-Extraktion
    
    Returns:
        6-stelliger Hash (z.B. "A1B2C3")
    """
    if not text:
        text = ""
    hash_obj = hashlib.sha1(text.encode('utf-8', errors='ignore'))
    return hash_obj.hexdigest()[:6].upper()


# Globale Instanz (lazy loading)
_EXTRACTOR: Optional[DocNumberExtractor] = None


def get_doc_number_extractor() -> DocNumberExtractor:
    """Liefert globale DocNumberExtractor-Instanz."""
    global _EXTRACTOR
    if _EXTRACTOR is None:
        _EXTRACTOR = DocNumberExtractor()
    return _EXTRACTOR


def extract_doc_number(
    text: str,
    supplier_canonical: Optional[str] = None,
    doc_type: Optional[str] = None
) -> DocNumberResult:
    """
    Convenience-Funktion: Extrahiert Dokumentnummer.
    
    Args:
        text: OCR/Text-Extraktion
        supplier_canonical: Kanonischer Supplier-Name (z.B. "WM", "OK")
        doc_type: Optional Dokumenttyp
    
    Returns:
        DocNumberResult
    """
    extractor = get_doc_number_extractor()
    return extractor.extract_doc_number(text, supplier_canonical, doc_type)
