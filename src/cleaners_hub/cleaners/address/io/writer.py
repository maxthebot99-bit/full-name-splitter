"""Address-tab CSV writer.

Writes seven output columns per row (street/city/state/zip/country, plus
source_url and confidence) prefixed by the website-url column name, plus
a single ``<website>__address_error`` column carrying the failure tag
(FOREIGN, CLOUDFLARE, DEAD_DOMAIN, etc.) for rows that didn't yield an
address. Mirrors the company writer's per-cell sanitization for CSV
formula-injection defense.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from ..types import AddressContext


# Output column suffixes — appended to the website URL column name.
SUFFIXES = (
    "__address_street",
    "__address_city",
    "__address_state",
    "__address_zip",
    "__address_country",
    "__address_source_url",
    "__address_confidence",
    "__address_error",
)


def _sanitize_csv_value(s: str | None) -> str:
    """Defang formula-injection + control chars before serialization."""
    if not s:
        return ""
    out_chars = []
    for ch in s:
        code = ord(ch)
        if code in (9, 10, 13):
            out_chars.append(" ")
        elif code < 32:
            continue
        else:
            out_chars.append(ch)
    cleaned = "".join(out_chars)
    if cleaned and cleaned[0] in ("=", "@", "+", "-"):
        cleaned = "'" + cleaned
    return cleaned


def build_export_df(
    source_df: pd.DataFrame,
    website_column: str,
    contexts: list[AddressContext],
    overrides: dict[int, dict] | None = None,
) -> pd.DataFrame:
    """Append 8 cleaned columns to the source DataFrame.

    The output columns are prefixed with the website column name (e.g.
    ``Company Website__address_street``) for easy CRM mapping.

    overrides: optional mapping of row-index → dict of partial fields
    (e.g. {"street": "...", "city": "..."}) for hand-corrections. Provided
    fields win over the LLM extraction; unspecified fields fall through.
    """
    if len(contexts) != len(source_df):
        raise ValueError("contexts length mismatch with source_df")
    overrides = overrides or {}

    cols: dict[str, list[str | float]] = {f"{website_column}{s}": [] for s in SUFFIXES}

    for i, ctx in enumerate(contexts):
        ov = overrides.get(i, {}) or {}
        street = ov.get("street", ctx.street) or ""
        city = ov.get("city", ctx.city) or ""
        state = ov.get("state", ctx.state) or ""
        zip_ = ov.get("zip", ctx.zip) or ""
        country = ov.get("country", ctx.country) or ""
        source_url = ov.get("source_url", ctx.source_url) or ""
        confidence = float(ov.get("confidence", ctx.confidence) or 0.0)
        error = ctx.error or ""

        cols[f"{website_column}__address_street"].append(_sanitize_csv_value(street))
        cols[f"{website_column}__address_city"].append(_sanitize_csv_value(city))
        cols[f"{website_column}__address_state"].append(_sanitize_csv_value(state))
        cols[f"{website_column}__address_zip"].append(_sanitize_csv_value(zip_))
        cols[f"{website_column}__address_country"].append(_sanitize_csv_value(country))
        cols[f"{website_column}__address_source_url"].append(_sanitize_csv_value(source_url))
        cols[f"{website_column}__address_confidence"].append(round(confidence, 2))
        cols[f"{website_column}__address_error"].append(_sanitize_csv_value(error))

    out = source_df.copy()
    for col, vals in cols.items():
        out[col] = vals
    return out


def write_csv(df: pd.DataFrame, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
