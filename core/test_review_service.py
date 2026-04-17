"""
Unit Tests für Review Service.
"""

import json
from pathlib import Path

import pytest

from core.review_service import (
    DocumentStatus,
    ReviewReasonCode,
    ReviewSettings,
    decide_review_status,
    finalize_document,
    save_correction,
    save_ground_truth_sample,
    build_final_filename,
)


# --- Test Fixtures ---


@pytest.fixture
def mock_settings():
    """Standard Review Settings."""
    return ReviewSettings(
        gate_supplier_min=0.80,
        gate_date_min=0.80,
        gate_doc_type_min=0.70,
        gate_doc_number_min=0.80,
        auto_finalize_enabled=False,
        autosort_enabled=False,
        autosort_base_dir=Path("."),
    )


@pytest.fixture
def high_confidence_extraction():
    """Extraction mit hohen Confidences (alle Gates bestanden)."""
    return {
        "supplier_canonical": "Musterfirma GmbH",
        "supplier_confidence": 0.95,
        "date": "2025-01-15",
        "date_confidence": 0.92,
        "doc_type": "Rechnung",
        "doc_type_confidence": 0.88,
        "doc_number": "RE-2025-00123",
        "doc_number_confidence": 0.85,
    }


@pytest.fixture
def low_confidence_extraction():
    """Extraction mit niedrigen Confidences (mehrere Gates failed)."""
    return {
        "supplier_canonical": "Unklar GmbH",
        "supplier_confidence": 0.65,
        "date": "2025-01-15",
        "date_confidence": 0.55,
        "doc_type": "Rechnung",
        "doc_type_confidence": 0.68,
        "doc_number": "RE-123",
        "doc_number_confidence": 0.75,
    }


@pytest.fixture
def missing_fields_extraction():
    """Extraction mit fehlenden Feldern."""
    return {
        "supplier_canonical": None,
        "supplier_confidence": None,
        "date": None,
        "date_confidence": 0.90,
        "doc_type": "Rechnung",
        "doc_type_confidence": 0.85,
        "doc_number": None,
        "doc_number_confidence": None,
    }


# --- Tests für decide_review_status() ---


def test_decide_review_status_all_pass(high_confidence_extraction, mock_settings):
    """Test: Alle Gates bestanden → READY."""
    decision = decide_review_status(high_confidence_extraction, mock_settings)

    assert decision.status == DocumentStatus.READY
    assert len(decision.reasons) == 0
    assert decision.details["gates_passed"] == 4
    assert decision.details["gates_failed"] == 0


def test_decide_review_status_low_confidence(low_confidence_extraction, mock_settings):
    """Test: Niedrige Confidences → NEEDS_REVIEW."""
    decision = decide_review_status(low_confidence_extraction, mock_settings)

    assert decision.status == DocumentStatus.NEEDS_REVIEW
    assert ReviewReasonCode.SUPPLIER_CONF_LOW in decision.reasons
    assert ReviewReasonCode.DATE_CONF_LOW in decision.reasons
    assert ReviewReasonCode.DOC_TYPE_CONF_LOW in decision.reasons
    assert decision.details["gates_passed"] == 1  # nur doc_number
    assert decision.details["gates_failed"] == 3


def test_decide_review_status_missing_fields(missing_fields_extraction, mock_settings):
    """Test: Fehlende Felder → NEEDS_REVIEW."""
    decision = decide_review_status(missing_fields_extraction, mock_settings)

    assert decision.status == DocumentStatus.NEEDS_REVIEW
    assert ReviewReasonCode.MISSING_SUPPLIER in decision.reasons
    assert ReviewReasonCode.MISSING_DATE in decision.reasons
    assert ReviewReasonCode.MISSING_DOC_NUMBER in decision.reasons
    assert decision.details["gates_passed"] == 1  # nur doc_type
    assert decision.details["gates_failed"] == 3


def test_decide_review_status_boundary_values(mock_settings):
    """Test: Boundary-Werte (genau am Gate-Threshold)."""
    # Genau am Threshold (sollte passen)
    extraction = {
        "supplier_canonical": "Test GmbH",
        "supplier_confidence": 0.80,
        "date": "2025-01-15",
        "date_confidence": 0.80,
        "doc_type": "Rechnung",
        "doc_type_confidence": 0.70,
        "doc_number": "RE-123",
        "doc_number_confidence": 0.80,
    }

    decision = decide_review_status(extraction, mock_settings)
    assert decision.status == DocumentStatus.READY
    assert len(decision.reasons) == 0


