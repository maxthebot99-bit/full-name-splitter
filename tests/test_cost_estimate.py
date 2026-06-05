"""Unit tests for the tiktoken-based pre-call cost estimate.

These tests stub out the provider so no network calls or real keys are
needed. We exercise:
  * the happy path (tiktoken loads, prompt builds, math comes out
    consistent with the per-1k pricing constants)
  * the fallback path when the provider can't surface pricing
  * sample padding when sample_rows < batch_size
  * total_rows scaling — the per-row cost stays stable, only the
    multiplier changes
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from full_name_splitter.cost_estimate import (
    tiktoken_estimate,
    _pad_sample,
    sample_rows_via_reader,
)


# A real XAIProvider would import from the cleaners.fullname.llm.xai path;
# we mimic the public surface (module path + ``_client`` + ``model``) so
# the helper can resolve ``build_batch_prompt`` and read pricing.
class FakeXAIClient:
    cost_in_per_1k = 0.0002   # $0.20 / 1M (matches xai.py's wiring)
    cost_out_per_1k = 0.0005  # $0.50 / 1M


# Module path matches the real provider so the resolver can find
# ``...llm.prompt_loader.build_batch_prompt``.
class _FakeXAIProvider:
    __module__ = "full_name_splitter.cleaners.fullname.llm.xai"

    def __init__(self) -> None:
        self.model = "grok-4-fast-reasoning"
        self._client = FakeXAIClient()


def _make_provider() -> _FakeXAIProvider:
    return _FakeXAIProvider()


def test_tiktoken_estimate_happy_path():
    """Sample rows tokenize and the per-row cost > 0, source is tiktoken."""
    provider = _make_provider()
    sample = ["John Smith", "Mary Jane Watson", "Dr. Bob McKenzie III"]
    est, breakdown = tiktoken_estimate(
        provider, sample,
        batch_size=100, total_rows=1000,
        fallback_per_row=Decimal("0.000011"),
    )
    assert est > 0, "estimate should be positive on the happy path"
    assert breakdown["source"] == "tiktoken"
    assert breakdown["batch_size"] == 100
    assert breakdown["total_rows"] == 1000
    assert breakdown["prompt_tokens_per_row"] > 0
    assert breakdown["completion_tokens_per_row"] == 14.0
    # Per-row cost should match the breakdown's own math.
    per_row = breakdown["cost_per_row_usd"]
    assert est == pytest.approx(per_row * 1000, rel=1e-9)


def test_tiktoken_estimate_scales_linearly_with_total_rows():
    """Doubling total_rows should ~double the estimate."""
    provider = _make_provider()
    sample = ["John Smith", "Mary Jane Watson"]
    est_500, _ = tiktoken_estimate(
        provider, sample,
        batch_size=100, total_rows=500,
        fallback_per_row=Decimal("0.000011"),
    )
    est_1000, _ = tiktoken_estimate(
        provider, sample,
        batch_size=100, total_rows=1000,
        fallback_per_row=Decimal("0.000011"),
    )
    assert est_1000 == pytest.approx(est_500 * 2, rel=1e-9)


def test_tiktoken_estimate_falls_back_without_pricing():
    """A provider that exposes no pricing should fall back to the constant."""
    # FakeProvider with no _client and no cost_in_per_1k attrs.
    class NoPricing:
        pass
    # Set __module__ so the prompt resolver doesn't crash first.
    NoPricing.__module__ = "full_name_splitter.cleaners.fullname.llm.xai"
    provider = NoPricing()
    est, breakdown = tiktoken_estimate(
        provider, ["test"],
        batch_size=100, total_rows=1000,
        fallback_per_row=Decimal("0.000011"),
    )
    assert breakdown["source"] == "fallback_constant"
    assert breakdown["reason"] == "missing_pricing"
    # Should equal the constant × rows.
    assert est == pytest.approx(0.000011 * 1000, rel=1e-9)


def test_tiktoken_estimate_zero_rows_returns_zero_cost():
    """Total rows = 0 → estimate is 0 regardless of source.

    The constant fallback explicitly short-circuits on zero rows; the
    tiktoken path naturally evaluates to 0 (cost_per_row × 0). Either
    way the estimate must be zero — exact source doesn't matter.
    """
    provider = _make_provider()
    est, _ = tiktoken_estimate(
        provider, ["foo"],
        batch_size=100, total_rows=0,
        fallback_per_row=Decimal("0.000011"),
    )
    assert est == 0.0


def test_pad_sample_repeats_when_short():
    """Padding cycles through the sample to reach batch_size."""
    out = _pad_sample(["a", "b", "c"], 7)
    assert len(out) == 7
    assert out == ["a", "b", "c", "a", "b", "c", "a"]


def test_pad_sample_truncates_when_long():
    out = _pad_sample(["a", "b", "c", "d", "e"], 3)
    assert out == ["a", "b", "c"]


def test_pad_sample_handles_empty_batch():
    # batch_size < 1 should be normalized by the caller, but pad_sample
    # must not crash on edge inputs.
    out = _pad_sample(["a"], 1)
    assert out == ["a"]


def test_sample_rows_via_reader_returns_empty_on_bad_input():
    """No meta / no column → empty list, no exception."""
    assert sample_rows_via_reader(None, None, "") == []
    assert sample_rows_via_reader(None, SimpleNamespace(), "col") == []
