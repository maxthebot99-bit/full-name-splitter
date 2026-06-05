"""File reader for the address tab.

Same chunked-DataFrame shape as company/io/reader.py — yields full chunks so
the worker can pull both the business-name column AND the website-url column
from each row. The ``column`` parameter passed by the worker is the website
URL column (the primary input). The secondary business-name column is
available on every yielded DataFrame chunk too.
"""
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
        with p.open("r", encoding=encoding, errors="replace", newline="") as f:
            rows = sum(1 for _ in f) - 1
        return FileMeta(
            path=p, encoding=encoding, delimiter=delimiter,
            columns=list(df_head.columns.astype(str)),
            row_count_estimate=max(0, rows),
        )
    except Exception as e:
        raise FileReadError(f"Cannot read CSV file {p}: {e}") from e


def read_chunks(
    meta: FileMeta,
    column: str,
    chunk_rows: int = 5_000,
    bad_line_cb=None,
) -> Iterator[pd.DataFrame]:
    """Yield DataFrame chunks. Same contract as company/io/reader.py.

    ``column`` is unused for actual filtering (we yield full chunks); it's
    kept for signature parity with the company reader so the worker
    dispatcher can call this without branching.
    """
    if is_excel(meta.path):
        df = pd.read_excel(
            meta.path, sheet_name=meta.sheet, dtype=str, keep_default_na=False
        )
        for start in range(0, len(df), chunk_rows):
            yield df.iloc[start : start + chunk_rows].copy()
        return

    from ..config import log as _log

    dropped = {"count": 0}

    def _on_bad(fields):
        dropped["count"] += 1
        if bad_line_cb is not None:
            try:
                bad_line_cb(dropped["count"], fields, "field count mismatch")
            except Exception:
                pass
        return None

    try:
        reader = pd.read_csv(
            meta.path,
            encoding=meta.encoding,
            sep=meta.delimiter,
            dtype=str,
            keep_default_na=False,
            chunksize=chunk_rows,
            engine="python",
            on_bad_lines=_on_bad,
        )
    except Exception as e:
        raise FileReadError(f"Error opening CSV reader: {e}") from e
    for chunk in reader:
        yield chunk
    if dropped["count"]:
        _log(f"reader: dropped {dropped['count']} malformed rows from {meta.path}")
