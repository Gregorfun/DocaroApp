from date_parser import extract_date_from_text


def test_dekra_report_date_beats_ez_registration_date():
    text = """
    (6) EZ-Kl. 16 EKR SELBSTF.ARBEITSMASCH.
    EZ 25.04.2022
    Berichts-Nr. F087046002827
    vom 07.04.2026, 09:34
    nächste HU fällig April 2027
    """

    iso, reason = extract_date_from_text(text)

    assert iso == "2026-04-07"
    assert reason == "dekra_report_date"


def test_dekra_report_date_varies_independently_from_ez_date():
    text = """
    DEKRA Automobil
    Erstzulassung 12.08.2020
    Berichts-Nr. F087046099999
    vom 03.02.2026, 10:15
    Dat. letzt. HU 04/2024
    """

    iso, reason = extract_date_from_text(text)

    assert iso == "2026-02-03"
    assert reason == "dekra_report_date"


def test_dekra_report_date_same_line_as_report_number():
    text = """
    Untersuchungsbericht
    EZ 14.11.2021
    Berichts-Nr. F087046012345 vom 18.03.2026
    """

    iso, reason = extract_date_from_text(text)

    assert iso == "2026-03-18"
    assert reason == "dekra_report_date"
