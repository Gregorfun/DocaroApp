from __future__ import annotations

from core.doc_number_extractor import extract_doc_number
from core.doctype_classifier import classify_doc_type


def test_doctype_classifier_detects_lschein_header_as_lieferschein():
    text = """L-Schein
L Schein Nr: LS-2026-4455
Lieferdatum: 14.01.2026
Warenempfänger: Beispiel GmbH
"""

    result = classify_doc_type(text)

    assert result.doc_type == "LIEFERSCHEIN"
    assert result.confidence >= 0.60


def test_doc_number_extractor_uses_doc_type_override_for_tadano_delivery_note():
    text = """Tadano Faun GmbH
Order ID: 4501234567
Lieferschein-Nr: LS-2026-7788
Shipment: 0088
"""

    result = extract_doc_number(text, supplier_canonical="Tadano", doc_type="LIEFERSCHEIN")

    assert result.doc_number == "LS-2026-7788"
    assert result.source_field == "Lieferschein-Nr"
    assert result.confidence == "high"


def test_doc_number_extractor_matches_l_schein_variant_for_known_supplier():
    text = """Herbrand Fichtenhain
L Schein : 47110815
Auftragsnummer: 882244
"""

    result = extract_doc_number(text, supplier_canonical="Herbrand Fichtenhain", doc_type="LIEFERSCHEIN")

    assert result.doc_number == "47110815"
    assert result.source_field == "L-Schein"
    assert result.confidence == "high"