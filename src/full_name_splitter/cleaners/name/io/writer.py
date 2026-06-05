from __future__ import annotations

from pathlib import Path

import csv

import pandas as pd

from ..types import NameContext


def _sanitize_csv_value(s: str) -> str:
    """See company/io/writer.py for the rationale — same logic.

    Strips control chars and prepends a quote to formula-injection prefixes.
    """
    if not s:
        return s
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
    name_column: str,
    contexts: list[NameContext],
    overrides: dict[int, str] | None = None,
) -> pd.DataFrame:
    """Append cleaned columns to the source dataframe, preserving all originals.

    overrides: mapping of row index (0-based in source_df.index order) → user-edited
    cleaned value. Wins over LLM/deterministic output. Both LLM and
    override values pass through _sanitize_csv_value before serialization.
    """
    if len(contexts) != len(source_df):
        raise ValueError("contexts length mismatch with source_df")
    overrides = overrides or {}
    cleaned = []
    is_null = []
    grok_reason = []
    for i, ctx in enumerate(contexts):
        if i in overrides:
            val = overrides[i]
            null_flag = (val == "") or (val.strip().lower() == "null")
        else:
            val = ctx.current
            null_flag = ctx.is_null
            if null_flag:
                val = ""
        cleaned.append(_sanitize_csv_value(val))
        is_null.append(bool(null_flag))
        grok_reason.append(_sanitize_csv_value((ctx.llm_reason or "").strip()))
    out = source_df.copy()
    out[f"{name_column}__cleaned"] = cleaned
    out[f"{name_column}__is_null"] = is_null
    out[f"{name_column}__grok_reason"] = grok_reason
    return out


def write_csv(df: pd.DataFrame, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
