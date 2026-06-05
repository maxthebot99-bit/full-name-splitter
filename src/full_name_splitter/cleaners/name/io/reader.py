from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pandas as pd

from ..errors import FileReadError
from .format_detect import detect_delimiter, detect_encoding, is_excel


@dataclass
class FileMeta:
    path: Path
    encoding: str
    delimiter: str
    columns: list[str]
    row_count_estimate: int
    sheet: str | None = None


def inspect(path: str | Path, sheet: str | None = None) -> FileMeta:
    p = Path(path)
    if not p.exists():
        raise FileReadError(f"File not found: {p}")
    # Short-circuit zero-byte files with a message humans can read.
    # Pandas' own error ("No columns to parse from file") bubbles into
    # the UI as a confusing raw string; this is the first thing users
    # with a cut-off export from Salesforce or Excel will hit.
    try:
        if p.stat().st_size == 0:
            raise FileReadError(f"File is empty: {p}")
    except OSError as e:
        raise FileReadError(f"Cannot stat {p}: {e}") from e
    if is_excel(p):
        try:
            xl = pd.ExcelFile(p)
            sheet_name = sheet or xl.sheet_names[0]
            df_head = pd.read_excel(xl, sheet_name=sheet_name, nrows=0)
            # Row count: approximate via dimension if we can cheaply load; fallback to shape
            df_est = pd.read_excel(xl, sheet_name=sheet_name, usecols=[0])
            return FileMeta(
                path=p, encoding="binary", delimiter="xlsx",
                columns=list(df_head.columns.astype(str)),
                row_count_estimate=len(df_est),
                sheet=sheet_name,
            )
        except Exception as e:
            raise FileReadError(f"Cannot read Excel file {p}: {e}") from e

    encoding = detect_encoding(p)
    delimiter = detect_delimiter(p, encoding)
    try:
        df_head = pd.read_csv(
            p, nrows=0, encoding=encoding, sep=delimiter, engine="python"
        )
        # Estimate rows by counting lines (minus header). Fast enough for <1GB files.
        with p.open("r", encoding=encoding, errors="replace", newline="") as f:
            rows = sum(1 for _ in f) - 1
        return FileMeta(
            path=p, encoding=encoding, delimiter=delimiter,
            columns=list(df_head.columns.astype(str)),
            row_count_estimate=max(0, rows),
        )
    except Exception as e:
        raise FileReadError(f"Cannot read CSV file {p}: {e}") from e


def guess_name_column(columns: list[str]) -> str | None:
    """Heuristic: pick a column whose name looks like a contact-first-name field."""
    exact = {"first_name", "firstname", "first name"}
    lowered = {c: c.lower().strip() for c in columns}
    for c, low in lowered.items():
        if low in exact:
            return c
    for c, low in lowered.items():
        # partial match — only fire if "first" appears and "last" doesn't
        if "first" in low and "last" not in low:
            return c
    return None


def read_chunks(
    meta: FileMeta,
    column: str,
    chunk_rows: int = 10_000,
    bad_line_cb=None,
) -> Iterator[pd.DataFrame]:
    """Yield DataFrame chunks of the full file (all columns preserved) to keep the
    original columns available for export.

    bad_line_cb: optional callable(line_num: int, fields: list[str], reason: str) invoked
    for each malformed CSV row. If not provided, malformed rows are still counted and
    logged via config.log so the UI can surface them.
    """
    if is_excel(meta.path):
        # openpyxl read-only for memory efficiency
        df = pd.read_excel(meta.path, sheet_name=meta.sheet, dtype=str, keep_default_na=False)
        for start in range(0, len(df), chunk_rows):
            yield df.iloc[start : start + chunk_rows].copy()
        return
    # CSV path
    from ..config import log as _log

    dropped = {"count": 0}

    def _on_bad(fields):
        dropped["count"] += 1
        if bad_line_cb is not None:
            try:
                bad_line_cb(dropped["count"], fields, "field count mismatch")
            except Exception:
                pass
        return None  # drop this row but continue

    try:
        reader = pd.read_csv(
            meta.path,
            encoding=meta.encoding,
            sep=meta.delimiter,
            dtype=str,
            keep_default_na=False,
            chunksize=chunk_rows,
            engine="python",  # tolerates multi-line cells / weird quoting
            on_bad_lines=_on_bad,
        )
    except Exception as e:
        raise FileReadError(f"Error opening CSV reader: {e}") from e
    for chunk in reader:
        yield chunk
    if dropped["count"]:
        _log(f"reader: dropped {dropped['count']} malformed rows from {meta.path}")
