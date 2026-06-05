from __future__ import annotations

import csv
from pathlib import Path

from charset_normalizer import from_bytes

from ..errors import EncodingError, FileReadError

_PREFERRED_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def detect_encoding(path: Path, sample_size: int = 65_536) -> str:
    try:
        with path.open("rb") as f:
            sample = f.read(sample_size)
    except OSError as e:
        raise FileReadError(f"Cannot read {path}: {e}") from e
    if not sample:
        return "utf-8"
    # Try preferred encodings first for speed.
    for enc in _PREFERRED_ENCODINGS:
        try:
            sample.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    detection = from_bytes(sample).best()
    if detection is None:
        raise EncodingError(f"Could not detect encoding for {path}")
    return detection.encoding


def detect_delimiter(path: Path, encoding: str, sample_size: int = 16_384) -> str:
    try:
        with path.open("r", encoding=encoding, errors="replace", newline="") as f:
            sample = f.read(sample_size)
    except OSError as e:
        raise FileReadError(f"Cannot read {path}: {e}") from e
    if not sample:
        return ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def is_excel(path: Path) -> bool:
    return path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}
