from __future__ import annotations

from typing import Protocol

# (first_or_None, last_or_None, short reason string)
SplitOutput = tuple[str | None, str | None, str]

# Backwards-compat alias for anything still importing the original name.
CleanOutput = SplitOutput


class Provider(Protocol):
    name: str
    model: str

    def clean_batch(self, raw_names: list[str]) -> list[SplitOutput]: ...

    def test_connection(self) -> tuple[bool, str]: ...

    def estimate_cost_per_row(self) -> float:
        """USD estimate per row sent to the LLM (input+output tokens combined)."""
        ...
