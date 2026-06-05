"""SSE pusher — bridges the sync worker thread to an asyncio queue.

Events emitted by the worker / HTTP handlers (kept in sync with the
React store's handleSseEvent dispatcher):

  ("hello",         {"sid": <uuid>})           — sent once on stream open
  ("state",         "running"|"done"|"cancelled"|"error"|"spend_blocked")
  ("rows",          list[Row])                 — batch of cleaned rows
  ("row_update",    Row)                       — single-row rerun / override
  ("telemetry",     {...})                     — per-batch token + cost stats
  ("cost_estimate_update", {...})              — projected total + tokens/row
  ("error",         {"code": int, "message": str})
  ("spend_cap_hit", {"today_usd": float, "cap_usd": float})

A ``Pusher`` is bound to one session and can be called from any thread; it
schedules ``queue.put(...)`` on the FastAPI event loop via
``run_coroutine_threadsafe``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, AsyncIterator

_log = logging.getLogger("full_name_splitter.streaming")


def _json_default(o: Any) -> Any:
    if is_dataclass(o):
        return asdict(o)
    if isinstance(o, set):
        return sorted(o)
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"unserializable: {type(o)!r}")


class Pusher:
    """Thread-safe event pusher bound to one session.

    Worker threads call ``push(kind, payload)`` synchronously; the call
    schedules a put on the session's asyncio.Queue from inside the FastAPI
    loop. The SSE handler drains the queue.
    """

    def __init__(self, session) -> None:  # full_name_splitter.sessions.Session
        self._session = session

    def push(self, kind: str, payload: Any = None) -> None:
        loop = self._session.event_loop
        q = self._session.event_queue
        if loop is None or q is None:
            _log.warning("push(%s) before queue bound; dropped", kind)
            return
        event = {"kind": kind, "payload": payload}
        try:
            asyncio.run_coroutine_threadsafe(q.put(event), loop)
        except Exception as e:
            _log.warning("push(%s) failed: %r", kind, e)


def format_sse(event: dict[str, Any]) -> bytes:
    """Encode one event as an SSE ``data:`` frame."""
    body = json.dumps(event, default=_json_default, ensure_ascii=False)
    return f"data: {body}\n\n".encode("utf-8")


async def sse_event_stream(session) -> AsyncIterator[bytes]:
    """Async generator yielding SSE frames for one session.

    Sends a heartbeat every 15s so Cloudflare Tunnel + intermediate proxies
    don't time out idle connections during long uploads or thinking phases.
    Increments session.active_sse_count while open so the idle sweeper
    won't delete a session out from under a connected reader.
    """
    q = session.event_queue
    if q is None:
        return
    with session.contexts_lock:
        session.active_sse_count += 1
    try:
        yield format_sse({"kind": "hello", "payload": {"sid": session.sid}})
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield b": heartbeat\n\n"
                continue
            yield format_sse(event)
            if event.get("kind") == "state" and event.get("payload") in (
                "done", "error", "cancelled", "spend_blocked"
            ):
                # One last heartbeat so the client sees a clean close, then exit.
                yield b": stream-end\n\n"
                return
    finally:
        with session.contexts_lock:
            session.active_sse_count = max(0, session.active_sse_count - 1)
        session.touch()  # arms the idle TTL clock now that the reader's gone
