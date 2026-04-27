"""Threaded run worker.

Mirrors the legacy ``shell.py:_run_worker`` from the desktop apps but pushes
events through ``streaming.Pusher`` (SSE) instead of the PyWebView JS
bridge. The pipeline + IO modules are vendored per-cleaner under
``cleaners_hub.cleaners.{company,name}``; this worker dispatches to the
right one based on ``kind``.

Per-batch flow:
  1. SpendTracker.would_exceed_cap(estimate) → if true, push spend_cap_hit,
     fire alert, mark session ``spend_blocked``, exit cleanly.
  2. pipeline.route_rows(...) → calls Grok in batches; batch_cb pushes
     ``rows`` and ``telemetry`` events.
  3. After each chunk, record actual token usage to SpendTracker.
  4. After all chunks, build the export DataFrame, write CSV to
     ``session.dir / output.csv``, push state="done".
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from cleaners_hub.alerts import alerter
from cleaners_hub.audit import audit
from cleaners_hub.sessions import Session
from cleaners_hub.spend import (
    SPEND_CAP_USD_PER_DAY,
    SpendTracker,
    usd_for_tokens,
)
from cleaners_hub.streaming import Pusher

_log = logging.getLogger("cleaners_hub.workers")


def _modules_for(kind: str):
    """Return (pipeline, io_reader, io_writer, types, XAIProvider, errors) for a kind."""
    if kind not in ("company", "name"):
        raise ValueError(f"unknown kind: {kind!r}")
    base = f"cleaners_hub.cleaners.{kind}"
    pipeline = importlib.import_module(f"{base}.pipeline")
    io_reader = importlib.import_module(f"{base}.io.reader")
    io_writer = importlib.import_module(f"{base}.io.writer")
    types_mod = importlib.import_module(f"{base}.types")
    xai = importlib.import_module(f"{base}.llm.xai")
    errors = importlib.import_module(f"{base}.errors")
    config = importlib.import_module(f"{base}.config")
    return pipeline, io_reader, io_writer, types_mod, xai.XAIProvider, errors, config


def _ctx_to_row(n: int, ctx) -> dict[str, Any]:
    """Mirror legacy ``shell._ctx_to_row``. Same shape the React store expects."""
    if ctx.is_null:
        clean = None
        status = "null"
    elif (ctx.current or "").strip() == (ctx.original or "").strip():
        clean = ctx.current
        status = "unchanged"
    else:
        clean = ctx.current
        status = "changed"
    return {
        "n": n,
        "orig": ctx.original,
        "clean": clean,
        "status": status,
        "reason": ctx.llm_reason or "",
        "flags": sorted(ctx.flags),
        "route": getattr(ctx, "route", None),
    }


def _stats_to_telemetry(stats, elapsed: float) -> dict[str, Any]:
    rps = (stats.llm_rows + stats.null_rows) / elapsed if elapsed > 0 else 0.0
    return {
        "rowsPerSecond": round(rps, 2),
        "tokensIn": int(stats.prompt_tokens),
        "tokensOut": int(stats.completion_tokens),
        "nullCount": int(stats.null_rows),
        "rulesFired": int(stats.api_calls),
        "costUsd": round(float(stats.actual_cost), 4),
    }


def run_worker(
    session: Session,
    *,
    column: str,
    row_limit: int | None,
    spend: SpendTracker,
) -> None:
    """Sync entry point for the worker thread.

    Caller is expected to have set ``session.state = 'running'`` already and
    spawned this in a daemon ``threading.Thread``.
    """
    pusher = Pusher(session)
    kind = session.kind
    email = session.email
    sid = session.sid

    audit("run_worker_start", email=email, session_id=sid, kind=kind, column=column,
          row_limit=row_limit)
    pusher.push("state", "running")

    try:
        pipeline, io_reader, io_writer, _types_mod, XAIProvider, errors, config = _modules_for(kind)
    except Exception as e:
        session.state = "error"
        session.error_msg = f"Module load failed: {type(e).__name__}: {e}"
        audit("run_error", email=email, session_id=sid, kind=kind,
              error=session.error_msg, level=logging.ERROR)
        pusher.push("error", {"code": 500, "message": session.error_msg})
        pusher.push("state", "error")
        return

    settings = config.Settings.load()

    # Provider init can fail if the xAI key isn't planted on the VPS yet.
    try:
        provider = XAIProvider()
    except errors.ProviderAuthError as e:
        session.state = "error"
        session.error_msg = str(e)
        audit("run_error", email=email, session_id=sid, kind=kind,
              error="provider_auth", level=logging.ERROR)
        pusher.push("error", {"code": 401, "message": str(e)})
        pusher.push("state", "error")
        return
    except Exception as e:
        session.state = "error"
        session.error_msg = f"Provider init: {type(e).__name__}: {e}"
        audit("run_error", email=email, session_id=sid, kind=kind,
              error="provider_init", level=logging.ERROR)
        pusher.push("error", {"code": 500, "message": session.error_msg})
        pusher.push("state", "error")
        return

    # Recover the FileMeta saved on the session by /api/columns.
    meta = getattr(session, "_file_meta_obj", None)
    if meta is None:
        # Re-inspect — caller didn't run the columns step. Defensive.
        try:
            assert session.upload_path is not None
            meta = io_reader.inspect(session.upload_path)
        except Exception as e:
            session.state = "error"
            session.error_msg = f"File reinspect failed: {e}"
            pusher.push("error", {"code": 500, "message": session.error_msg})
            pusher.push("state", "error")
            return

    if column not in meta.columns:
        session.state = "error"
        session.error_msg = f"Column not found: {column!r}"
        pusher.push("error", {"code": 400, "message": session.error_msg})
        pusher.push("state", "error")
        return

    start = time.monotonic()
    all_contexts: list = []
    accumulated_dfs: list[pd.DataFrame] = []
    rows_seen = 0
    spend_was_blocked = False
    final_stats = None
    cumulative_cost: float = 0.0  # provider running_cost across chunks

    def _cancel_cb() -> bool:
        nonlocal spend_was_blocked
        if session.cancel_flag.is_set():
            return True
        # Daily-cap gate: cumulative committed spend + this run's uncommitted
        # in-flight cost from the provider.
        try:
            today = spend.today_total_usd()
            in_flight = Decimal(str(provider.running_usage().get("cost", 0.0)))
            if today + in_flight > SPEND_CAP_USD_PER_DAY:
                spend_was_blocked = True
                return True
        except Exception as e:
            _log.warning("spend cap check error: %r", e)
        return False

    try:
        for chunk_idx, df_chunk in enumerate(
            io_reader.read_chunks(meta, column, chunk_rows=settings.chunk_rows)
        ):
            if _cancel_cb():
                break
            if column not in df_chunk.columns:
                raise RuntimeError(
                    f"Column {column!r} disappeared from chunk {chunk_idx}"
                )

            # Build (idx, raw) pairs honoring row_limit
            chunk_rows: list[tuple[int, str]] = []
            for local_i, val in enumerate(df_chunk[column].astype(str).tolist()):
                if row_limit is not None and rows_seen >= row_limit:
                    break
                global_idx = rows_seen
                chunk_rows.append((global_idx, val))
                rows_seen += 1

            # Trim the source df to match in case row_limit cut us off
            df_used = df_chunk.iloc[: len(chunk_rows)].copy()
            accumulated_dfs.append(df_used)

            def _batch_cb(done_items, stats):
                rows_payload = [_ctx_to_row(n + 1, ctx) for n, ctx in done_items]
                pusher.push("rows", rows_payload)
                pusher.push("telemetry", _stats_to_telemetry(stats, time.monotonic() - start))

            chunk_contexts, chunk_stats = pipeline.route_rows(
                chunk_rows,
                settings,
                provider,
                cancel_cb=_cancel_cb,
                batch_cb=_batch_cb,
            )
            all_contexts.extend(chunk_contexts)
            final_stats = chunk_stats

            # Commit this chunk's actual spend to the SQLite tracker
            try:
                usage = provider.running_usage()
                total_cost = float(usage.get("cost", 0.0))
                delta = total_cost - cumulative_cost
                cumulative_cost = total_cost
                if delta > 0:
                    pt = int(usage.get("prompt_tokens", 0))
                    ct = int(usage.get("completion_tokens", 0))
                    spend.record(
                        kind=kind,
                        session_id=sid,
                        email=email,
                        prompt_tokens=pt,
                        completion_tokens=ct,
                        cost_usd=Decimal(str(delta)),
                    )
            except Exception as e:
                _log.warning("spend record failed: %r", e)

            if row_limit is not None and rows_seen >= row_limit:
                break
            if spend_was_blocked:
                break

        # ---- terminal state ----

        if session.cancel_flag.is_set():
            session.state = "cancelled"
            audit("run_cancelled", email=email, session_id=sid, kind=kind,
                  rows_processed=len(all_contexts))
            pusher.push("state", "cancelled")
            return

        if spend_was_blocked:
            session.state = "spend_blocked"
            today_total = spend.today_total_usd()
            pusher.push("spend_cap_hit", {
                "today_usd": float(today_total),
                "cap_usd": float(SPEND_CAP_USD_PER_DAY),
            })
            try:
                alerter().spend_cap_hit(
                    today_total_usd=today_total,
                    cap_usd=SPEND_CAP_USD_PER_DAY,
                )
            except Exception as e:
                _log.warning("alert spend_cap_hit failed: %r", e)
            audit("spend_cap_hit", email=email, session_id=sid, kind=kind,
                  today_usd=float(today_total), cap_usd=float(SPEND_CAP_USD_PER_DAY))
            pusher.push("state", "spend_blocked")
            return

        # Build export and write CSV
        if accumulated_dfs:
            source_df = pd.concat(accumulated_dfs, ignore_index=True)
        else:
            source_df = pd.DataFrame(columns=meta.columns)
        export_df = io_writer.build_export_df(source_df, column, all_contexts)
        out_path = session.dir / "output.csv"
        io_writer.write_csv(export_df, out_path)
        session.result_csv_path = out_path
        session.result_row_count = len(all_contexts)
        if final_stats is not None:
            session.result_cost_usd = float(final_stats.actual_cost)
            session.result_prompt_tokens = int(final_stats.prompt_tokens)
            session.result_completion_tokens = int(final_stats.completion_tokens)

        # Costly-run alert (>$1 per the spec)
        try:
            alerter().costly_run(
                email=email,
                session_id=sid,
                cost_usd=Decimal(str(session.result_cost_usd)),
                row_count=session.result_row_count,
                kind=kind,
            )
        except Exception as e:
            _log.warning("alert costly_run failed: %r", e)

        elapsed = time.monotonic() - start
        if final_stats is not None:
            pusher.push("telemetry", _stats_to_telemetry(final_stats, elapsed))
        session.state = "done"
        audit(
            "run_done",
            email=email,
            session_id=sid,
            kind=kind,
            row_count=session.result_row_count,
            cost_usd=session.result_cost_usd,
            elapsed_s=round(elapsed, 2),
        )
        pusher.push("state", "done")

    except Exception as e:
        session.state = "error"
        session.error_msg = f"{type(e).__name__}: {e}"
        audit("run_error", email=email, session_id=sid, kind=kind,
              error=session.error_msg, level=logging.ERROR)
        pusher.push("error", {"code": 500, "message": session.error_msg})
        pusher.push("state", "error")


def spawn_run(session: Session, *, column: str, row_limit: int | None,
              spend: SpendTracker) -> threading.Thread:
    """Convenience: start the worker on a daemon thread and return it."""
    t = threading.Thread(
        target=run_worker,
        kwargs={"session": session, "column": column, "row_limit": row_limit,
                "spend": spend},
        name=f"runworker-{session.sid[:8]}",
        daemon=True,
    )
    t.start()
    return t