def test_decide_review_status_just_below_threshold(mock_settings):
    """Test: Knapp unter Threshold → NEEDS_REVIEW."""
    extraction = {
        "supplier_canonical": "Test GmbH",
        "supplier_confidence": 0.79,  # Unter 0.80
        "date": "2025-01-15",
        "date_confidence": 0.80,
        "doc_type": "Rechnung",
        "doc_type_confidence": 0.70,
        "doc_number": "RE-123",
        "doc_number_confidence": 0.80,
    }

    decision = decide_review_status(extraction, mock_settings)
    assert decision.status == DocumentStatus.NEEDS_REVIEW
    assert ReviewReasonCode.SUPPLIER_CONF_LOW in decision.reasons


# --- Tests für build_final_filename() ---


def test_build_final_filename_standard():
    """Test: Standard Filename Building."""
    extraction = {"supplier_canonical": "Musterfirma GmbH", "date": "2025-01-15", "doc_number": "RE-2025-00123"}

    filename = build_final_filename(extraction)
    assert filename == "Musterfirma-GmbH_2025-01-15_RE-2025-00123.pdf"


def test_build_final_filename_sanitization():
    """Test: Filename Sanitization (verbotene Zeichen)."""
    extraction = {"supplier_canonical": "Test/Firma: GmbH", "date": "2025-01-15", "doc_number": "RE*2025?123"}

    filename = build_final_filename(extraction)
    # Verbotene Zeichen sollten entfernt werden
    assert "/" not in filename
    assert ":" not in filename
    assert "*" not in filename
    assert "?" not in filename


def test_build_final_filename_remove_scan_prefix():
    """Test: 'scan' Prefix wird entfernt."""
    extraction = {"supplier_canonical": "scan_Musterfirma GmbH", "date": "2025-01-15", "doc_number": "scan RE-123"}

    filename = build_final_filename(extraction)
    assert not filename.startswith("scan")
    assert "Musterfirma-GmbH" in filename


def test_build_final_filename_remove_timestamp():
    """Test: Timestamps (yyyy-mm-dd_hh-mm-ss) werden entfernt."""
    extraction = {
        "supplier_canonical": "Musterfirma GmbH",
        "date": "2025-01-15",
        "doc_number": "2025-01-15_14-30-00_RE-123",
    }

    filename = build_final_filename(extraction)
    # Timestamp sollte entfernt sein
    assert "14-30-00" not in filename
    assert "RE-123" in filename


def test_build_final_filename_missing_fields():
    """Test: Fehlende Felder → 'Unknown' Platzhalter."""
    extraction = {"supplier_canonical": None, "date": "2025-01-15", "doc_number": None}

    filename = build_final_filename(extraction)
    assert "Unknown" in filename
    assert "2025-01-15" in filename


# --- Tests für finalize_document() ---


def test_finalize_document_copy_mode(high_confidence_extraction, mock_settings, tmp_path):
    """Test: Finalize mit mode='copy' (Originaldatei bleibt)."""
    # Create source file
    source_file = tmp_path / "test_source.pdf"
    source_file.write_text("PDF Content")

    # Finalize
    result = finalize_document(
        doc_id="test123",
        source_path=source_file,
        extraction_result=high_confidence_extraction,
        settings=mock_settings,
        mode="copy",
    )

    assert result.success
    assert result.finalized_path.exists()
    assert source_file.exists()  # Original bleibt
    assert "Musterfirma-GmbH_2025-01-15_RE-2025-00123.pdf" in result.final_filename


def test_finalize_document_move_mode(high_confidence_extraction, mock_settings, tmp_path):
    """Test: Finalize mit mode='move' (Originaldatei wird verschoben)."""
    # Create source file
    source_file = tmp_path / "test_source.pdf"
    source_file.write_text("PDF Content")

    # Finalize
    result = finalize_document(
        doc_id="test123",
        source_path=source_file,
        extraction_result=high_confidence_extraction,
        settings=mock_settings,
        mode="move",
    )

    assert result.success
    assert result.finalized_path.exists()
    assert not source_file.exists()  # Original verschoben


def test_finalize_document_unique_suffix(high_confidence_extraction, mock_settings, tmp_path):
    """Test: Unique Suffix bei Datei-Duplikaten (_01, _02, ...)."""
    # Create existing file with same name
    target_dir = tmp_path
    existing_file = target_dir / "Musterfirma-GmbH_2025-01-15_RE-2025-00123.pdf"
    existing_file.write_text("Existing PDF")

    # Create source file
    source_file = tmp_path / "test_source.pdf"
    source_file.write_text("New PDF Content")

    # Finalize (sollte _01 Suffix bekommen)
    settings = mock_settings
    settings.autosort_enabled = False
    settings.autosort_base_dir = target_dir

    result = finalize_document(
        doc_id="test123",
        source_path=source_file,
        extraction_result=high_confidence_extraction,
        settings=settings,
        mode="copy",
    )

    assert result.success
    assert "_01.pdf" in result.final_filename


