"""Offline mock provider for stress tests and dogfooding without burning
the real Grok API. Implements the full :class:`Provider` protocol so the
rest of the pipeline can't tell it isn't talking to xAI.

Turn it on with ``COMPANY_CLEANER_MOCK_LLM=1`` before launching the app
or the stress harness. Tune its personality with:

- ``COMPANY_CLEANER_MOCK_LATENCY_MS``  default 120. Per-batch sleep so
  you can feel realistic streaming instead of instant completion.
- ``COMPANY_CLEANER_MOCK_NULL_RATE``   default 0.08. Fraction of inputs
  the mock returns as ``null``, so the "null" pill and red row state
  get exercised.
- ``COMPANY_CLEANER_MOCK_FAIL_RATE``   default 0.0. Per-batch chance of
  raising :class:`ProviderError` — lets you test the LLM_UNAVAILABLE
  flag + retry path.
- ``COMPANY_CLEANER_MOCK_SEED``        default 42. Deterministic RNG.

Cleaning logic is intentionally minimal — strip trailing LLC/Inc/Ltd
and title-case the result. Good enough to produce a realistic mix of
``changed`` / ``unchanged`` / ``null`` rows through the UI pipeline.
"""
from __future__ import annotations

import os
import random
import re
import time

from ..errors import ProviderError
from .base import CleanOutput

_LEGAL_RE = re.compile(
    r"[\s,]*\b("
    r"l\.?l\.?c|inc|incorporated|corp|corporation|co|company|ltd|limited|"
    r"llp|lllp|plc|p\.?c|l\.?p|holdings|group"
    r")\.?\s*$",
    re.IGNORECASE,
)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _title_case(s: str) -> str:
    # Preserve obvious stylizations so the "unchanged" path gets exercised
    # on things like eBay, iHeart — matches the real prompt's behavior.
    stylized = {"ebay", "iheart", "ipipeline", "mcdonald's", "3m", "ibm", "pwc"}
    if s.lower() in stylized:
        table = {"ebay": "eBay", "iheart": "iHeart", "ipipeline": "iPipeline",
                 "mcdonald's": "McDonald's", "3m": "3M", "ibm": "IBM", "pwc": "PwC"}
        return table[s.lower()]
    return " ".join(w[:1].upper() + w[1:].lower() for w in s.split() if w)


class MockProvider:
    """Drop-in replacement for XAIProvider. Fast, free, deterministic."""

    name = "mock"
    model = "mock-grok"

    def __init__(self) -> None:
        self._latency_ms = _env_int("COMPANY_CLEANER_MOCK_LATENCY_MS", 120)
        self._null_rate = _env_float("COMPANY_CLEANER_MOCK_NULL_RATE", 0.08)
        self._fail_rate = _env_float("COMPANY_CLEANER_MOCK_FAIL_RATE", 0.0)
        self._rng = random.Random(_env_int("COMPANY_CLEANER_MOCK_SEED", 42))
        # Mirrors XAIProvider's running_usage() contract so the UI's
        # telemetry footer shows tokens + cost like it would in a real run.
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._api_calls = 0
        self._cost = 0.0

    def clean_batch(self, raw_names: list[str]) -> list[CleanOutput]:
        if self._latency_ms > 0:
            time.sleep(self._latency_ms / 1000.0)
        if self._fail_rate > 0 and self._rng.random() < self._fail_rate:
            raise ProviderError("mock: simulated provider failure")

        self._api_calls += 1
        out: list[CleanOutput] = []
        for raw in raw_names:
            # Rough token accounting so the footer's tokens-in/out numbers
            # tick along with real-world-ish ratios (~1 token per 4 chars).
            self._prompt_tokens += max(1, len(raw) // 4)
            stripped = _LEGAL_RE.sub("", raw or "").strip(" ,.-")
            if not stripped or len(stripped) < 2:
                self._completion_tokens += 1
                out.append((None, "mock: below length floor"))
                continue
            if self._rng.random() < self._null_rate:
                self._completion_tokens += 1
                out.append((None, "mock: flagged for manual review"))
                continue
            cleaned = _title_case(stripped)
            self._completion_tokens += max(1, len(cleaned) // 4)
            reason = "mock: unchanged" if cleaned == raw else "mock: normalized"
            out.append((cleaned, reason))

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
