"""Runtime data types for the address pipeline.

Diverges from company/name's single-string NameContext: an address row has
multiple structured output fields plus a fetch-status carrier so the UI can
show why a row came back blank (FOREIGN vs unreachable vs no-address-on-site).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AddressContext:
    """One row on its way to and from the address pipeline.

    Inputs are ``business_name`` and ``website_url``. Outputs are the seven
    address fields (street/city/state/zip/country/source_url/confidence).
    """
    business_name: str
    website_url: str
    # Output fields — populated after extraction.
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    country: str | None = None
    source_url: str | None = None
    confidence: float = 0.0
    # Operational metadata.
    flags: set[str] = field(default_factory=set)
    is_null: bool = False
    fetch_status: str | None = None  # ok / cloudflare / dead / broken / tls_error / no_response / empty_render
    error: str | None = None  # FOREIGN / CLOUDFLARE / DEAD_DOMAIN / TLS_ERROR / SITE_BROKEN / NO_RESPONSE / EMPTY_RENDER / LLM_UNAVAILABLE

    def flag(self, *flags: str) -> None:
        self.flags.update(flags)

    def has_address(self) -> bool:
        return bool(self.street or self.city or self.state or self.zip)

    @property
    def route(self) -> str:
        """Where this row's verdict came from. Informational for the UI."""
        if self.error:
            return "error"
        if self.has_address():
            return "extracted"
        return "blank"