def test_finalize_document_autosort_enabled(high_confidence_extraction, tmp_path):
    """Test: AutoSort erstellt <Supplier>/<YYYY-MM>/ Struktur."""
    source_file = tmp_path / "test_source.pdf"
    source_file.write_text("PDF Content")

    settings = ReviewSettings(
        gate_supplier_min=0.80,
        gate_date_min=0.80,
        gate_doc_type_min=0.70,
        gate_doc_number_min=0.80,
        auto_finalize_enabled=False,
        autosort_enabled=True,
        autosort_base_dir=tmp_path,
    )

    result = finalize_document(
        doc_id="test123",
        source_path=source_file,
        extraction_result=high_confidence_extraction,
        settings=settings,
        mode="copy",
    )

    assert result.success
    # Prüfe AutoSort Struktur: <Base>/Musterfirma-GmbH/2025-01/
    assert "Musterfirma-GmbH" in str(result.finalized_path)
    assert "2025-01" in str(result.finalized_path)
    assert result.autosort_reason == "autosort_enabled"


# --- Tests für save_correction() ---


def _read_corrections(path):
    """Hilfsfunktion: Liest corrections.jsonl als Liste."""
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_save_correction(tmp_path):
    """Test: Correction wird in corrections.jsonl gespeichert."""
    corrections_file = tmp_path / "corrections.jsonl"

    original = {
        "supplier_canonical": "Old Supplier",
        "doc_type": "Rechnung",
        "date": "2025-01-10",
        "doc_number": "RE-123",
    }

    corrected = {
        "supplier_canonical": "New Supplier",
        "doc_type": "Lieferschein",
        "date": "2025-01-11",
        "doc_number": "LS-456",
    }

    save_correction(corrections_file, "doc123", "admin@test.com", original, corrected)

    assert corrections_file.exists()

    data = _read_corrections(corrections_file)
    assert len(data) == 1
    assert data[0]["doc_id"] == "doc123"
    assert data[0]["user"] == "admin@test.com"
    assert data[0]["original"]["supplier_canonical"] == "Old Supplier"
    assert data[0]["corrected"]["supplier_canonical"] == "New Supplier"


def test_save_correction_append(tmp_path):
    """Test: Mehrere Corrections werden angehängt."""
    corrections_file = tmp_path / "corrections.jsonl"

    save_correction(corrections_file, "doc1", "user1", {"field": "old1"}, {"field": "new1"})
    save_correction(corrections_file, "doc2", "user2", {"field": "old2"}, {"field": "new2"})

    data = _read_corrections(corrections_file)
    assert len(data) == 2
    assert data[0]["doc_id"] == "doc1"
    assert data[1]["doc_id"] == "doc2"


# --- Tests für save_ground_truth_sample() ---


def test_save_ground_truth_sample(tmp_path):
    """Test: Ground Truth Sample wird als JSONL gespeichert."""
    ground_truth_file = tmp_path / "ground_truth.jsonl"

    labels = {
        "supplier_canonical": "Musterfirma GmbH",
        "doc_type": "Rechnung",
        "date": "2025-01-15",
        "doc_number": "RE-123",
    }

    save_ground_truth_sample(ground_truth_file, "doc123", "Full OCR text here...", labels)

    assert ground_truth_file.exists()

    lines = ground_truth_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    sample = json.loads(lines[0])
    assert sample["doc_id"] == "doc123"
    assert sample["text"] == "Full OCR text here..."
    assert sample["labels"]["supplier_canonical"] == "Musterfirma GmbH"


def test_save_ground_truth_sample_append(tmp_path):
    """Test: Mehrere Samples werden angehängt (JSONL Format)."""
    ground_truth_file = tmp_path / "ground_truth.jsonl"

    # First sample
    save_ground_truth_sample(ground_truth_file, "doc1", "Text 1", {"field": "value1"})

    # Second sample
    save_ground_truth_sample(ground_truth_file, "doc2", "Text 2", {"field": "value2"})

    lines = ground_truth_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2

    sample1 = json.loads(lines[0])
    sample2 = json.loads(lines[1])

    assert sample1["doc_id"] == "doc1"
    assert sample2["doc_id"] == "doc2"


# --- Run Tests ---

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
