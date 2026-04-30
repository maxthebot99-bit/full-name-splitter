"""Country scope filter — gates which countries we ship addresses for."""
from __future__ import annotations


# US + Canada + US territories. Anything else gets nulled and flagged FOREIGN.
ALLOWED_COUNTRIES = {"US", "CA", "PR", "GU", "VI", "AS", "MP", "UM"}

COUNTRY_NORMALIZE = {
    "USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US",
    "CANADA": "CA",
    "PUERTO RICO": "PR",
    "GUAM": "GU",
    "U.S. VIRGIN ISLANDS": "VI", "US VIRGIN ISLANDS": "VI", "VIRGIN ISLANDS": "VI",
    "AMERICAN SAMOA": "AS",
    "NORTHERN MARIANA ISLANDS": "MP",
}


def normalize_country(c: str | None) -> str | None:
    """Normalize a country string to an uppercase ISO code where possible."""
    if not c:
        return None
    upper = c.strip().upper()
    return COUNTRY_NORMALIZE.get(upper, upper)


def is_in_scope(country: str | None) -> bool:
    """True if the country is null/unknown (allow through) or in ALLOWED_COUNTRIES."""
    n = normalize_country(country)
    if n is None:
        return True  # allow partial in-scope addresses where LLM didn't fill country
    return n in ALLOWED_COUNTRIES
