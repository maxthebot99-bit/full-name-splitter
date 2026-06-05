"""Sharper pre-call cost estimate via tiktoken on the actual prompt.

Replaces the legacy ``EST_USD_PER_ROW`` constant for the dry-run cost line
and the pre-flight cap check. We build the exact prompt the provider would
send for a small sample of rows, tokenize it with cl100k_base (Grok and
modern OpenAI models share that family — close enough at the rate we care
about, which is "near reality, not a hand-tuned constant"), then divide by
the configured batch size to get a per-row input-token estimate. We pair
that with an empirical per-row output budget pulled from the existing
``estimate_cost_per_row`` shape on each provider.

If tiktoken can't load the encoding (offline, broken install, etc.) we
fall back to the caller's ``fallback_per_row`` Decimal — keeping the
historical behavior so a dry-run never breaks just because tokenization
failed.

Returns ``(estimated_usd, breakdown)`` where ``breakdown`` carries the
inputs that produced the estimate so the API caller can surface them.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Iterable

_log = logging.getLogger("full_name_splitter.cost_estimate")

# Per-row output budget. Splitter emits two JSON fields plus ``why`` per
# row at temperature=0; ~14 tokens is the empirical mean we already
# documented in ``_openai_compat.py:estimate_cost_per_row``. Stays here
# so the estimate is provider-agnostic — every kind that imports this
# helper inherits the same output assumption unless it overrides.
DEFAULT_OUT_TOKENS_PER_ROW = 14.0


def tiktoken_estimate(
    provider,
    sample_rows: Iterable[str],
    *,
    batch_size: int,
    total_rows: int,
    fallback_per_row: Decimal,
    out_tokens_per_row: float = DEFAULT_OUT_TOKENS_PER_ROW,
) -> tuple[float, dict]:
    """Estimate run cost by tokenizing the *real* prompt for a sample.

    Args:
      provider: a kind's ``XAIProvider`` (or equivalent). We read
        ``cost_in_per_1k``/``cost_out_per_1k`` off ``provider._client`` when
        present, falling back to attributes on the provider itself for
        kinds whose providers expose pricing directly (e.g. openrouter).
      sample_rows: the first N rows from the file. We pad to ``batch_size``
        with the longest row repeated so the tokenized prompt reflects a
        full-batch shape (otherwise per-row counts skew high for tiny
        samples — fixed prompt overhead dominates).
      batch_size: actual configured batch size for the kind.
      total_rows: rows we expect to bill for (after row_limit clamp).
      fallback_per_row: legacy ``EST_USD_PER_ROW``-style constant used if
        tiktoken fails to load or the helper crashes.

    Returns:
      ``(estimated_cost_usd, breakdown)``. ``breakdown`` always carries a
      ``source`` field — ``"tiktoken"`` for the real path,
      ``"fallback_constant"`` for the legacy path.
    """
    sample = [r for r in sample_rows if r is not None]
    # Tokenizing 1-2 rows wildly over-attributes the prompt header to each
    # row — pad up so the math reflects a real batch.
    if not sample:
        sample = [""]
    if batch_size < 1:
        batch_size = 1
    if total_rows < 0:
        total_rows = 0

    # Pricing — provider._client is the canonical place (xAI clients), but
    # some providers (openrouter) hang the constants on the wrapper itself.
    cost_in_per_1k = _read_price(provider, "cost_in_per_1k", "_cost_in_per_1k")
    cost_out_per_1k = _read_price(provider, "cost_out_per_1k", "_cost_out_per_1k")
    if cost_in_per_1k is None or cost_out_per_1k is None:
        _log.warning("provider missing cost_in/out_per_1k; falling back to constant")
        return _fallback(fallback_per_row, total_rows, batch_size,
                         out_tokens_per_row, reason="missing_pricing")

    # Build the real prompt for the sample, padded up to one full batch.
    try:
        build_batch_prompt = _resolve_build_batch_prompt(provider)
    except Exception as e:
        _log.warning("could not locate build_batch_prompt: %r", e)
        return _fallback(fallback_per_row, total_rows, batch_size,
                         out_tokens_per_row, reason="no_prompt_builder")

    padded = _pad_sample(sample, batch_size)
    try:
        prompt = build_batch_prompt(padded)
    except Exception as e:
        _log.warning("build_batch_prompt failed during estimate: %r", e)
        return _fallback(fallback_per_row, total_rows, batch_size,
                         out_tokens_per_row, reason="prompt_build_failed")

    # Tokenize. cl100k_base is offline-safe — its BPE files are bundled
    # with the tiktoken wheel — so the import + get_encoding should
    # succeed in any environment where the package is installed.
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        prompt_tokens = len(enc.encode(prompt))
    except Exception as e:
        _log.warning("tiktoken encode failed: %r", e)
        return _fallback(fallback_per_row, total_rows, batch_size,
                         out_tokens_per_row, reason="tiktoken_unavailable")

    # Per-row math. Divide the batch prompt's token count by the batch
    # size to amortize the shared prompt header across the rows that
    # would actually consume it on the wire.
    in_per_row = prompt_tokens / float(batch_size)
    out_per_row = float(out_tokens_per_row)

    in_cost_per_row = (in_per_row / 1000.0) * float(cost_in_per_1k)
    out_cost_per_row = (out_per_row / 1000.0) * float(cost_out_per_1k)
    per_row_cost = in_cost_per_row + out_cost_per_row

    estimated_usd = per_row_cost * float(total_rows)

    breakdown = {
        "source": "tiktoken",
        "model": getattr(provider, "model", None),
        "batch_size": int(batch_size),
        "sample_rows_used": len(sample),
        "padded_rows_tokenized": len(padded),
        "prompt_tokens_batch": int(prompt_tokens),
        "prompt_tokens_per_row": round(in_per_row, 2),
        "completion_tokens_per_row": round(out_per_row, 2),
        "cost_in_per_1k": float(cost_in_per_1k),
        "cost_out_per_1k": float(cost_out_per_1k),
        "cost_per_row_usd": per_row_cost,
        "total_rows": int(total_rows),
    }
    return estimated_usd, breakdown


def _read_price(provider, *attrs: str) -> float | None:
    # Try the provider, then provider._client (OpenAI-compatible wrapper).
    targets = [provider, getattr(provider, "_client", None)]
    for tgt in targets:
        if tgt is None:
            continue
        for a in attrs:
            v = getattr(tgt, a, None)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
    return None


def _resolve_build_batch_prompt(provider):
    """Locate the kind's ``build_batch_prompt`` import.

    Provider knows its kind via its module path (e.g.
    ``full_name_splitter.cleaners.fullname.llm.xai``). We import
    ``...llm.prompt_loader`` off that root and pull ``build_batch_prompt``
    out. That's the same function the runtime client uses, so the
    tokenized prompt is the actual wire payload — not an approximation.
    """
    import importlib
    mod_name = type(provider).__module__
    # Strip the ``.llm.xai`` (or ``.llm.openrouter``) suffix to get the
    # kind base, then re-attach ``.llm.prompt_loader``.
    parts = mod_name.split(".")
    # Find ``llm`` — the last occurrence wins, in case a provider lives
    # deeper.
    try:
        llm_idx = len(parts) - 1 - parts[::-1].index("llm")
    except ValueError as e:
        raise RuntimeError(f"provider module {mod_name!r} has no 'llm' segment") from e
    prompt_mod = ".".join(parts[: llm_idx + 1] + ["prompt_loader"])
    mod = importlib.import_module(prompt_mod)
    fn = getattr(mod, "build_batch_prompt", None)
    if fn is None:
        raise RuntimeError(f"{prompt_mod} has no build_batch_prompt")
    return fn


def _pad_sample(sample: list[str], batch_size: int) -> list[str]:
    """Pad a small sample up to ``batch_size`` with realistic rows so the
    tokenized prompt reflects a full batch's shape.

    We cycle through the sample to keep the input distribution close to
    what the user is actually about to send, instead of repeating the
    same row (which would under-count when downstream tokenization runs
    BPE merges on identical substrings).
    """
    if len(sample) >= batch_size:
        return sample[:batch_size]
    out: list[str] = []
    i = 0
    while len(out) < batch_size:
        out.append(sample[i % len(sample)])
        i += 1
    return out


def _fallback(
    fallback_per_row: Decimal,
    total_rows: int,
    batch_size: int,
    out_tokens_per_row: float,
    *,
    reason: str,
) -> tuple[float, dict]:
    est = float(fallback_per_row) * total_rows
    return est, {
        "source": "fallback_constant",
        "reason": reason,
        "batch_size": int(batch_size),
        "completion_tokens_per_row": round(float(out_tokens_per_row), 2),
        "fallback_per_row_usd": float(fallback_per_row),
        "total_rows": int(total_rows),
    }


def sample_rows_from_meta(meta, column: str, *, n: int = 20) -> list[str]:
    """Pull the first ``n`` non-empty values from ``column`` for the
    estimate. Reads the file lazily via the kind's ``io_reader`` so we
    never hold the whole file in memory.

    Returns ``[]`` on any read error — caller treats that as "fall back".
    """
    import importlib
    if meta is None or not column:
        return []
    try:
        # The reader module lives at <pkg>.cleaners.<kind>.io.reader; we
        # don't know <pkg> here, so dispatch via the caller's helper. Keep
        # this as a thin convenience: production callers pass the reader
        # directly (see main.py).
        raise RuntimeError("call sample_rows_via_reader instead")
    except Exception:
        return []


def sample_rows_via_reader(io_reader, meta, column: str, *, n: int = 20) -> list[str]:
    """Read the first ``n`` non-empty values from ``column`` via the kind's
    own reader. Tolerant of read failures — returns ``[]`` on anything bad.
    """
    if meta is None or not column:
        return []
    try:
        chunks = io_reader.read_chunks(meta, column, chunk_rows=max(n, 100))
        df = next(iter(chunks), None)
        if df is None or column not in df.columns:
            return []
        vals: list[str] = []
        for v in df[column].astype(str).tolist():
            s = (v or "").strip()
            if not s:
                continue
            vals.append(s)
            if len(vals) >= n:
                break
        return vals
    except Exception as e:
        _log.warning("sample_rows_via_reader failed: %r", e)
        return []
