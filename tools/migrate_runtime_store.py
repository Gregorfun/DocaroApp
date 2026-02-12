# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import Config
from core.runtime_store import RuntimeStore


def main() -> int:
    cfg = Config()
    db_path = cfg.DATA_DIR / "runtime_state.db"
    store = RuntimeStore(
        db_path,
        session_files_path=cfg.SESSION_FILES_PATH,
        supplier_corrections_path=cfg.SUPPLIER_CORRECTIONS_PATH,
        history_path=cfg.HISTORY_PATH,
    )

    print(f"Runtime store ready: {db_path}")
    print(f"session entries: {len(store.load_session_files())}")
    print(f"supplier corrections: {len(store.load_supplier_corrections())}")
    print(f"history entries: {len(store.load_history_entries())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
