def test_wfi_detected_from_letterhead_not_recipient():
    from core.extractor import detect_supplier_detailed

    text = """Wireless Funk- und Informationstechnik GmbH
www.wfi-funktechnik.de
info@wfi-funktechnik.de

Empfänger / Lieferanschrift
Franz Bracht Kran-Vermietung GmbH
Bruchfeld 91
47809 Krefeld

LIEFERSCHEIN
Pos 1: Test
"""

    supplier, conf, source, guess, cands = detect_supplier_detailed(text)
    assert supplier == "WFI Funktechnik GmbH"
    assert conf >= 0.80


def test_ortjohann_kraft_detected_from_address_markers():
    from core.extractor import detect_supplier_detailed

    text = """Ortjohann + Kraft Werkzeug- und Maschinenhandel GmbH
Siemensstraße 6
33397 Rietberg

An:
Franz Bracht Kran-Vermietung GmbH

RECHNUNG
Pos 1: Test
"""

    supplier, conf, source, guess, cands = detect_supplier_detailed(text)
    assert supplier == "Orjohann Kraft"
    assert conf >= 0.80


def test_franz_bracht_is_never_supplier_even_if_prominent():
    from core.extractor import detect_supplier_detailed

    text = """Franz Bracht Kran-Vermietung GmbH
Bruchfeld 91
47809 Krefeld

LIEFERSCHEIN
Pos 1: Test
"""

    supplier, conf, source, guess, cands = detect_supplier_detailed(text)
    assert supplier.lower() != "franz bracht"
