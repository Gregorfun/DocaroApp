from __future__ import annotations

import json
from pathlib import Path

from core.document_intelligence import (
    apply_supplier_profile,
    compute_review_priority,
    derive_processing_route,
    load_supplier_profiles,
)


def test_load_supplier_profiles_normalizes_keys(tmp_path: Path) -> None:
    profile_path = tmp_path / "supplier_profiles.json"
    profile_path.write_text(
        json.dumps(
            {
                "WM GmbH": {"route_tag": "warehouse"},
                "Acme-1": {"route_tag": "finance"},
            }
        ),
        encoding="utf-8",
    )
    profiles = load_supplier_profiles(profile_path)
    assert "wmgmbh" in profiles
    assert "acme1" in profiles


def test_apply_supplier_profile_enriches_item() -> None:
    item = {
        "supplier": "WM GmbH",
        "doc_type": "SONSTIGES",
        "doc_number": "",
        "supplier_guess_line": "Beleg-Nr. LS-2026-1234",
    }
    profiles = {
        "wmgmbh": {
            "name": "WM",
            "doc_type_force": "LIEFERSCHEIN",
            "doc_number_patterns": [r"(LS-\d{4}-\d+)"],
            "review_confidence_min": 0.9,
            "route_tag": "warehouse",
        }
    }
    out = apply_supplier_profile(item, profiles)
    assert out["doc_type"] == "LIEFERSCHEIN"
    assert out["doc_number"] == "LS-2026-1234"
    assert out["profile_route"] == "warehouse"
    assert float(out["supplier_profile_review_conf_min"]) == 0.9


def test_review_priority_and_route() -> None:
    risky = {
        "doc_type": "SONSTIGES",
        "supplier_missing": True,
        "date_missing": True,
        "supplier_broken": False,
        "supplier_confidence": "0.30",
        "parsing_failed": False,
    }
    safe = {
        "doc_type": "LIEFERSCHEIN",
        "supplier_missing": False,
        "date_missing": False,
        "supplier_broken": False,
        "supplier_confidence": "0.95",
        "parsing_failed": False,
    }
    assert derive_processing_route(risky) == "triage"
    assert derive_processing_route({"doc_type": "RECHNUNG"}) == "finance"
    assert compute_review_priority(risky) > compute_review_priority(safe)
