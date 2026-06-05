"""Runtime data types for the full-name splitter pipeline.

Forked from the cleaners-hub ``name`` kind. Where the original ``name``
cleaner returned a single cleaned first-name string per row, the splitter
emits TWO fields per row: ``first`` and ``last`` (each str or None). The
context object carries both alongside the legacy ``current`` mirror so
the existing single-string SSE/UI plumbing (``workers._ctx_to_row`` etc.)
keeps working without a parallel codepath.

The class name ``NameContext`` is preserved so the kind dispatcher
(``workers._modules_for``) can keep using a uniform attribute reference.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Output column names used by the writer. The Splitter SOP asks for
# "First Name" / "Last Name" — title-case, space-separated — to match
# Salesforce/HubSpot conventions.
FIRST_COLUMN = "First Name"
LAST_COLUMN = "Last Name"


@dataclass
class NameContext:
    """One row on its way to and from Grok.

    ``original`` never changes — it's the raw cell from the sheet.

    ``first`` / ``last`` hold the parsed name parts once Grok answers
    (or stay None if Grok returned null or the row never ran).

    ``current`` is a convenience mirror — "<first> <last>" with empty
    parts collapsed — so the legacy single-string row payload code
    (``workers._ctx_to_row``) can serialize a Splitter context without
    needing a parallel branch. The writer never reads ``current``; it
    reads ``first`` / ``last`` directly.

    ``is_null`` is True iff BOTH ``first`` and ``last`` are None (or the
    Grok response was the null sentinel). Mirrors the ``name`` kind's
    null-row semantics for the UI's red-row state.
    """
    original: str
    current: str = ""
    first: str | None = None
    last: str | None = None
    flags: set[str] = field(default_factory=set)
    confidence: float = 1.0
    is_null: bool = False
    # Populated after Grok (or cache replay) has answered.
    llm_prompt: str | None = None
    llm_response: str | None = None
    llm_reason: str | None = None  # short 'why' returned alongside the split

    def flag(self, *flags: str) -> None:
        self.flags.update(flags)

    @property
    def route(self) -> str:
        """Where this row's verdict came from. Purely informational for the UI.

        - ``"null"`` — Grok returned null for both parts (or Grok was
          unreachable and we have no answer).
        - ``"llm"`` — Grok returned a usable split.
        - ``"pending"`` — no verdict yet (provider unwired, or the row is
          queued for a reprocess pass).
        """
        if self.is_null:
            return "null"
        if self.llm_response is not None:
            return "llm"
        return "pending"
