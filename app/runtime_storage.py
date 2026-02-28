from __future__ import annotations

import time
from typing import Callable, Optional

from core.runtime_store import RuntimeStore


class RuntimeStorageManager:
    """Thin adapter between Flask app helpers and RuntimeStore.

    Keeps function signatures in app/app.py stable while moving storage concerns
    out of the route module.
    """

    def __init__(
        self,
        *,
        runtime_store: RuntimeStore,
        get_session_id: Callable[[], str],
        get_user_scope: Callable[[], str],
        report_error: Callable[[str, Exception], None],
        log_retention_days: int,
    ) -> None:
        self._runtime_store = runtime_store
        self._get_session_id = get_session_id
        self._get_user_scope = get_user_scope
        self._report_error = report_error
        self._log_retention_days = int(log_retention_days)
        self._session_cache: dict[str, object] = {"data": None, "mtime": 0.0}

    def load_session_files(self) -> dict:
        try:
            data = self._runtime_store.load_session_files()
        except Exception as exc:
            self._report_error("runtime_store_session_load", exc)
            return {}
        self._session_cache["data"] = data
        self._session_cache["mtime"] = time.time()
        return data

    def save_session_files(self, data: dict) -> None:
        try:
            self._runtime_store.save_session_files(data)
        except Exception as exc:
            self._report_error("runtime_store_session_save", exc)
            return
        self._session_cache["data"] = data
        self._session_cache["mtime"] = time.time()

    def get_session_file_map(self) -> dict:
        data = self.load_session_files()
        sid = self._get_session_id()
        return data.get(sid, {})

    def set_session_file_entry(self, file_id: str, path: str, filename: str) -> None:
        data = self.load_session_files()
        sid = self._get_session_id()
        session_map = data.setdefault(sid, {})
        session_map[file_id] = {"path": path, "filename": filename}
        self.save_session_files(data)

    def remove_session_files(self) -> None:
        data = self.load_session_files()
        sid = self._get_session_id()
        if sid in data:
            data.pop(sid, None)
            self.save_session_files(data)

    def append_history(self, entry: dict) -> None:
        payload = dict(entry or {})
        payload.setdefault("owner_scope", self._get_user_scope())
        try:
            self._runtime_store.append_history(payload)
        except Exception as exc:
            self._report_error("runtime_store_history_append", exc)
            return
        self.trim_history()

    def load_supplier_corrections(self) -> dict:
        try:
            return self._runtime_store.load_supplier_corrections()
        except Exception as exc:
            self._report_error("runtime_store_corrections_load", exc)
            return {}

    def save_supplier_corrections(self, data: dict) -> None:
        try:
            self._runtime_store.save_supplier_corrections(data)
        except Exception as exc:
            self._report_error("runtime_store_corrections_save", exc)

    def load_history_entries(self) -> list:
        try:
            items = self._runtime_store.load_history_entries()
        except Exception as exc:
            self._report_error("runtime_store_history_load", exc)
            return []
        scope = self._get_user_scope()
        out: list[dict] = []
        for item in items:
            owner = str(item.get("owner_scope") or "").strip().lower()
            if owner and owner != scope:
                continue
            out.append(item)
        return out

    def latest_history_entry(self) -> Optional[dict]:
        entries = self.load_history_entries()
        for entry in reversed(entries):
            if entry.get("action_type") != "undo":
                return entry
        return None

    def trim_history(self) -> None:
        try:
            self._runtime_store.trim_history(self._log_retention_days)
        except Exception as exc:
            self._report_error("runtime_store_history_trim", exc)
