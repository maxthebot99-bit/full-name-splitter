"""Run history — persistent record of every run.

One row per run, written when a run starts, updated when it finishes/errors.
Stored in SQLite at ``$DATA_DIR/history.sqlite3`` (alongside spend.sqlite3
and alerts.sqlite3).

The history serves three purposes:
  1. Browse past runs in the UI (file, kind, rows, cost, when, who)
  2. Re-download cleaned outputs from prior runs (output_path points at the
     persistent file under /var/lib/cleaners-hub/outputs/)
  3. Audit trail — joins with the journalctl audit log via run_id (== sid)

Scoping: all authorized users see all runs. Cloudflare Access already
trusts everyone in the wildcard policy. The ``email`` column lets the UI
show "by jazif@…" / "by you" labels without fancy access control.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cleaners_hub.spend import _data_dir

_log = logging.getLogger("cleaners_hub.history")


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HistoryStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (_data_dir() / "history.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        with self._lock, self._connect() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    ts_started TEXT NOT NULL,
                    ts_finished TEXT,
                    email TEXT,
                    kind TEXT NOT NULL,
                    column_name TEXT,
                    filename TEXT,
                    row_count INTEGER,
                    cost_usd REAL,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    state TEXT NOT NULL,
                    output_path TEXT,
                    error_msg TEXT
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts_started DESC)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_email ON runs(email)"
            )

    # ─── writes ──────────────────────────────────────────────────────────

    def record_start(
        self,
        *,
        run_id: str,
        email: str | None,
        kind: str,
        column: str,
        filename: str | None,
    ) -> None:
        with self._lock, self._connect() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO runs
                  (run_id, ts_started, email, kind, column_name, filename, state)
                VALUES (?, ?, ?, ?, ?, ?, 'running')
                """,
                (run_id, _ts(), email, kind, column, filename),
            )

    def record_finish(
        self,
        *,
        run_id: str,
        state: str,
        row_count: int = 0,
        cost_usd: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        output_path: Path | None = None,
        error_msg: str | None = None,
    ) -> None:
        with self._lock, self._connect() as c:
            c.execute(
                """
                UPDATE runs SET
                    ts_finished = ?,
                    state = ?,
                    row_count = ?,
                    cost_usd = ?,
                    prompt_tokens = ?,
                    completion_tokens = ?,
                    output_path = ?,
                    error_msg = ?
                WHERE run_id = ?
                """,
                (
                    _ts(),
                    state,
                    int(row_count),
                    float(cost_usd),
                    int(prompt_tokens),
                    int(completion_tokens),
                    str(output_path) if output_path else None,
                    error_msg,
                    run_id,
                ),
            )

    # ─── reads ───────────────────────────────────────────────────────────

    def list_runs(
        self,
        *,
        kind: str | None = None,
        email: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if email is not None:
            clauses.append("email = ?")
            params.append(email)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM runs {where} "
            "ORDER BY ts_started DESC "
            "LIMIT ? OFFSET ?"
        )
        params += [int(limit), int(offset)]
        with self._lock, self._connect() as c:
            rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as c:
            row = c.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def count_runs(self, *, kind: str | None = None, email: str | None = None) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if email is not None:
            clauses.append("email = ?")
            params.append(email)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock, self._connect() as c:
            row = c.execute(
                f"SELECT COUNT(*) FROM runs {where}", params
            ).fetchone()
        return int(row[0])


# Module-level singleton (avoids re-opening the SQLite file on every endpoint).
_singleton: HistoryStore | None = None
_singleton_lock = threading.Lock()


def history() -> HistoryStore:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = HistoryStore()
    return _singleton
