"""Runtime data types for the pure-Grok pipeline.

Historically this lived at ``deterministic/base.py`` alongside a rule-trace
framework. Now that Grok is the only decision-maker and no deterministic
rules run at runtime, the extra machinery (RuleTrace, apply(), leakage_type)
has been removed. What's left is the minimal envelope the pipeline and UI
need to describe a single row.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NameContext:
    """One row on its way to and from Grok.

    ``original`` never changes. ``current`` holds whatever Grok returned
    (or the raw input before Grok has run). ``flags`` is a grab-bag of
    pipeline metadata like ``LLM_UNAVAILABLE`` or ``NEEDS_MANUAL_REVIEW``
    — these are operational signals, not cleaning decisions.
    """
    original: str
    current: str
    flags: set[str] = field(default_factory=set)
    confidence: float = 1.0
    is_null: bool = False
    # Populated after Grok (or cache replay) has answered.
    llm_prompt: str | None = None
    llm_response: str | None = None
    llm_reason: str | None = None  # short 'why' returned alongside cleaned name

    def flag(self, *flags: str) -> None:
        self.flags.update(flags)

    @property
    def route(self) -> str:
        """Where this row's verdict came from. Purely informational for the UI.

        - ``"null"`` — Grok returned null (or Grok was unreachable and we
          have no answer).
        - ``"llm"`` — Grok returned a cleaned name.
        - ``"pending"`` — no verdict yet (provider unwired, or the row is
          queued for a reprocess pass).
        """
        if self.is_null:
            return "null"
        if self.llm_response is not None:
            return "llm"
        return "pending"
