import pytest


def test_doctype_lieferschein_not_rechnung_due_to_footer_iban():
    from core.doctype_classifier import classify_doc_type

    text = """LIEFERSCHEIN
Lieferscheinnr: LS-12345
Lieferdatum: 10.01.2026

Position 1: Test

Zahlungsinformationen
IBAN: DE12 3456 7890 1234 5678 90
BIC: ABCDDEFFXXX
"""

    res = classify_doc_type(text, supplier_canonical=None)
    assert res.doc_type == "LIEFERSCHEIN"
    assert res.confidence >= 0.60


def test_uebernahmeschein_classified_and_ksr_detected():
    from core.doctype_classifier import classify_doc_type
    from core.extractor import detect_supplier_detailed

    text = """ÜBERNAHMESCHEIN
Entsorgungsnachweis-Nummer: EN-2026-0001

Abfallerzeuger (Name, Anschrift)
Franz Bracht Kran-Vermietung GmbH

Beförderer (Name, Anschrift)
KS-Logistic GmbH & Co. KG
Irgendwo 12

Abfallentsorger (Name, Anschrift)
KS-Recycling GmbH & Co. KG
Sonstwo 34

Empfänger / Lieferung an
WM SE
"""

    dt = classify_doc_type(text, supplier_canonical=None)
    assert dt.doc_type == "ÜBERNAHMESCHEIN"
    assert dt.confidence >= 0.60

    supplier, conf, source, guess, cands = detect_supplier_detailed(text, doc_type_hint="ÜBERNAHMESCHEIN")
    assert supplier == "KSR"
    assert conf >= 0.80
    assert cands is not None


def test_liebherr_wins_over_recipient_franz_bracht():
    from core.extractor import detect_supplier_detailed
    from core.doctype_classifier import classify_doc_type

    text = """Liebherr-Werk Ehingen GmbH
Werk Ehingen

Empfänger:
Franz Bracht Kran-Vermietung GmbH
Lieferadresse:
Irgendwo 1

LIEFERSCHEIN
Pos 1: Test
"""

    supplier, conf, source, guess, cands = detect_supplier_detailed(text)
    assert supplier.lower().startswith("liebherr")
    assert conf >= 0.50

    dt = classify_doc_type(text, supplier_canonical=supplier)
    assert dt.doc_type == "LIEFERSCHEIN"


def test_dekra_report_markers_are_detected_without_explicit_branding():
    from core.extractor import detect_supplier_detailed
    from core.doctype_classifier import classify_doc_type

    text = """(6) EZ-Kl. 16 EKR SELBSTF.ARBEITSMASCH.
EZ 25.04.2022
Berichts-Nr. F087046002827
vom 07.04.2026, 09:34
nächste HU fällig April 2027
Kennz.: SO-FB1494
"""

    supplier, conf, source, guess, cands = detect_supplier_detailed(text)
    assert supplier == "Dekra"
    assert conf >= 0.80
    assert source in {"explicit_dekra", "keywords", "db"}
    assert cands is not None

    dt = classify_doc_type(text, supplier_canonical=supplier)
    assert dt.doc_type == "PRÜFBERICHT"
    assert dt.confidence >= 0.80
