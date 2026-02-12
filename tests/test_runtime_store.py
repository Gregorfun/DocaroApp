from __future__ import annotations

import json
from pathlib import Path

from core.runtime_store import RuntimeStore


def test_runtime_store_migrates_json_files(tmp_path: Path) -> None:
    session_file = tmp_path / "session_files.json"
    corr_file = tmp_path / "supplier_corrections.json"
    history_file = tmp_path / "history.jsonl"
    db_file = tmp_path / "runtime_state.db"

    session_file.write_text(json.dumps({"sid": {"f1": {"path": "/tmp/a.pdf"}}}), encoding="utf-8")
    corr_file.write_text(json.dumps({"abc": "SupplierX"}), encoding="utf-8")
    history_file.write_text(
        json.dumps({"timestamp": "2026-01-01T00:00:00", "action_type": "x"}) + "\n", encoding="utf-8"
    )

    store = RuntimeStore(
        db_file,
        session_files_path=session_file,
        supplier_corrections_path=corr_file,
        history_path=history_file,
    )

    assert store.load_session_files().get("sid") is not None
    assert store.load_supplier_corrections().get("abc") == "SupplierX"
    assert len(store.load_history_entries()) == 1


def test_runtime_store_append_and_trim_history(tmp_path: Path) -> None:
    store = RuntimeStore(tmp_path / "runtime_state.db")
    store.append_history({"timestamp": "2020-01-01T00:00:00", "action_type": "old"})
    store.append_history({"timestamp": "2099-01-01T00:00:00", "action_type": "new"})

    store.trim_history(30)
    entries = store.load_history_entries()

    assert any(e.get("action_type") == "new" for e in entries)
    assert not any(e.get("action_type") == "old" for e in entries)
