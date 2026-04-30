"""Address-cleaner orchestrator.

Diverges from company/name's pipeline.py in three ways:
  1. Each row carries TWO inputs (business_name, website_url) instead of one
  2. Each row produces SIX outputs (street/city/state/zip/country/source_url
     plus confidence) instead of one cleaned string
  3. Per-row work has TWO stages (HTML fetch + LLM extract) instead of one
     batched LLM call

Keeps the same callback contract (progress_cb, batch_cb, cancel_cb) so the
existing UI streaming layer in main.py can route address-tab progress to the
SSE pipe without a separate code path.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .config import Settings, log
from .errors import ProviderError
from .fetch import fetch_pages
from .llm.base import AddressProvider
from .types import AddressContext


# Map fetch.py status codes onto the user-facing error tags shown in the UI.
FETCH_STATUS_TO_ERROR = {
    "cloudflare": "CLOUDFLARE",
    "broken": "SITE_BROKEN",
    "dead": "DEAD_DOMAIN",
    "tls_error": "TLS_ERROR",
    "no_response": "NO_RESPONSE",
}


@dataclass
class PipelineStats:
    total: int = 0
    null_rows: int = 0
    extracted_rows: int = 0
    foreign_rows: int = 0
    fetch_failed_rows: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    api_calls: int = 0
    actual_cost: float = 0.0


def run_row(name: str, website: str) -> AddressContext:
    """Wrap raw inputs into an AddressContext. No cleaning, no rules."""
    return AddressContext(
        business_name=(name or "").strip(),
        website_url=(website or "").strip(),
    )


async def _process_one(
    ctx: AddressContext,
    provider: AddressProvider | None,
    settings: Settings,
    fetch_sem: asyncio.Semaphore,
    llm_sem: asyncio.Semaphore,
) -> AddressContext:
    """Fetch HTML for one row, then run the LLM extractor on it."""
    if not ctx.website_url:
        ctx.error = "NO_RESPONSE"
        ctx.is_null = True
        return ctx

    html_text, fetch_status = await fetch_pages(
        ctx.website_url,
        per_page_chars=settings.per_page_chars,
        max_html_chars=settings.max_html_chars,
        sem=fetch_sem,
    )
    ctx.fetch_status = fetch_status

    if fetch_status != "ok":
        ctx.error = FETCH_STATUS_TO_ERROR.get(fetch_status, "NO_RESPONSE")
        ctx.is_null = True
        return ctx

    if provider is None:
        ctx.error = "LLM_UNAVAILABLE"
        ctx.flag("NEEDS_MANUAL_REVIEW")
        return ctx

    async with llm_sem:
        try:
            await provider.extract(ctx, html_text)
        except ProviderError as e:
            log(f"provider error on row {ctx.website_url!r}: {e!r}")
            ctx.error = "LLM_UNAVAILABLE"
            ctx.flag("LLM_UNAVAILABLE")
    return ctx


def route_rows(
    rows: list[tuple[int, str, str]],
    settings: Settings,
    provider: AddressProvider | None = None,
    progress_cb=None,
    cancel_cb=None,
    batch_cb=None,
) -> tuple[list[AddressContext], PipelineStats]:
    """Process rows of (idx, business_name, website_url).

    Returns ordered list of AddressContext + a stats summary.

    Mirrors company/name's route_rows signature except for the row tuple shape.
    The worker dispatch in main.py is responsible for unpacking address rows
    as 3-tuples and other-kind rows as 2-tuples.
    """
    return asyncio.run(
        _route_rows_async(rows, settings, provider, progress_cb, cancel_cb, batch_cb)
    )


async def _route_rows_async(
    rows: list[tuple[int, str, str]],
    settings: Settings,
    provider: AddressProvider | None,
    progress_cb,
    cancel_cb,
    batch_cb,
) -> tuple[list[AddressContext], PipelineStats]:
    stats = PipelineStats(total=len(rows))
    results: dict[int, AddressContext] = {}

    for idx, name, website in rows:
        results[idx] = run_row(name, website)

    if progress_cb:
        progress_cb(0, stats.total)

    if not provider:
        # No provider — flag every row, return.
        for idx in results:
            results[idx].error = "LLM_UNAVAILABLE"
            results[idx].flag("NEEDS_MANUAL_REVIEW")
        if batch_cb:
            batch_cb(list(results.items()), stats)
        return [results[i] for i, *_ in rows], stats

    fetch_sem = asyncio.Semaphore(settings.fetch_concurrency)
    llm_sem = asyncio.Semaphore(settings.llm_concurrency)

    # Process in batches so we can stream progress and let the worker
    # check cancel_cb between groups (matching company/name cadence).
    batch_size = max(1, settings.batch_size)
    indices = list(results.keys())
    done = 0

    for batch_start in range(0, len(indices), batch_size):
        if cancel_cb and cancel_cb():
            break
        batch_indices = indices[batch_start : batch_start + batch_size]
        tasks = [
            _process_one(
                results[i], provider, settings, fetch_sem, llm_sem
            )
            for i in batch_indices
        ]
        batch_done: list[tuple[int, AddressContext]] = []
        try:
            updated_ctxs = await asyncio.gather(*tasks, return_exceptions=False)
        except Exception as e:
            log(f"batch error: {e!r}")
            for i in batch_indices:
                results[i].error = "LLM_UNAVAILABLE"
                results[i].flag("LLM_UNAVAILABLE")
                batch_done.append((i, results[i]))
        else:
            for ctx, i in zip(updated_ctxs, batch_indices):
                results[i] = ctx
                if ctx.error == "FOREIGN":
                    stats.foreign_rows += 1
                elif ctx.error in (
                    "CLOUDFLARE", "SITE_BROKEN", "DEAD_DOMAIN",
                    "TLS_ERROR", "NO_RESPONSE",
                ):
                    stats.fetch_failed_rows += 1
                elif ctx.has_address():
                    stats.extracted_rows += 1
                else:
                    stats.null_rows += 1
                batch_done.append((i, ctx))

        done += len(batch_indices)
        if hasattr(provider, "running_usage"):
            try:
                usage = provider.running_usage()
                stats.prompt_tokens = int(usage.get("prompt_tokens", 0))
                stats.completion_tokens = int(usage.get("completion_tokens", 0))
                stats.api_calls = int(usage.get("api_calls", 0))
                stats.actual_cost = float(usage.get("cost", 0.0))
            except Exception as e:
                log(f"usage capture failed: {e!r}")

        if progress_cb:
            progress_cb(min(done, stats.total), stats.total)
        if batch_cb and batch_done:
            batch_cb(batch_done, stats)

    ordered = [results[i] for i, *_ in rows]
    return ordered, stats
