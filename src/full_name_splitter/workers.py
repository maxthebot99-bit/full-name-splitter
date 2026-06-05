"""Threaded run worker.

Mirrors the legacy ``shell.py:_run_worker`` from the desktop apps but pushes
events through ``streaming.Pusher`` (SSE) instead of the PyWebView JS
bridge. The pipeline + IO modules are vendored per-cleaner under
``full_name_splitter.cleaners.{company,name}``; this worker dispatches to the
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

from full_name_splitter.alerts import alerter
from full_name_splitter.audit import audit
from full_name_splitter.history import history
from full_name_splitter.sessions import Session
from full_name_splitter.settings_store import settings as app_settings
from full_name_splitter.spend import (
    SPEND_CAP_USD_PER_DAY,
    SpendTracker,
)
from full_name_splitter.streaming import Pusher

_log = logging.getLogger("full_name_splitter.workers")


def _modules_for(kind: str):
    """Return (pipeline, io_reader, io_writer, types, XAIProvider, errors, config) for company/name.

    Address kind has a different module shape (different provider class,
    AddressContext instead of NameContext, multi-column writer) — use
    ``_modules_for_address()`` for that.
    """
    if kind not in ("company", "name"):
        raise ValueError(f"unknown kind for _modules_for: {kind!r}")
    base = f"full_name_splitter.cleaners.{kind}"
    pipeline = importlib.import_module(f"{base}.pipeline")
    io_reader = importlib.import_module(f"{base}.io.reader")
    io_writer = importlib.import_module(f"{base}.io.writer")
    types_mod = importlib.import_module(f"{base}.types")
    xai = importlib.import_module(f"{base}.llm.xai")
    errors = importlib.import_module(f"{base}.errors")
    config = importlib.import_module(f"{base}.config")
    return pipeline, io_reader, io_writer, types_mod, xai.XAIProvider, errors, config


def _modules_for_address():
    """Return the address-cleaner modules.

    Different shape from _modules_for() because the address tab uses a
    different LLM provider (OpenRouter, not xAI), a multi-column output
    writer, and AddressContext instead of NameContext.
    """
    base = "full_name_splitter.cleaners.address"
    pipeline = importlib.import_module(f"{base}.pipeline")
    io_reader = importlib.import_module(f"{base}.io.reader")
    io_writer = importlib.import_module(f"{base}.io.writer")
    types_mod = importlib.import_module(f"{base}.types")
    openrouter = importlib.import_module(f"{base}.llm.openrouter")
    errors = importlib.import_module(f"{base}.errors")
    config = importlib.import_module(f"{base}.config")
    return (
        pipeline,
        io_reader,
        io_writer,
        types_mod,
        openrouter.OpenRouterLlamaProvider,
        errors,
        config,
    )


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


def _address_ctx_to_row(n: int, ctx) -> dict[str, Any]:
    """SSE/HTTP row payload for the address tab — multi-field shape.

    Differs from _ctx_to_row (single-string ``orig`` / ``clean``) because
    address rows have two inputs and seven structured outputs. The frontend
    address-tab renderer reads this shape. ctx.country is set by the
    pipeline (LLM extraction or TLD fallback for fetch-failed rows), so
    this function trusts whatever the pipeline produced.
    """
    has_addr = bool(ctx.street or ctx.city)
    if ctx.error == "FOREIGN":
        status = "foreign"
    elif ctx.error in (
        "CLOUDFLARE", "SITE_BROKEN", "DEAD_DOMAIN",
        "TLS_ERROR", "NO_RESPONSE", "LLM_UNAVAILABLE",
    ):
        status = "fetch_failed"
    elif has_addr:
        status = "extracted"
    else:
        status = "blank"
    return {
        "n": n,
        "business_name": ctx.business_name,
        "website_url": ctx.website_url,
        "street": ctx.street or "",
        "city": ctx.city or "",
        "state": ctx.state or "",
        "zip": ctx.zip or "",
        "country": ctx.country or "",
        "source_url": ctx.source_url or "",
        "confidence": round(float(ctx.confidence or 0.0), 2),
        "error": ctx.error or "",
        "status": status,
        "flags": sorted(ctx.flags),
    }


def _address_stats_to_telemetry(stats, elapsed: float) -> dict[str, Any]:
    """Telemetry for the address tab — different stats shape than company/name."""
    total_processed = (
        stats.extracted_rows + stats.null_rows
        + stats.foreign_rows + stats.fetch_failed_rows
    )
    rps = total_processed / elapsed if elapsed > 0 else 0.0
    return {
        "rowsPerSecond": round(rps, 2),
        "tokensIn": int(stats.prompt_tokens),
        "tokensOut": int(stats.completion_tokens),
        "extractedCount": int(stats.extracted_rows),
        "blankCount": int(stats.null_rows),
        "foreignCount": int(stats.foreign_rows),
        "fetchFailedCount": int(stats.fetch_failed_rows),
        "errorBreakdown": {k: int(v) for k, v in stats.error_breakdown.items()},
        "rulesFired": int(stats.api_calls),
        "costUsd": round(float(stats.actual_cost), 4),
    }


# ─── partial-cleaning helpers ────────────────────────────────────────────────
# Per-row ▶ and manual override need to work BEFORE a full run has been kicked
# off. The full-run worker can then skip rows that ▶ already cleaned. Both
# paths share session.contexts as a sparse list of length total_rows where
# slot i is None for "not yet cleaned" and a Context for "done".

def _ensure_partial_state(session: Session, column: str) -> bool:
    """Make sure session.source_df + session.contexts are ready for partial
    cleaning. Returns False if the file can't be read.

    Idempotent — once initialized, subsequent calls are cheap. The full-run
    worker calls this too so its skip-already-cleaned logic always sees a
    sized contexts list.
    """
    if session.upload_path is None:
        return False
    meta = getattr(session, "_file_meta_obj", None)
    if meta is None:
        return False

    if session.source_df is None:
        try:
            io_reader = importlib.import_module(
                f"full_name_splitter.cleaners.{session.kind}.io.reader"
            )
            parts = list(io_reader.read_chunks(meta, column, chunk_rows=10_000))
            session.source_df = (
                pd.concat(parts, ignore_index=True) if parts
                else pd.DataFrame(columns=meta.columns)
            )
        except Exception as e:
            _log.warning("source_df lazy load failed: %r", e)
            return False

    total = len(session.source_df)
    if not session.contexts:
        session.contexts = [None] * total
    elif len(session.contexts) < total:
        session.contexts.extend([None] * (total - len(session.contexts)))

    if session.selected_column is None:
        session.selected_column = column
    return True


def _passthrough_context(kind: str, original: str):
    """Build a Context that represents a row we didn't clean (row_limit cut
    us off, or skipped via partial cleaning). The export CSV needs *some*
    Context object per row; this one keeps ``current == original`` and
    flags ``route="pending"`` so it's clearly distinguishable from a real
    Grok answer.
    """
    types_mod = importlib.import_module(f"full_name_splitter.cleaners.{kind}.types")
    Ctx = types_mod.NameContext  # both kinds use NameContext
    return Ctx(
        original=original,
        current=original,
        flags={"NOT_PROCESSED"},
        is_null=False,
        llm_response=None,
        llm_reason="",
    )


def _row_payload(n: int, ctx: Any | None, *, orig: str = "",
                 clean: str | None = None, status: str = "pending",
                 reason: str = "") -> dict[str, Any]:
    """Build the SSE/HTTP row payload either from a Context (preferred when
    present) or from raw fields (used for pre-run override / pending rows)."""
    if ctx is not None:
        return _ctx_to_row(n, ctx)
    return {
        "n": n,
        "orig": orig,
        "clean": clean,
        "status": status,
        "reason": reason,
        "flags": [],
        "route": None,
    }


def run_worker(
    session: Session,
    *,
    column: str,
    row_limit: int | None,
    spend: SpendTracker,
    secondary_column: str | None = None,
) -> None:
    """Sync entry point for the worker thread.

    Caller is expected to have set ``session.state = 'running'`` already and
    spawned this in a daemon ``threading.Thread``.

    For ``kind == "address"``, ``column`` is the website-URL column and
    ``secondary_column`` is the business-name column. For company/name,
    ``secondary_column`` is ignored.
    """
    if session.kind == "address":
        _run_worker_address(
            session,
            website_column=column,
            name_column=secondary_column,
            row_limit=row_limit,
            spend=spend,
        )
        return

    pusher = Pusher(session)
    kind = session.kind
    email = session.email
    sid = session.sid

    audit("run_worker_start", email=email, session_id=sid, kind=kind, column=column,
          row_limit=row_limit)
    try:
        history().record_start(
            run_id=sid, email=email, kind=kind, column=column,
            filename=session.upload_filename,
        )
    except Exception as e:
        _log.warning("history.record_start failed: %r", e)
    pusher.push("state", "running")

    try:
        pipeline, io_reader, io_writer, _types_mod, XAIProvider, errors, config = _modules_for(kind)
    except Exception as e:
        session.state = "error"
        session.error_msg = f"Module load failed: {type(e).__name__}: {e}"
        audit("run_error", email=email, session_id=sid, kind=kind,
              error=session.error_msg, level=logging.ERROR)
        try:
            history().record_finish(run_id=sid, state="error",
                                    error_msg=session.error_msg)
        except Exception:
            pass
        pusher.push("error", {"code": 500, "message": session.error_msg})
        pusher.push("state", "error")
        return

    settings = config.Settings.load()
    # Apply runtime AppSettings (batch size + model) so admin tweaks via
    # /api/settings take effect on the next run without redeploying.
    _app = app_settings().get()
    settings.batch_size = _app.batch_size_for(kind)
    settings.model = {"xai": _app.model_for(kind)}
    soft_cap = Decimal(str(_app.daily_cap_usd))

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
    accumulated_dfs: list[pd.DataFrame] = []
    rows_seen = 0
    spend_was_blocked = False
    final_stats = None
    cumulative_cost: float = 0.0  # provider running_cost across chunks
    skipped_already_done = 0  # rows we didn't Grok because ▶ pre-cleaned them

    # Pre-allocate session.contexts to total_rows so the run can skip rows
    # that ▶ or apply_override already filled. If contexts is already the
    # right size (from prior partial cleaning) the call is a no-op.
    if not _ensure_partial_state(session, column):
        session.state = "error"
        session.error_msg = "Could not pre-load source for partial cleaning"
        pusher.push("error", {"code": 500, "message": session.error_msg})
        pusher.push("state", "error")
        return

    def _cancel_cb() -> bool:
        nonlocal spend_was_blocked
        if session.cancel_flag.is_set():
            return True
        # Daily-cap gate: cumulative committed spend + this run's uncommitted
        # in-flight cost from the provider. ``soft_cap`` is the AppSettings
        # value (UI-adjustable, bounded ≤ SPEND_CAP_USD_PER_DAY).
        try:
            today = spend.today_total_usd()
            in_flight = Decimal(str(provider.running_usage().get("cost", 0.0)))
            if today + in_flight > soft_cap:
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

            # Build (idx, raw) pairs honoring row_limit. Skip rows that
            # already have a context — those were cleaned by a prior ▶
            # click and don't need to round-trip through Grok again.
            chunk_rows: list[tuple[int, str]] = []
            chunk_local_count = 0  # rows from this chunk we keep in source_df
            for local_i, val in enumerate(df_chunk[column].astype(str).tolist()):
                if row_limit is not None and rows_seen >= row_limit:
                    break
                global_idx = rows_seen
                if (
                    global_idx < len(session.contexts)
                    and session.contexts[global_idx] is not None
                ):
                    skipped_already_done += 1
                else:
                    chunk_rows.append((global_idx, val))
                chunk_local_count += 1
                rows_seen += 1

            # Keep the full chunk in accumulated_dfs (skipped rows still
            # need to appear in the export DataFrame, just with their
            # already-cleaned context).
            df_used = df_chunk.iloc[:chunk_local_count].copy()
            accumulated_dfs.append(df_used)

            if not chunk_rows:
                # Whole chunk was already cleaned — nothing for Grok.
                continue

            def _batch_cb(done_items, stats):
                # Mirror results into session.contexts as we go so a mid-run
                # cancel still leaves usable partial state.
                rows_payload = []
                for idx, ctx in done_items:
                    if 0 <= idx < len(session.contexts):
                        session.contexts[idx] = ctx
                    rows_payload.append(_ctx_to_row(idx + 1, ctx))
                pusher.push("rows", rows_payload)
                pusher.push("telemetry", _stats_to_telemetry(stats, time.monotonic() - start))

            chunk_contexts, chunk_stats = pipeline.route_rows(
                chunk_rows,
                settings,
                provider,
                cancel_cb=_cancel_cb,
                batch_cb=_batch_cb,
            )
            # Belt-and-suspenders write in case route_rows finished a row
            # without firing batch_cb.
            for (gidx, _), ctx in zip(chunk_rows, chunk_contexts):
                if 0 <= gidx < len(session.contexts):
                    session.contexts[gidx] = ctx
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

        # session.contexts is the canonical list at this point; cleaned rows
        # have a Context, the rest are still None. Counts/exports work off
        # the populated entries.
        cleaned_count = sum(1 for c in session.contexts if c is not None)

        if session.cancel_flag.is_set():
            session.state = "cancelled"
            audit("run_cancelled", email=email, session_id=sid, kind=kind,
                  rows_processed=cleaned_count,
                  skipped_already_done=skipped_already_done)
            try:
                history().record_finish(
                    run_id=sid, state="cancelled",
                    row_count=cleaned_count,
                    cost_usd=cumulative_cost,
                )
            except Exception:
                pass
            pusher.push("state", "cancelled")
            return

        if spend_was_blocked:
            session.state = "spend_blocked"
            today_total = spend.today_total_usd()
            pusher.push("spend_cap_hit", {
                "today_usd": float(today_total),
                "cap_usd": float(soft_cap),
            })
            try:
                alerter().spend_cap_hit(
                    today_total_usd=today_total,
                    cap_usd=soft_cap,
                )
            except Exception as e:
                _log.warning("alert spend_cap_hit failed: %r", e)
            audit("spend_cap_hit", email=email, session_id=sid, kind=kind,
                  today_usd=float(today_total), cap_usd=float(soft_cap))
            try:
                history().record_finish(
                    run_id=sid, state="spend_blocked",
                    row_count=cleaned_count,
                    cost_usd=cumulative_cost,
                )
            except Exception:
                pass
            pusher.push("state", "spend_blocked")
            return

        # Build export and write CSV to PERSISTENT outputs dir (/var/lib/...)
        # so the file survives a systemctl restart. PrivateTmp wipes
        # session.dir on every unit start; outputs live outside that.
        if accumulated_dfs:
            source_df = pd.concat(accumulated_dfs, ignore_index=True)
        else:
            source_df = pd.DataFrame(columns=meta.columns)

        # Stash source_df on session for editable-cell rebuilds. contexts
        # was already updated row-by-row via _batch_cb.
        session.source_df = source_df

        # If row_limit was set, contexts past that index might still be
        # None — pad with synthetic "skipped" contexts so build_export_df
        # produces a clean output instead of crashing on Nones.
        any_unfilled = any(c is None for c in session.contexts)
        contexts_for_export: list = list(session.contexts)
        if any_unfilled:
            # Read-through: unfilled rows export as their original value.
            for i, c in enumerate(contexts_for_export):
                if c is not None:
                    continue
                if i < len(source_df):
                    raw = source_df[column].iloc[i] if column in source_df.columns else ""
                    orig_val = str(raw or "").strip()
                else:
                    orig_val = ""
                contexts_for_export[i] = _passthrough_context(kind, orig_val)

        export_df = io_writer.build_export_df(
            source_df, column, contexts_for_export,
            overrides=session.overrides or None,
        )
        out_path = session.output_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        io_writer.write_csv(export_df, out_path)
        session.result_csv_path = out_path
        session.result_row_count = cleaned_count
        if final_stats is not None:
            session.result_cost_usd = float(final_stats.actual_cost)
            session.result_prompt_tokens = int(final_stats.prompt_tokens)
            session.result_completion_tokens = int(final_stats.completion_tokens)

        elapsed = time.monotonic() - start

        # Always-on completion alert — one email per successful run.
        try:
            alerter().run_completed(
                email=email,
                session_id=sid,
                kind=kind,
                filename=session.upload_filename,
                row_count=session.result_row_count,
                cost_usd=Decimal(str(session.result_cost_usd)),
                elapsed_s=elapsed,
            )
        except Exception as e:
            _log.warning("alert run_completed failed: %r", e)

        # Separate higher-priority alert for unusually expensive runs.
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
        try:
            history().record_finish(
                run_id=sid, state="done",
                row_count=session.result_row_count,
                cost_usd=session.result_cost_usd,
                prompt_tokens=session.result_prompt_tokens,
                completion_tokens=session.result_completion_tokens,
                output_path=out_path,
            )
        except Exception:
            pass
        pusher.push("state", "done")

    except Exception as e:
        session.state = "error"
        session.error_msg = f"{type(e).__name__}: {e}"
        audit("run_error", email=email, session_id=sid, kind=kind,
              error=session.error_msg, level=logging.ERROR)
        try:
            history().record_finish(run_id=sid, state="error",
                                    error_msg=session.error_msg)
        except Exception:
            pass
        pusher.push("error", {"code": 500, "message": session.error_msg})
        pusher.push("state", "error")


def spawn_run(session: Session, *, column: str, row_limit: int | None,
              spend: SpendTracker, secondary_column: str | None = None) -> threading.Thread:
    """Convenience: start the worker on a daemon thread and return it.

    ``secondary_column`` is required when ``session.kind == "address"``
    (it's the business-name column; ``column`` is the website-URL column).
    Ignored for company/name.
    """
    t = threading.Thread(
        target=run_worker,
        kwargs={
            "session": session, "column": column, "row_limit": row_limit,
            "spend": spend, "secondary_column": secondary_column,
        },
        name=f"runworker-{session.sid[:8]}",
        daemon=True,
    )
    t.start()
    return t


# ─── address-tab worker (parallel to run_worker for kind="address") ──────────

def _passthrough_address_context(business_name: str, website_url: str):
    """Build an unprocessed AddressContext (e.g. when row_limit cut us off)."""
    types_mod = importlib.import_module("full_name_splitter.cleaners.address.types")
    return types_mod.AddressContext(
        business_name=business_name,
        website_url=website_url,
        flags={"NOT_PROCESSED"},
    )


def _run_worker_address(
    session: Session,
    *,
    website_column: str,
    name_column: str | None,
    row_limit: int | None,
    spend: SpendTracker,
) -> None:
    """Address-specific worker. Mirrors run_worker's structure but uses
    the address pipeline (HTML fetch + Llama 3.1 8B per-row extract) and
    streams multi-field row payloads to the SSE pipe.
    """
    pusher = Pusher(session)
    email = session.email
    sid = session.sid

    audit("run_worker_start", email=email, session_id=sid, kind="address",
          column=website_column, secondary_column=name_column,
          row_limit=row_limit)
    try:
        history().record_start(
            run_id=sid, email=email, kind="address", column=website_column,
            filename=session.upload_filename,
        )
    except Exception as e:
        _log.warning("history.record_start failed: %r", e)
    pusher.push("state", "running")

    if not name_column:
        session.state = "error"
        session.error_msg = "address kind requires both column (website_url) and secondary_column (business_name)"
        pusher.push("error", {"code": 400, "message": session.error_msg})
        pusher.push("state", "error")
        return

    try:
        pipeline, io_reader, io_writer, _types_mod, ProviderCls, errors, config = \
            _modules_for_address()
    except Exception as e:
        session.state = "error"
        session.error_msg = f"Module load failed: {type(e).__name__}: {e}"
        audit("run_error", email=email, session_id=sid, kind="address",
              error=session.error_msg, level=logging.ERROR)
        pusher.push("error", {"code": 500, "message": session.error_msg})
        pusher.push("state", "error")
        return

    settings = config.Settings.load()
    _app = app_settings().get()
    settings.batch_size = _app.batch_size_for("address")
    settings.model = {"openrouter": _app.model_for("address")}
    soft_cap = Decimal(str(_app.daily_cap_usd))

    try:
        provider = ProviderCls()
    except errors.ProviderAuthError as e:
        session.state = "error"
        session.error_msg = str(e)
        audit("run_error", email=email, session_id=sid, kind="address",
              error="provider_auth", level=logging.ERROR)
        pusher.push("error", {"code": 401, "message": str(e)})
        pusher.push("state", "error")
        return
    except Exception as e:
        session.state = "error"
        session.error_msg = f"Provider init: {type(e).__name__}: {e}"
        audit("run_error", email=email, session_id=sid, kind="address",
              error="provider_init", level=logging.ERROR)
        pusher.push("error", {"code": 500, "message": session.error_msg})
        pusher.push("state", "error")
        return

    meta = getattr(session, "_file_meta_obj", None)
    if meta is None:
        try:
            assert session.upload_path is not None
            meta = io_reader.inspect(session.upload_path)
        except Exception as e:
            session.state = "error"
            session.error_msg = f"File reinspect failed: {e}"
            pusher.push("error", {"code": 500, "message": session.error_msg})
            pusher.push("state", "error")
            return

    if website_column not in meta.columns:
        session.state = "error"
        session.error_msg = f"Website column not found: {website_column!r}"
        pusher.push("error", {"code": 400, "message": session.error_msg})
        pusher.push("state", "error")
        return
    if name_column not in meta.columns:
        session.state = "error"
        session.error_msg = f"Business-name column not found: {name_column!r}"
        pusher.push("error", {"code": 400, "message": session.error_msg})
        pusher.push("state", "error")
        return

    start = time.monotonic()
    accumulated_dfs: list[pd.DataFrame] = []
    rows_seen = 0
    spend_was_blocked = False
    final_stats = None
    cumulative_cost: float = 0.0

    # Lazy-init contexts so partial-cleaning works the same way as company/name.
    if session.source_df is None:
        try:
            parts = list(io_reader.read_chunks(meta, website_column, chunk_rows=settings.chunk_rows))
            session.source_df = (
                pd.concat(parts, ignore_index=True) if parts
                else pd.DataFrame(columns=meta.columns)
            )
        except Exception as e:
            session.state = "error"
            session.error_msg = f"source_df load failed: {e}"
            pusher.push("error", {"code": 500, "message": session.error_msg})
            pusher.push("state", "error")
            return

    total = len(session.source_df)
    if not session.contexts:
        session.contexts = [None] * total
    elif len(session.contexts) < total:
        session.contexts.extend([None] * (total - len(session.contexts)))
    if session.selected_column is None:
        session.selected_column = website_column

    def _cancel_cb() -> bool:
        nonlocal spend_was_blocked
        if session.cancel_flag.is_set():
            return True
        try:
            today = spend.today_total_usd()
            in_flight = Decimal(str(provider.running_usage().get("cost", 0.0)))
            if today + in_flight > soft_cap:
                spend_was_blocked = True
                return True
        except Exception as e:
            _log.warning("spend cap check error: %r", e)
        return False

    try:
        for chunk_idx, df_chunk in enumerate(
            io_reader.read_chunks(meta, website_column, chunk_rows=settings.chunk_rows)
        ):
            if _cancel_cb():
                break
            if website_column not in df_chunk.columns:
                raise RuntimeError(f"Column {website_column!r} disappeared from chunk {chunk_idx}")
            if name_column not in df_chunk.columns:
                raise RuntimeError(f"Column {name_column!r} disappeared from chunk {chunk_idx}")

            chunk_rows: list[tuple[int, str, str]] = []
            chunk_local_count = 0
            websites = df_chunk[website_column].astype(str).tolist()
            names = df_chunk[name_column].astype(str).tolist()
            for local_i, (name_val, website_val) in enumerate(zip(names, websites)):
                if row_limit is not None and rows_seen >= row_limit:
                    break
                global_idx = rows_seen
                if (
                    global_idx < len(session.contexts)
                    and session.contexts[global_idx] is not None
                ):
                    pass  # already processed
                else:
                    chunk_rows.append((global_idx, name_val, website_val))
                chunk_local_count += 1
                rows_seen += 1

            df_used = df_chunk.iloc[:chunk_local_count].copy()
            accumulated_dfs.append(df_used)

            if not chunk_rows:
                continue

            def _batch_cb(done_items, stats):
                rows_payload = []
                for idx, ctx in done_items:
                    if 0 <= idx < len(session.contexts):
                        session.contexts[idx] = ctx
                    rows_payload.append(_address_ctx_to_row(idx + 1, ctx))
                pusher.push("rows", rows_payload)
                pusher.push(
                    "telemetry",
                    _address_stats_to_telemetry(stats, time.monotonic() - start),
                )

            chunk_contexts, chunk_stats = pipeline.route_rows(
                chunk_rows,
                settings,
                provider,
                cancel_cb=_cancel_cb,
                batch_cb=_batch_cb,
            )
            for (gidx, _name, _web), ctx in zip(chunk_rows, chunk_contexts):
                if 0 <= gidx < len(session.contexts):
                    session.contexts[gidx] = ctx
            final_stats = chunk_stats

            try:
                usage = provider.running_usage()
                total_cost = float(usage.get("cost", 0.0))
                delta = total_cost - cumulative_cost
                cumulative_cost = total_cost
                if delta > 0:
                    pt = int(usage.get("prompt_tokens", 0))
                    ct = int(usage.get("completion_tokens", 0))
                    spend.record(
                        kind="address",
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

        cleaned_count = sum(1 for c in session.contexts if c is not None)

        if session.cancel_flag.is_set():
            session.state = "cancelled"
            audit("run_cancelled", email=email, session_id=sid, kind="address",
                  rows_processed=cleaned_count)
            try:
                history().record_finish(
                    run_id=sid, state="cancelled",
                    row_count=cleaned_count, cost_usd=cumulative_cost,
                )
            except Exception:
                pass
            pusher.push("state", "cancelled")
            return

        if spend_was_blocked:
            session.state = "spend_blocked"
            today_total = spend.today_total_usd()
            pusher.push("spend_cap_hit", {
                "today_usd": float(today_total),
                "cap_usd": float(soft_cap),
            })
            try:
                alerter().spend_cap_hit(today_total_usd=today_total, cap_usd=soft_cap)
            except Exception as e:
                _log.warning("alert spend_cap_hit failed: %r", e)
            audit("spend_cap_hit", email=email, session_id=sid, kind="address",
                  today_usd=float(today_total), cap_usd=float(soft_cap))
            try:
                history().record_finish(
                    run_id=sid, state="spend_blocked",
                    row_count=cleaned_count, cost_usd=cumulative_cost,
                )
            except Exception:
                pass
            pusher.push("state", "spend_blocked")
            return

        if accumulated_dfs:
            source_df = pd.concat(accumulated_dfs, ignore_index=True)
        else:
            source_df = pd.DataFrame(columns=meta.columns)

        session.source_df = source_df

        contexts_for_export = list(session.contexts)
        for i, c in enumerate(contexts_for_export):
            if c is not None:
                continue
            if i < len(source_df):
                name_val = (
                    str(source_df[name_column].iloc[i] or "").strip()
                    if name_column in source_df.columns else ""
                )
                website_val = (
                    str(source_df[website_column].iloc[i] or "").strip()
                    if website_column in source_df.columns else ""
                )
            else:
                name_val = ""
                website_val = ""
            contexts_for_export[i] = _passthrough_address_context(name_val, website_val)

        export_df = io_writer.build_export_df(
            source_df, website_column, contexts_for_export,
        )
        out_path = session.output_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        io_writer.write_csv(export_df, out_path)
        session.result_csv_path = out_path
        session.result_row_count = cleaned_count
        if final_stats is not None:
            session.result_cost_usd = float(final_stats.actual_cost)
            session.result_prompt_tokens = int(final_stats.prompt_tokens)
            session.result_completion_tokens = int(final_stats.completion_tokens)

        elapsed = time.monotonic() - start

        try:
            alerter().run_completed(
                email=email, session_id=sid, kind="address",
                filename=session.upload_filename,
                row_count=session.result_row_count,
                cost_usd=Decimal(str(session.result_cost_usd)),
                elapsed_s=elapsed,
            )
        except Exception as e:
            _log.warning("alert run_completed failed: %r", e)

        try:
            alerter().costly_run(
                email=email, session_id=sid,
                cost_usd=Decimal(str(session.result_cost_usd)),
                row_count=session.result_row_count, kind="address",
            )
        except Exception as e:
            _log.warning("alert costly_run failed: %r", e)

        if final_stats is not None:
            pusher.push(
                "telemetry", _address_stats_to_telemetry(final_stats, elapsed)
            )
        session.state = "done"
        audit(
            "run_done", email=email, session_id=sid, kind="address",
            row_count=session.result_row_count,
            cost_usd=session.result_cost_usd,
            elapsed_s=round(elapsed, 2),
        )
        try:
            history().record_finish(
                run_id=sid, state="done",
                row_count=session.result_row_count,
                cost_usd=session.result_cost_usd,
                prompt_tokens=session.result_prompt_tokens,
                completion_tokens=session.result_completion_tokens,
                output_path=out_path,
            )
        except Exception:
            pass
        pusher.push("state", "done")

    except Exception as e:
        session.state = "error"
        session.error_msg = f"{type(e).__name__}: {e}"
        audit("run_error", email=email, session_id=sid, kind="address",
              error=session.error_msg, level=logging.ERROR)
        try:
            history().record_finish(run_id=sid, state="error",
                                    error_msg=session.error_msg)
        except Exception:
            pass
        pusher.push("error", {"code": 500, "message": session.error_msg})
        pusher.push("state", "error")


# ─── dry-run sample (sync, no SSE) ───────────────────────────────────────────

def dry_run_sample(
    session: Session,
    *,
    column: str,
    count: int = 25,
    spend: SpendTracker,
) -> dict[str, Any]:
    """Run ``count`` rows through Grok and return the result inline.

    Synchronous. No SSE. Doesn't touch session.state (so the caller can
    call this multiple times before committing to a full run). Records
    actual token usage to the spend tracker.
    """
    pipeline, io_reader, _io_writer, _types_mod, XAIProvider, _errors, config = \
        _modules_for(session.kind)

    settings_obj = config.Settings.load()
    _app = app_settings().get()
    settings_obj.batch_size = _app.batch_size_for(session.kind)
    settings_obj.model = {"xai": _app.model_for(session.kind)}

    meta = getattr(session, "_file_meta_obj", None)
    if meta is None:
        assert session.upload_path is not None
        meta = io_reader.inspect(session.upload_path)
    if column not in meta.columns:
        raise ValueError(f"unknown column: {column!r}")

    # Pull just enough rows from the first chunk
    chunks = io_reader.read_chunks(meta, column, chunk_rows=settings_obj.chunk_rows)
    df_chunk = next(iter(chunks))
    raw_vals = df_chunk[column].astype(str).tolist()[:count]
    rows: list[tuple[int, str]] = list(enumerate(raw_vals))

    start = time.monotonic()
    provider = XAIProvider()
    contexts, stats = pipeline.route_rows(rows, settings_obj, provider)
    elapsed = time.monotonic() - start

    # Record actual spend
    try:
        spend.record(
            kind=session.kind,
            session_id=session.sid,
            email=session.email,
            prompt_tokens=int(stats.prompt_tokens),
            completion_tokens=int(stats.completion_tokens),
            cost_usd=Decimal(str(stats.actual_cost)),
        )
    except Exception as e:
        _log.warning("dry_run_sample spend.record failed: %r", e)

    audit("dry_run_sample", email=session.email, session_id=session.sid,
          kind=session.kind, column=column, count=len(contexts),
          cost_usd=float(stats.actual_cost), elapsed_s=round(elapsed, 2))

    return {
        "meta": {
            "model": provider.model,
            "elapsed_s": round(elapsed, 2),
            "cost_usd": round(float(stats.actual_cost), 4),
            "count": len(contexts),
            "tokens_in": int(stats.prompt_tokens),
            "tokens_out": int(stats.completion_tokens),
        },
        "rows": [_ctx_to_row(n + 1, ctx) for n, ctx in enumerate(contexts)],
    }


# ─── per-row rerun (single-row Grok call) ────────────────────────────────────

def rerun_one_row(
    session: Session,
    *,
    n: int,
    spend: SpendTracker,
    column: str | None = None,
) -> dict[str, Any] | None:
    """Re-Grok a single row by 1-based index ``n``.

    Works pre-run (no full cleaning has happened yet) by lazy-loading the
    source DataFrame and pre-allocating session.contexts as a sparse list.
    Updates session.contexts[n-1] in place. The output CSV is only
    regenerated once the whole run is done — partial-state CSVs would mix
    cleaned and raw values in confusing ways.
    """
    target_col = session.selected_column or column
    if target_col is None:
        return None
    if not _ensure_partial_state(session, target_col):
        return None
    if n < 1 or n > len(session.contexts):
        return None

    pipeline, _io_reader, io_writer, _types_mod, XAIProvider, _errors, config = \
        _modules_for(session.kind)

    settings_obj = config.Settings.load()
    _app = app_settings().get()
    settings_obj.batch_size = _app.batch_size_for(session.kind)
    settings_obj.model = {"xai": _app.model_for(session.kind)}

    existing = session.contexts[n - 1]
    if existing is not None:
        original = existing.original
    else:
        # Pull the raw value from the cached source DataFrame.
        try:
            raw = session.source_df[target_col].iloc[n - 1]
            original = str(raw or "").strip()
        except Exception as e:
            _log.warning("rerun row read from source_df failed: %r", e)
            return None

    provider = XAIProvider()
    new_contexts, stats = pipeline.route_rows(
        [(0, original)], settings_obj, provider
    )
    new_ctx = new_contexts[0]
    session.contexts[n - 1] = new_ctx

    # Record actual spend
    try:
        spend.record(
            kind=session.kind,
            session_id=session.sid,
            email=session.email,
            prompt_tokens=int(stats.prompt_tokens),
            completion_tokens=int(stats.completion_tokens),
            cost_usd=Decimal(str(stats.actual_cost)),
        )
    except Exception as e:
        _log.warning("rerun_one_row spend.record failed: %r", e)

    # Rebuild output CSV only when every row has a context. Mid-cleaning
    # downloads should reflect a "complete" file, not a half-baked one.
    fully_cleaned = all(c is not None for c in session.contexts)
    if fully_cleaned and session.source_df is not None and session.selected_column:
        try:
            export_df = io_writer.build_export_df(
                session.source_df, session.selected_column,
                session.contexts, overrides=session.overrides or None,
            )
            io_writer.write_csv(export_df, session.output_path)
        except Exception as e:
            _log.warning("rerun output rewrite failed: %r", e)

    audit("rerun_row", email=session.email, session_id=session.sid,
          kind=session.kind, row_n=n, cost_usd=float(stats.actual_cost),
          pre_run=(existing is None))

    # Stream a row_update SSE event so any open browser updates live.
    Pusher(session).push("row_update", _ctx_to_row(n, new_ctx))
    return _ctx_to_row(n, new_ctx)


# ─── manual override (no Grok call) ──────────────────────────────────────────

def apply_override(
    session: Session,
    *,
    n: int,
    cleaned: str | None,
    column: str | None = None,
) -> dict[str, Any] | None:
    """Set/clear a manual override for row ``n``. Rewrites output CSV.

    ``cleaned=None`` clears the override (restoring the Grok value, if
    any). Works pre-run via the same lazy-init path rerun_one_row uses.
    """
    target_col = session.selected_column or column
    if target_col is None:
        return None
    if not _ensure_partial_state(session, target_col):
        return None
    if n < 1 or n > len(session.contexts):
        return None

    if cleaned is None:
        session.overrides.pop(n - 1, None)
    else:
        session.overrides[n - 1] = cleaned

    # Build the row payload — prefer an existing Context, else read the
    # raw value from source_df so the user sees their override against
    # the original.
    ctx = session.contexts[n - 1]
    if ctx is not None:
        original = ctx.original
        payload = _ctx_to_row(n, ctx)
    else:
        try:
            raw = session.source_df[target_col].iloc[n - 1]
            original = str(raw or "").strip()
        except Exception as e:
            _log.warning("override read from source_df failed: %r", e)
            return None
        payload = _row_payload(n, None, orig=original, clean=None,
                               status="pending", reason="")

    if cleaned is not None:
        payload["clean"] = cleaned
        payload["status"] = "changed" if cleaned != original else "unchanged"
        payload["reason"] = "manual override"
    elif ctx is None:
        # Override cleared and there's no Grok value either → row is back
        # to pending.
        payload["status"] = "pending"
        payload["clean"] = None
        payload["reason"] = ""

    # Rebuild output CSV only when every row has a context.
    fully_cleaned = all(c is not None for c in session.contexts)
    if fully_cleaned and session.source_df is not None and session.selected_column:
        _pipeline, _io_reader, io_writer, _types_mod, _XAIProvider, _errors, _config = \
            _modules_for(session.kind)
        try:
            export_df = io_writer.build_export_df(
                session.source_df, session.selected_column,
                session.contexts, overrides=session.overrides or None,
            )
            io_writer.write_csv(export_df, session.output_path)
        except Exception as e:
            _log.warning("override output rewrite failed: %r", e)

    audit("override_row", email=session.email, session_id=session.sid,
          kind=session.kind, row_n=n, cleared=(cleaned is None),
          pre_run=(ctx is None))

    Pusher(session).push("row_update", payload)
    return payload
