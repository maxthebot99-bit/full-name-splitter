"""Tests for the ``fullname`` cleaner kind — response parser + writer.

These tests cover the Phase B data-shape changes that distinguish the
splitter from the original ``name`` kind:
  * The Grok response shape is ``{outputs: [{first, last, why}, ...]}``.
  * Per-row malformed items degrade to ``(None, None, "")`` without
    crashing the whole batch.
  * The writer emits two new columns (``First Name`` / ``Last Name``)
    instead of one ``__cleaned`` column, with empty strings (not the
    literal "None") for null parts.
  * A golden-fixture CSV documents the splitter's expected end-to-end
    behavior on dirty real-world rows.

Real Grok calls are NOT exercised here — those are integration tests
that depend on a live API key and cost money.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from full_name_splitter.cleaners.fullname.io.writer import build_export_df
from full_name_splitter.cleaners.fullname.llm._openai_compat import _parse_outputs
from full_name_splitter.cleaners.fullname.types import (
    FIRST_COLUMN,
    LAST_COLUMN,
    NameContext,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dirty_names_golden.csv"


# ─── _parse_outputs ──────────────────────────────────────────────────────────


def _wrap_outputs(items: list[dict]) -> str:
    """Serialize a list of per-row items as the {"outputs": [...]} envelope."""
    return json.dumps({"outputs": items})


def test_parse_outputs_basic_split():
    """Happy path: a single {first, last, why} item parses cleanly."""
    content = _wrap_outputs([{"first": "John", "last": "Smith", "why": "no change needed"}])
    result = _parse_outputs(content, expected_n=1)
    assert result == [("John", "Smith", "no change needed")]


def test_parse_outputs_null_pair():
    """A null/null item (JSON null) lands as (None, None, why)."""
    content = _wrap_outputs([{"first": None, "last": None, "why": "null: mononym"}])
    result = _parse_outputs(content, expected_n=1)
    assert result == [(None, None, "null: mononym")]


def test_parse_outputs_null_string_sentinel():
    """The literal string "null" is treated the same as JSON null."""
    content = _wrap_outputs([{"first": "null", "last": "null", "why": "null: unparseable"}])
    result = _parse_outputs(content, expected_n=1)
    assert result == [(None, None, "null: unparseable")]


def test_parse_outputs_batch_mixed():
    """A batch of rows preserves order and per-row independence."""
    content = _wrap_outputs([
        {"first": "John", "last": "Smith", "why": "no change needed"},
        {"first": None, "last": None, "why": "null: mononym"},
        {"first": "Mary Jane", "last": "Watson", "why": "stripped title and suffix"},
    ])
    result = _parse_outputs(content, expected_n=3)
    assert result == [
        ("John", "Smith", "no change needed"),
        (None, None, "null: mononym"),
        ("Mary Jane", "Watson", "stripped title and suffix"),
    ]


def test_parse_outputs_malformed_row_in_batch():
    """One malformed item degrades to (None, None, "") — others unaffected."""
    content = _wrap_outputs([
        {"first": "John", "last": "Smith", "why": "ok"},
        # Missing "last" key — primary shape says "first" or "last" exists,
        # so this still parses as first=John, last=None.
        {"first": "John", "why": "missing last"},
        # Bare string item — not a dict; degrades to (None, None, "").
        "garbage",
        {"first": "Mary", "last": "Watson", "why": "ok"},
    ])
    result = _parse_outputs(content, expected_n=4)
    assert result == [
        ("John", "Smith", "ok"),
        ("John", None, "missing last"),
        (None, None, ""),
        ("Mary", "Watson", "ok"),
    ]


def test_parse_outputs_strips_code_fence():
    """Tolerant of ```json ... ``` fences (some models add them)."""
    inner = json.dumps({"outputs": [{"first": "John", "last": "Smith", "why": "ok"}]})
    content = f"```json\n{inner}\n```"
    result = _parse_outputs(content, expected_n=1)
    assert result == [("John", "Smith", "ok")]


def test_parse_outputs_length_mismatch_raises():
    """Length mismatch is the one error condition that can't degrade —
    the pipeline relies on positional zip with the request batch."""
    from full_name_splitter.cleaners.fullname.errors import ProviderBadResponseError

    content = _wrap_outputs([{"first": "John", "last": "Smith", "why": "ok"}])
    with pytest.raises(ProviderBadResponseError):
        _parse_outputs(content, expected_n=2)


# ─── writer ──────────────────────────────────────────────────────────────────


def _make_ctx(*, first=None, last=None, original="", reason="", is_null=None) -> NameContext:
    ctx = NameContext(original=original, current="", first=first, last=last)
    ctx.llm_reason = reason
    if is_null is None:
        ctx.is_null = first is None and last is None
    else:
        ctx.is_null = is_null
    return ctx


def test_writer_adds_first_and_last_columns():
    """build_export_df appends "First Name" and "Last Name" columns."""
    df = pd.DataFrame({"contact": ["John Smith", "Mary Watson"]})
    ctxs = [
        _make_ctx(first="John", last="Smith", original="John Smith", reason="ok"),
        _make_ctx(first="Mary", last="Watson", original="Mary Watson", reason="ok"),
    ]
    out = build_export_df(df, "contact", ctxs)
    assert FIRST_COLUMN in out.columns
    assert LAST_COLUMN in out.columns
    assert out[FIRST_COLUMN].tolist() == ["John", "Mary"]
    assert out[LAST_COLUMN].tolist() == ["Smith", "Watson"]


def test_writer_uses_empty_string_for_null_parts():
    """A null first/last writes as "" — never the literal "None" string."""
    df = pd.DataFrame({"contact": ["Madonna", "John Smith"]})
    ctxs = [
        _make_ctx(first=None, last=None, original="Madonna", reason="null: mononym"),
        _make_ctx(first="John", last="Smith", original="John Smith", reason="ok"),
    ]
    out = build_export_df(df, "contact", ctxs)
    assert out[FIRST_COLUMN].tolist() == ["", "John"]
    assert out[LAST_COLUMN].tolist() == ["", "Smith"]
    # And NOT the string "None" — that's the bug we're guarding against.
    assert "None" not in set(out[FIRST_COLUMN].tolist())
    assert "None" not in set(out[LAST_COLUMN].tolist())


def test_writer_preserves_source_columns():
    """Original columns must survive — the export is additive."""
    df = pd.DataFrame({
        "id": [1, 2],
        "contact": ["John Smith", "Madonna"],
        "extra": ["x", "y"],
    })
    ctxs = [
        _make_ctx(first="John", last="Smith", original="John Smith"),
        _make_ctx(first=None, last=None, original="Madonna"),
    ]
    out = build_export_df(df, "contact", ctxs)
    assert list(out.columns)[:3] == ["id", "contact", "extra"]
    assert out["id"].tolist() == [1, 2]


def test_writer_is_null_column():
    """is_null column is True iff BOTH parts are null."""
    df = pd.DataFrame({"contact": ["John Smith", "Madonna"]})
    ctxs = [
        _make_ctx(first="John", last="Smith", original="John Smith"),
        _make_ctx(first=None, last=None, original="Madonna"),
    ]
    out = build_export_df(df, "contact", ctxs)
    assert out["contact__is_null"].tolist() == [False, True]


def test_writer_overrides_pair_format():
    """Per-row overrides are (first, last) tuples — either part can be None."""
    df = pd.DataFrame({"contact": ["John Smith", "Mary Watson"]})
    ctxs = [
        _make_ctx(first="John", last="Smith", original="John Smith"),
        _make_ctx(first="Mary", last="Watson", original="Mary Watson"),
    ]
    overrides = {1: ("Mary Jane", "Watson")}
    out = build_export_df(df, "contact", ctxs, overrides=overrides)
    assert out[FIRST_COLUMN].tolist() == ["John", "Mary Jane"]
    assert out[LAST_COLUMN].tolist() == ["Smith", "Watson"]


def test_writer_length_mismatch_raises():
    df = pd.DataFrame({"contact": ["John Smith", "Mary Watson"]})
    ctxs = [_make_ctx(first="John", last="Smith", original="John Smith")]
    with pytest.raises(ValueError, match="contexts length mismatch"):
        build_export_df(df, "contact", ctxs)


# ─── golden fixture sanity ───────────────────────────────────────────────────


def test_golden_fixture_loadable():
    """The golden CSV exists, parses, and has the expected columns + rowcount."""
    assert FIXTURE_PATH.exists(), f"missing fixture: {FIXTURE_PATH}"
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 28, f"expected 28 fixture rows, got {len(rows)}"
    assert set(rows[0].keys()) == {"full_name", "expected_first", "expected_last"}
    # Spot-check a few known rows.
    by_input = {r["full_name"]: r for r in rows}
    assert by_input["John Smith"]["expected_first"] == "John"
    assert by_input["John Smith"]["expected_last"] == "Smith"
    assert by_input["Madonna"]["expected_first"] == ""
    assert by_input["Madonna"]["expected_last"] == ""


def test_writer_round_trip_against_fixture():
    """Feed the golden expected values straight into the writer and confirm
    the output CSV matches what a real pipeline run would produce. This
    verifies the writer doesn't mangle accents, hyphens, particles, or
    apostrophes — the failure modes most likely to bite on real data."""
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    df = pd.DataFrame([{"full_name": r["full_name"]} for r in rows])
    ctxs = [
        _make_ctx(
            first=(r["expected_first"] or None),
            last=(r["expected_last"] or None),
            original=r["full_name"],
        )
        for r in rows
    ]
    out = build_export_df(df, "full_name", ctxs)
    assert out[FIRST_COLUMN].tolist() == [r["expected_first"] for r in rows]
    assert out[LAST_COLUMN].tolist() == [r["expected_last"] for r in rows]
    # Spot-check that accented characters survive.
    elodie_idx = next(i for i, r in enumerate(rows) if r["full_name"] == "Élodie Dubois")
    assert out[FIRST_COLUMN].iloc[elodie_idx] == "Élodie"
    assert out[LAST_COLUMN].iloc[elodie_idx] == "Dubois"
