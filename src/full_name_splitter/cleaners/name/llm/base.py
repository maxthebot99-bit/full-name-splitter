from __future__ import annotations

from typing import Protocol

# (cleaned_or_None, short reason string)
CleanOutput = tuple[str | None, str]


class Provider(Protocol):
    name: str
    model: str

    def clean_batch(self, raw_names: list[str]) -> list[CleanOutput]: ...

    def test_connection(self) -> tuple[bool, str]: ...

    def estimate_cost_per_row(self) -> float:
        """USD estimate per row sent to the LLM (input+output tokens combined)."""
        ...
