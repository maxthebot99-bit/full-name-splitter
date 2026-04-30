from __future__ import annotations

from typing import Protocol

from ..types import AddressContext


class AddressProvider(Protocol):
    """LLM provider interface for address extraction.

    Different shape from company/name's batched ``clean_batch`` — addresses
    can't be batched into one prompt because each row carries its own ~3.5K
    tokens of HTML. Per-row calls with high concurrency instead.
    """
    name: str
    model: str

    async def extract(self, ctx: AddressContext, html_text: str) -> AddressContext: ...

    def test_connection(self) -> tuple[bool, str]: ...

    def estimate_cost_per_row(self) -> float: ...

    def running_usage(self) -> dict: ...

    def reset_usage(self) -> None: ...
