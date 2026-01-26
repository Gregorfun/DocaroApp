"""
Tests für Dokumenttyp-Klassifikation (DocType Classifier).
"""

import logging
from core.doctype_classifier import DocTypeClassifier, classify_doc_type

_LOGGER = logging.getLogger(__name__)


def test_rechnung():
    """Test für RECHNUNG-Klassifikation."""
    text = """
    Rechnung
    Rechnungsnummer: INV-12345
    Rechnungsdatum: 15.01.2026
    
    IBAN: DE89370400440532013000
    BIC: COBADEFFXXX
    Zahlungsziel: 14 Tage
    
    Netto: 850,00 EUR
    Mehrwertsteuer 19%: 161,50 EUR
    Brutto: 1.011,50 EUR
    """
    result = classify_doc_type(text)
    print(f"✓ RECHNUNG: doc_type={result.doc_type}, confidence={result.confidence:.2f}, evidence={result.evidence}")
    assert result.doc_type == "RECHNUNG", f"Expected RECHNUNG, got {result.doc_type}"
    assert result.confidence >= 0.70, f"Confidence too low: {result.confidence}"


def test_lieferschein():
    """Test für LIEFERSCHEIN-Klassifikation."""
    text = """
    Lieferschein
    Lieferschein-Nr: LS-9999-2026
    Lieferdatum: 20.01.2026
    
    Versandadresse:
    Musterfirma GmbH
    Musterstraße 123
    12345 Musterstadt
    
    Position | Artikel | Menge
    1 | Hydraulikzylinder HZ-500 | 2 Stück
    2 | Dichtungssatz DS-100 | 5 Stück
    
    Ware wurde vollständig geliefert.
    """
    result = classify_doc_type(text)
    print(f"✓ LIEFERSCHEIN: doc_type={result.doc_type}, confidence={result.confidence:.2f}, evidence={result.evidence}")
    assert result.doc_type == "LIEFERSCHEIN", f"Expected LIEFERSCHEIN, got {result.doc_type}"
    assert result.confidence >= 0.70, f"Confidence too low: {result.confidence}"


def test_uebernahmeschein():
    """Test für ÜBERNAHMESCHEIN-Klassifikation."""
    text = """
    ÜBERNAHMESCHEIN
    Entsorgungsnachweis
    
    Übernahmeschein-Nr: UE-2026-001
    Datum: 22.01.2026
    
    Abfallart: Bauschutt gemischt
    AVV-Schlüssel: 17 09 04
    
    Container: 10m³ Mulde
    Gewicht: 8.500 kg (8,5 Tonnen)
    
    Standort: Baustelle Musterweg 45, 67890 Beispielstadt
    Abholung durch: Entsorgung Müller GmbH
    
    Die Ware wurde ordnungsgemäß entsorgt.
    """
    result = classify_doc_type(text)
    print(f"✓ ÜBERNAHMESCHEIN: doc_type={result.doc_type}, confidence={result.confidence:.2f}, evidence={result.evidence}")
    assert result.doc_type == "ÜBERNAHMESCHEIN", f"Expected ÜBERNAHMESCHEIN, got {result.doc_type}"
    assert result.confidence >= 0.70, f"Confidence too low: {result.confidence}"


def test_kommissionierliste():
    """Test für KOMMISSIONIERLISTE-Klassifikation."""
    text = """
    KOMMISSIONIERLISTE (pro Auftrag)
    
    Picking List
    Auftrag: 7777-2026
    Datum: 18.01.2026
    
    Lager: Hauptlager A
    
    Pos | Artikel | Lagerplatz | Regal | Fach | Menge | Status
    1 | Schraube M12 | A-01 | R12 | F3 | 50 Stk | [ ] entnommen
    2 | Mutter M12 | A-02 | R12 | F4 | 50 Stk | [ ] entnommen
    3 | Unterlegscheibe M12 | A-03 | R13 | F1 | 100 Stk | [ ] entnommen
    
    Kommissionierer: _____________
    Bereitstellung erfolgt bis: 19.01.2026, 10:00 Uhr
    """
    result = classify_doc_type(text)
    print(f"✓ KOMMISSIONIERLISTE: doc_type={result.doc_type}, confidence={result.confidence:.2f}, evidence={result.evidence}")
    assert result.doc_type == "KOMMISSIONIERLISTE", f"Expected KOMMISSIONIERLISTE, got {result.doc_type}"
    assert result.confidence >= 0.70, f"Confidence too low: {result.confidence}"


def test_sonstiges():
    """Test für SONSTIGES-Klassifikation (unklarer Dokumenttyp)."""
    text = """
    Random Document
    
    This is a document without specific keywords.
    It could be anything - a letter, a report, or something else.
    
    Lorem ipsum dolor sit amet.
    No clear indication of document type.
    
    Some random text here.
    No invoice, delivery note, or disposal certificate keywords.
    """
    result = classify_doc_type(text)
    print(f"✓ SONSTIGES: doc_type={result.doc_type}, confidence={result.confidence:.2f}, evidence={result.evidence}")
    assert result.doc_type == "SONSTIGES", f"Expected SONSTIGES, got {result.doc_type}"
    # SONSTIGES kann niedrige confidence haben


def test_rechnung_mit_supplier_hint():
    """Test für RECHNUNG mit Supplier-Hint (Manitowoc)."""
    text = """
    Manitowoc Cranes
    
    Invoice Date: 2026-01-10
    Invoice No: MAN-2026-0042
    
    IBAN: DE12345678901234567890
    Payment Terms: 30 days
    
    Net Amount: 15.000,00 EUR
    VAT 19%: 2.850,00 EUR
    Gross Total: 17.850,00 EUR
    """
    # Ohne supplier hint
    result_no_hint = classify_doc_type(text, supplier_canonical=None)
    print(f"✓ RECHNUNG (no hint): confidence={result_no_hint.confidence:.2f}")
    
    # Mit supplier hint
    result_with_hint = classify_doc_type(text, supplier_canonical="Manitowoc")
    print(f"✓ RECHNUNG (Manitowoc hint): confidence={result_with_hint.confidence:.2f}")
    
    assert result_with_hint.doc_type == "RECHNUNG"
    assert result_with_hint.confidence >= result_no_hint.confidence, "Hint sollte Confidence erhöhen"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== DocType Classifier Tests ===\n")
    
    try:
        test_rechnung()
        test_lieferschein()
        test_uebernahmeschein()
        test_kommissionierliste()
        test_sonstiges()
        test_rechnung_mit_supplier_hint()
        
        print("\n✅ Alle Tests erfolgreich!\n")
    except AssertionError as e:
        print(f"\n❌ Test fehlgeschlagen: {e}\n")
        raise
