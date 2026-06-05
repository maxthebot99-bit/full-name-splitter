"""In-memory session store.

One ``Session`` per upload. Holds the uploaded file, parsed columns, run
state, cancel flag, and an asyncio event queue for streaming progress to
the UI. Sessions live under ``$DATA_DIR/sessions/<sid>/`` (or
``/var/tmp/full-name-splitter/sessions/<sid>/`` if no env override) and are swept
after ``IDLE_TTL_S`` of inactivity.

All endpoints validate ``session_id`` strictly as a UUID4 before doing any
filesystem operation, so user-supplied paths can never escape the sessions
root.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

IDLE_TTL_S: int = 60 * 60  # 60 minutes
SWEEP_INTERVAL_S: int = 5 * 60  # check every 5 minutes
# Persistent output retention. Past-run CSVs land under _outputs_root() and
# are downloadable from the History drawer; without this they accumulate
# forever (one user reported tracking 800+ runs after a few months on a
# similar app). Files older than this are reaped by the sweeper.
OUTPUT_RETENTION_S: int = 30 * 24 * 60 * 60  # 30 days

_log = logging.getLogger("full_name_splitter.sessions")


def _sessions_root() -> Path:
    p = os.environ.get("CLEANERS_HUB_SESSIONS_DIR")
    if p:
        return Path(p)
    return Path("/var/tmp/full-name-splitter/sessions")


def _outputs_root() -> Path:
    """Persistent output dir — survives systemctl restart.

    Lives under /var/lib (not PrivateTmp) so a service restart doesn't wipe
    completed run outputs. The systemd unit's ReadWritePaths covers
    /var/lib/full-name-splitter which contains this dir + spend.sqlite3 +
    history.sqlite3.
    """
    p = os.environ.get("CLEANERS_HUB_OUTPUTS_DIR")
    if p:
        return Path(p)
    return Path("/var/lib/full-name-splitter/outputs")


def is_valid_sid(sid: str) -> bool:
    """Strict UUID validation; rejects anything that's not a canonical UUID
    string. This is the path-traversal gate."""
    try:
        u = uuid.UUID(sid)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(u) == sid


@dataclass
class Session:
    sid: str
    kind: str  # 'company' or 'name'
    email: str | None
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    # File state
    upload_path: Path | None = None
    upload_filename: str | None = None
    upload_size_bytes: int = 0
    file_meta: dict[str, Any] | None = None
    columns: list[dict[str, Any]] | None = None
    selected_column: str | None = None
    row_count: int | None = None

    # Run state
    state: str = "idle"  # idle | running | done | cancelled | error | spend_blocked
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    error_msg: str | None = None

    # Output
    result_csv_path: Path | None = None
    result_row_count: int = 0
    result_cost_usd: float = 0.0
    result_prompt_tokens: int = 0
    result_completion_tokens: int = 0

    # Manual cell overrides: row index (0-based, matching the export DF index) →
    # (first, last) tuple. Either part can be None (cleared). Wins over the
    # Grok output at download time. Splitter-only: company/name kinds used a
    # single string here, but the splitter splits the row into two cells.
    overrides: dict[int, tuple[str | None, str | None]] = field(default_factory=dict)
    # In-memory copy of the source DataFrame, kept for cheap rebuilds when
    # the user toggles overrides or reruns a row.
    source_df: object | None = None  # pandas.DataFrame; typed loose to avoid import at session-creation time
    # Final NameContext list, for editable-cell + per-row rerun support.
    contexts: list = field(default_factory=list)

    # SSE event queue (per-session). Bound to the FastAPI loop on creation.
    event_queue: asyncio.Queue[dict[str, Any]] | None = None
    event_loop: asyncio.AbstractEventLoop | None = None

    # Number of currently-open SSE streams reading from this session. The
    # idle sweeper refuses to delete a session while this is >0 — otherwise
    # the queue ref under an active reader gets garbage-collected and the
    # SSE handler hangs/errors. Mutated only under contexts_lock.
    active_sse_count: int = 0

    # Re-entrant lock for ALL mutations that touch contexts / source_df /
    # overrides / active_sse_count. Both the worker thread (writing batch
    # results) and HTTP handlers (▶ rerun, override edit, SSE start/stop)
    # mutate these — without a lock the list can corrupt under concurrent
    # writes.
    contexts_lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def dir(self) -> Path:
        return _sessions_root() / self.sid

    @property
    def output_path(self) -> Path:
        """Persistent output file for this run. Survives systemctl restart."""
        return _outputs_root() / f"{self.sid}.csv"

    def touch(self) -> None:
        self.last_active = time.time()


class SessionStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: dict[str, Session] = {}
        _sessions_root().mkdir(parents=True, exist_ok=True)
        _outputs_root().mkdir(parents=True, exist_ok=True)

    def create(self, *, kind: str, email: str | None,
               loop: asyncio.AbstractEventLoop) -> Session:
        sid = str(uuid.uuid4())
        sess = Session(
            sid=sid,
            kind=kind,
            email=email,
            event_queue=asyncio.Queue(maxsize=10_000),
            event_loop=loop,
        )
        sess.dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._sessions[sid] = sess
        _log.info(
            "session_created",
            extra={"action": "session_created", "session_id": sid, "kind": kind,
                   "email": email},
        )
        return sess

    def get(self, sid: str) -> Session | None:
        if not is_valid_sid(sid):
            return None
        with self._lock:
            sess = self._sessions.get(sid)
        if sess is not None:
            sess.touch()
        return sess

    def delete(self, sid: str) -> None:
        if not is_valid_sid(sid):
            return
        with self._lock:
            sess = self._sessions.pop(sid, None)
        if sess is None:
            return
        try:
            shutil.rmtree(sess.dir, ignore_errors=True)
        except Exception:
            pass
        _log.info(
            "session_deleted",
            extra={"action": "session_deleted", "session_id": sid},
        )

    def sweep_idle(self) -> int:
        """Delete sessions inactive for more than IDLE_TTL_S. Returns count.

        Also skips sessions with at least one SSE stream still attached —
        deleting under an open stream collapses the queue ref and the
        client hangs. The stream's own exit decrement re-arms TTL.
        """
        cutoff = time.time() - IDLE_TTL_S
        to_delete: list[str] = []
        with self._lock:
            for sid, sess in self._sessions.items():
                if sess.state == "running":
                    continue  # don't TTL-out an active run
                with sess.contexts_lock:
                    if sess.active_sse_count > 0:
                        continue  # SSE reader still attached
                if sess.last_active < cutoff:
                    to_delete.append(sid)
        for sid in to_delete:
            self.delete(sid)
        if to_delete:
            _log.info(
                "session_sweep",
                extra={"action": "session_sweep", "count": len(to_delete)},
            )
        return len(to_delete)

    def snapshot(self) -> dict[str, Any]:
        """Lightweight snapshot for /api/health debugging (no secrets)."""
        with self._lock:
            return {
                "active": len(self._sessions),
                "ids": [
                    {
                        "sid": s.sid,
                        "kind": s.kind,
                        "state": s.state,
                        "age_s": int(time.time() - s.created_at),
                    }
                    for s in self._sessions.values()
                ],
            }


# Module-level singleton; main.py creates and references this directly.
store = SessionStore()


def sweep_old_outputs() -> int:
    """Delete output CSVs older than OUTPUT_RETENTION_S from _outputs_root.

    Past-run CSVs are still listed in history.sqlite3 after deletion — the
    download endpoint returns 410 ("output file missing on disk") in that
    case, which the UI surfaces as an inactive download link. Returns the
    number of files removed.
    """
    root = _outputs_root()
    if not root.exists():
        return 0
    cutoff = time.time() - OUTPUT_RETENTION_S
    removed = 0
    try:
        for f in root.iterdir():
            if not f.is_file():
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError as e:
                _log.warning("output sweep failed for %s: %r", f.name, e)
    except OSError as e:
        _log.warning("output sweep iter failed: %r", e)
    if removed:
        _log.info(
            "output_sweep",
            extra={"action": "output_sweep", "count": removed,
                   "retention_days": OUTPUT_RETENTION_S // 86400},
        )
    return removed


async def idle_sweeper_loop() -> None:
    """Background task: periodically sweep idle sessions + stale outputs."""
    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL_S)
            store.sweep_idle()
            sweep_old_outputs()
        except asyncio.CancelledError:
            return
        except Exception as e:
            _log.warning("sweeper_error: %r", e)


def session_public_dict(sess: Session) -> dict[str, Any]:
    """Browser-facing serialization of a session — never includes paths or keys."""
    return {
        "sid": sess.sid,
        "kind": sess.kind,
        "state": sess.state,
        "filename": sess.upload_filename,
        "size_bytes": sess.upload_size_bytes,
        "row_count": sess.row_count,
        "selected_column": sess.selected_column,
        "result_row_count": sess.result_row_count,
        "result_cost_usd": sess.result_cost_usd,
        "error_msg": sess.error_msg,
    }
