from __future__ import annotations

from pathlib import Path

import csv

import pandas as pd

from ..types import NameContext


def build_export_df(
    source_df: pd.DataFrame,
    name_column: str,
    contexts: list[NameContext],
    overrides: dict[int, str] | None = None,
) -> pd.DataFrame:
    """Append cleaned columns to the source dataframe, preserving all originals.

    overrides: mapping of row index (0-based in source_df.index order) → user-edited
    cleaned value. Wins over LLM/deterministic output.
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
        cleaned.append(val)
        is_null.append(bool(null_flag))
        grok_reason.append((ctx.llm_reason or "").strip())
    out = source_df.copy()
    out[f"{name_column}__cleaned"] = cleaned
    out[f"{name_column}__is_null"] = is_null
    out[f"{name_column}__grok_reason"] = grok_reason
    return out


def write_csv(df: pd.DataFrame, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
