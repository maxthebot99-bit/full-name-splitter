"""Offline mock provider for stress tests and dogfooding without burning
the real Grok API. Implements the full :class:`Provider` protocol so the
rest of the pipeline can't tell it isn't talking to xAI.

Turn it on with ``CLEANER_MOCK_LLM=1`` (legacy ``COMPANY_CLEANER_MOCK_LLM``
also honored) before launching the app or the stress harness. Tune its
personality with:

- ``CLEANER_MOCK_LATENCY_MS``  default 120. Per-batch sleep.
- ``CLEANER_MOCK_NULL_RATE``   default 0.08. Fraction of inputs returned
  as (None, None).
- ``CLEANER_MOCK_FAIL_RATE``   default 0.0. Per-batch chance of raising
  :class:`ProviderError`.
- ``CLEANER_MOCK_SEED``        default 42. Deterministic RNG.

Splitting logic is intentionally minimal — strip a leading title, split
on whitespace, return (first_tokens, last_token). Good enough to produce
a realistic mix of changed / null rows through the UI pipeline.
"""
from __future__ import annotations

import os
import random
import re
import time

from ..errors import ProviderError
from .base import SplitOutput

_TITLE_RE = re.compile(
    r"^(dr\.?|mr\.?|mrs\.?|ms\.?|mx\.?|prof\.?|sir|dame|rev\.?|hon\.?)\s+",
    re.IGNORECASE,
)
_SUFFIX_RE = re.compile(
    r"\s+(jr\.?|sr\.?|ii|iii|iv|md|phd|esq\.?|cpa|mba|jd|rn)\.?$",
    re.IGNORECASE,
)


def _env_float(name: str, default: float) -> float:
    for n in (name, name.replace("CLEANER_", "COMPANY_CLEANER_")):
        v = os.environ.get(n)
        if v is not None:
            try:
                return float(v)
            except ValueError:
                pass
    return default


def _env_int(name: str, default: int) -> int:
    for n in (name, name.replace("CLEANER_", "COMPANY_CLEANER_")):
        v = os.environ.get(n)
        if v is not None:
            try:
                return int(v)
            except ValueError:
                pass
    return default


def _split_mock(raw: str) -> tuple[str | None, str | None, str]:
    """Cheap heuristic split — title strip, comma reversal, last-token rule."""
    s = (raw or "").strip()
    if not s:
        return (None, None, "mock: blank")
    s = _TITLE_RE.sub("", s)
    s = _SUFFIX_RE.sub("", s)
    s = s.strip(" ,.-")
    if not s:
        return (None, None, "mock: only title/suffix")
    if "," in s:
        last_part, _, first_part = s.partition(",")
        first = first_part.strip() or None
        last = last_part.strip() or None
        return (first, last, "mock: comma-reversed")
    tokens = s.split()
    if len(tokens) == 1:
        return (None, None, "mock: single token")
    return (" ".join(tokens[:-1]), tokens[-1], "mock: last-token rule")


class MockProvider:
    """Drop-in replacement for XAIProvider. Fast, free, deterministic."""

    name = "mock"
    model = "mock-grok"

    def __init__(self) -> None:
        self._latency_ms = _env_int("CLEANER_MOCK_LATENCY_MS", 120)
        self._null_rate = _env_float("CLEANER_MOCK_NULL_RATE", 0.08)
        self._fail_rate = _env_float("CLEANER_MOCK_FAIL_RATE", 0.0)
        self._rng = random.Random(_env_int("CLEANER_MOCK_SEED", 42))
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._api_calls = 0
        self._cost = 0.0

    def clean_batch(self, raw_names: list[str]) -> list[SplitOutput]:
        if self._latency_ms > 0:
            time.sleep(self._latency_ms / 1000.0)
        if self._fail_rate > 0 and self._rng.random() < self._fail_rate:
            raise ProviderError("mock: simulated provider failure")

        self._api_calls += 1
        out: list[SplitOutput] = []
        for raw in raw_names:
            self._prompt_tokens += max(1, len(raw) // 4)
            if self._rng.random() < self._null_rate:
                self._completion_tokens += 2
                out.append((None, None, "mock: flagged for manual review"))
                continue
            first, last, reason = _split_mock(raw)
            self._completion_tokens += max(1, len((first or "") + (last or "")) // 4)
            out.append((first, last, reason))

        # Match XAI's per-1M-token pricing shape so cost numbers in the
        # footer look plausible ($0.20 in / $0.50 out per 1M).
        self._cost = (
            self._prompt_tokens * 0.20 / 1_000_000
            + self._completion_tokens * 0.50 / 1_000_000
        )
        return out

    def test_connection(self) -> tuple[bool, str]:
        return True, "mock: always OK"

    def estimate_cost_per_row(self) -> float:
        return 0.0

    def running_usage(self) -> dict[str, float | int]:
        return {
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "api_calls": self._api_calls,
            "cost": self._cost,
        }

    def reset_usage(self) -> None:
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._api_calls = 0
        self._cost = 0.0
