from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


class RuntimeStore:
    """SQLite-backed runtime store for session/history/corrections hotpaths.

    The store keeps external behavior stable (dict/list payloads) while moving
    file-append and JSON read-modify-write hotpaths to SQLite.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        session_files_path: Path | None = None,
        supplier_corrections_path: Path | None = None,
        history_path: Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.session_files_path = session_files_path
        self.supplier_corrections_path = supplier_corrections_path
        self.history_path = history_path

        self._init_db()
        self._migrate_from_json_files_once()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL DEFAULT (datetime('now')),
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _upsert_kv(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kv_store(key, value_json, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = datetime('now')
                """,
                (key, payload),
            )
            conn.commit()

    def _load_kv(self, key: str, default: Any) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value_json FROM kv_store WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(str(row["value_json"]))
        except Exception:
            return default

    def _history_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM history_events").fetchone()
        return int(row["c"] if row and row["c"] is not None else 0)

    def _migrate_from_json_files_once(self) -> None:
        flag = self._load_kv("migrated_v1", False)
        if flag:
            return

        migrated_any = False

        # session_files.json -> kv_store: session_files
        if self.session_files_path and self.session_files_path.exists():
            try:
                data = json.loads(self.session_files_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._upsert_kv("session_files", data)
                    migrated_any = True
            except Exception as exc:
                _LOGGER.warning("session_files migration skipped: %s", exc)

        # supplier_corrections.json -> kv_store: supplier_corrections
        if self.supplier_corrections_path and self.supplier_corrections_path.exists():
            try:
                data = json.loads(self.supplier_corrections_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._upsert_kv("supplier_corrections", data)
                    migrated_any = True
            except Exception as exc:
                _LOGGER.warning("supplier_corrections migration skipped: %s", exc)

        # history.jsonl -> history_events
        if self.history_path and self.history_path.exists() and self._history_count() == 0:
            try:
                lines = self.history_path.read_text(encoding="utf-8").splitlines()
                with self._connect() as conn:
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            payload = json.loads(line)
                        except Exception:
                            continue
                        conn.execute(
                            "INSERT INTO history_events(payload_json) VALUES (?)",
                            (json.dumps(payload, ensure_ascii=True),),
                        )
                    conn.commit()
                migrated_any = True
            except Exception as exc:
                _LOGGER.warning("history migration skipped: %s", exc)

        self._upsert_kv("migrated_v1", True)
        if migrated_any:
            _LOGGER.info("RuntimeStore JSON->SQLite migration completed")

    # Public API
    def load_session_files(self) -> dict[str, Any]:
        data = self._load_kv("session_files", {})
        return data if isinstance(data, dict) else {}

    def save_session_files(self, data: dict[str, Any]) -> None:
        self._upsert_kv("session_files", data if isinstance(data, dict) else {})

    def load_supplier_corrections(self) -> dict[str, str]:
        data = self._load_kv("supplier_corrections", {})
        return data if isinstance(data, dict) else {}

    def save_supplier_corrections(self, data: dict[str, str]) -> None:
        self._upsert_kv("supplier_corrections", data if isinstance(data, dict) else {})

    def append_history(self, entry: dict[str, Any]) -> None:
        payload = json.dumps(entry, ensure_ascii=True)
        with self._connect() as conn:
            conn.execute("INSERT INTO history_events(payload_json) VALUES (?)", (payload,))
            conn.commit()

    def load_history_entries(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM history_events ORDER BY id ASC").fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(str(row["payload_json"]))
                if isinstance(value, dict):
                    out.append(value)
            except Exception:
                continue
        return out

    def trim_history(self, retention_days: int) -> None:
        cutoff_expr = f"-{max(int(retention_days), 1)} days"
        with self._connect() as conn:
            rows = conn.execute("SELECT id, payload_json FROM history_events ORDER BY id ASC").fetchall()
            keep_ids: list[int] = []
            for row in rows:
                try:
                    payload = json.loads(str(row["payload_json"]))
                except Exception:
                    keep_ids.append(int(row["id"]))
                    continue
                ts = str((payload or {}).get("timestamp") or "").strip()
                if not ts:
                    keep_ids.append(int(row["id"]))
                    continue
                try:
                    cmp_row = conn.execute(
                        "SELECT datetime(?) >= datetime('now', ?)",
                        (ts, cutoff_expr),
                    ).fetchone()
                    if cmp_row and int(cmp_row[0]) == 1:
                        keep_ids.append(int(row["id"]))
                except Exception:
                    keep_ids.append(int(row["id"]))

            if not keep_ids:
                conn.execute("DELETE FROM history_events")
            else:
                placeholders = ",".join("?" for _ in keep_ids)
                conn.execute(f"DELETE FROM history_events WHERE id NOT IN ({placeholders})", tuple(keep_ids))
            conn.commit()
