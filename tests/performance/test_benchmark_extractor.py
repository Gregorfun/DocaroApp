from __future__ import annotations

import pytest

from core.extractor import extract_document_numbers

pytest.importorskip("pytest_benchmark")

SAMPLE_TEXT = """
Lieferschein-Nr: 8012994793
Lieferdatum: 20.11.2025
Bestellnummer: PO-1245-7788
Warenausgang: 20-11-2025
"""


def test_benchmark_extract_document_numbers(benchmark) -> None:
    result = benchmark(extract_document_numbers, SAMPLE_TEXT)
    assert (result.get("delivery_note_no") or result.get("order_no")) is not None
    assert result["confidence"] in {"high", "low"}
