from __future__ import annotations

from pathlib import Path

import csv

import pandas as pd

from ..types import FIRST_COLUMN, LAST_COLUMN, NameContext


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
    overrides: dict[int, tuple[str | None, str | None]] | None = None,
) -> pd.DataFrame:
    """Append First Name / Last Name (plus is_null + grok_reason) columns.

    Different shape from the original ``name`` writer: instead of one
    ``<col>__cleaned`` column we emit two — ``First Name`` and
    ``Last Name`` — so downstream CRMs can map them directly.

    ``overrides``: mapping row index → (first_override, last_override).
    Either value can be None to clear that part. The override format is
    deliberately a pair, not a single string, because the splitter
    operates on two independent fields.

    None values are written as empty strings (never the literal "None").
    The is_null flag is True iff BOTH parts are null (mirrors the
    NameContext.is_null semantics).
    """
    if len(contexts) != len(source_df):
        raise ValueError("contexts length mismatch with source_df")
    overrides = overrides or {}
    firsts: list[str] = []
    lasts: list[str] = []
    is_null: list[bool] = []
    grok_reason: list[str] = []
    for i, ctx in enumerate(contexts):
        f_val: str | None
        l_val: str | None
        if i in overrides:
            f_val, l_val = overrides[i]
            null_flag = (not f_val) and (not l_val)
        else:
            f_val = ctx.first
            l_val = ctx.last
            null_flag = ctx.is_null
        firsts.append(_sanitize_csv_value(f_val or ""))
        lasts.append(_sanitize_csv_value(l_val or ""))
        is_null.append(bool(null_flag))
        grok_reason.append(_sanitize_csv_value((ctx.llm_reason or "").strip()))
    out = source_df.copy()
    out[FIRST_COLUMN] = firsts
    out[LAST_COLUMN] = lasts
    out[f"{name_column}__is_null"] = is_null
    out[f"{name_column}__grok_reason"] = grok_reason
    return out


def write_csv(df: pd.DataFrame, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
