"""Pure-Grok pipeline: every raw cell from the sheet is sent to Grok.

Design intent (locked by Jason, Apr 2026):

- **No app-side judgment.** The app does not decide what is or isn't a
  company name. It does not strip, truncate, fix, or flag the input. It
  does not consult ``nulls.json`` to veto rows, and it does not cap
  pathological lengths. Grok is the sole decision-maker.
- **Blanks go to Grok too.** An empty cell is still "what's in the
  sheet." The authoritative prompt explicitly handles "blank or null"
  → return null, so Grok will do the right thing; the cost is a few
  tokens for the wrapper.
- **No cache.** Every row hits Grok fresh every run. Jason's call
  (Apr 2026): the app should never replay a prior decision, even Grok's
  own. If the prompt nudges or the data shifts, we want Grok to re-judge
  end-to-end. The cost tradeoff is accepted.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings, log
from .types import NameContext
from .errors import ProviderError
from .llm.base import Provider


@dataclass
class PipelineStats:
    total: int = 0
    # `null_rows` here means "Grok returned null for this row". It does
    # NOT count app-side short-circuits because there aren't any anymore.
    null_rows: int = 0
    # Kept for backward-compat with the old hybrid reporter; always 0 now.
    leakage_rows: int = 0
    deterministic_rows: int = 0
    llm_rows: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    api_calls: int = 0
    actual_cost: float = 0.0


def run_row(raw: str, settings: Settings) -> NameContext:
    """Wrap a raw value into a NameContext. No cleaning, no rules, no detection.

    Grok is the decision-maker for every row. This function just packages
    the raw input so the rest of the pipeline has a consistent type.
    """
    if raw is None:
        raw = ""
    return NameContext(original=raw, current=raw)


def route_rows(
    rows: list[tuple[int, str]],
    settings: Settings,
    provider: Provider | None = None,
    progress_cb=None,
    cancel_cb=None,
    batch_cb=None,
) -> tuple[list[NameContext], PipelineStats]:
    """Send every row through Grok. No cache, no replay — each run is fresh.

    rows: list of (row_index, raw_name).
    provider: Grok provider. Required — without it, rows are flagged
        ``NEEDS_MANUAL_REVIEW`` and passed through unchanged.
    progress_cb: optional callable(done, total) invoked after each batch.
    batch_cb: optional callable(done_items, stats) invoked whenever a
        batch of rows becomes final. ``done_items`` is a list of
        ``(row_index, NameContext)`` so the caller can stream them
        straight to the UI.
    """
    stats = PipelineStats(total=len(rows))
    results: dict[int, NameContext] = {}
    llm_queue: list[tuple[int, str]] = []
    preflight_emit: list[tuple[int, NameContext]] = []

    def _refresh_usage() -> None:
        if provider is not None and hasattr(provider, "running_usage"):
            try:
                usage = provider.running_usage()
                stats.prompt_tokens = int(usage.get("prompt_tokens", 0))
                stats.completion_tokens = int(usage.get("completion_tokens", 0))
                stats.api_calls = int(usage.get("api_calls", 0))
                stats.actual_cost = float(usage.get("cost", 0.0))
            except Exception as e:
                log(f"usage capture failed: {e!r}")

    # Pass-through. Every raw cell becomes a context and joins the LLM
    # queue unless the provider is missing. No blank check, no junk
    # check, no length cap — Jason wants Grok to see the sheet as-is.
    for idx, raw in rows:
        ctx = run_row(raw, settings)
        results[idx] = ctx
        llm_queue.append((idx, ctx.original))

    if progress_cb:
        progress_cb(0, stats.total)

    if provider and llm_queue:
        batch_size = max(1, settings.batch_size)
        for i in range(0, len(llm_queue), batch_size):
            if cancel_cb and cancel_cb():
                break
            batch = llm_queue[i : i + batch_size]
            raw_names = [r for _, r in batch]
            batch_done: list[tuple[int, NameContext]] = []
            try:
                outs = provider.clean_batch(raw_names)
            except ProviderError as e:
                log(f"provider error on batch size {len(batch)}: {e!r}")
                for idx, _raw in batch:
                    ctx = results[idx]
                    ctx.flag("LLM_UNAVAILABLE")
                    batch_done.append((idx, ctx))
            else:
                for (idx, raw), (cleaned, reason) in zip(batch, outs, strict=True):
                    ctx = results[idx]
                    ctx.llm_prompt = raw
                    ctx.llm_response = cleaned if cleaned is not None else "null"
                    ctx.llm_reason = (reason or None)
                    ctx.confidence = 1.0
                    if cleaned is None:
                        ctx.is_null = True
                        ctx.current = "null"
                        stats.null_rows += 1
                    else:
                        ctx.is_null = False
                        ctx.current = cleaned
                    stats.llm_rows += 1
                    batch_done.append((idx, ctx))
            if progress_cb:
                done = i + len(batch)
                progress_cb(min(done, stats.total), stats.total)
            if batch_cb and batch_done:
                _refresh_usage()
                batch_cb(batch_done, stats)
    elif not provider:
        for idx, _raw in llm_queue:
            results[idx].flag("NEEDS_MANUAL_REVIEW")
            preflight_emit.append((idx, results[idx]))

    # Final usage refresh covers the no-LLM path and trailing updates.
    _refresh_usage()

    # If nothing streamed mid-run (no provider, or caller didn't pass
    # batch_cb), fire once at the end so the caller still gets a flush.
    if batch_cb and preflight_emit:
        batch_cb(preflight_emit, stats)

    ordered = [results[i] for i, _ in rows]
    return ordered, stats
