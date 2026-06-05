"""Phase C tests for the override + dropNull plumbing.

These cover the data-shape changes that landed alongside the splitter UI:

  * ``OverrideBody`` now carries ``{first, last}`` instead of ``{cleaned}``.
    Either field can be null/empty. Both empty clears the override.
  * ``apply_override`` writes ``(first, last)`` tuples into
    ``session.overrides``, matching what the splitter writer expects.
  * ``GET /api/download/{sid}?dropNull=1`` filters out rows where BOTH
    First Name and Last Name cells are empty (the splitter's null sentinel).

Tests use the real FastAPI app via ``TestClient`` so the wiring through
the Pydantic body + the override route + the download route is exercised
end to end. No Grok calls — sessions are seeded by hand with a synthetic
``NameContext`` list and a pre-written result CSV.
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from full_name_splitter.cleaners.fullname.io.writer import build_export_df
from full_name_splitter.cleaners.fullname.types import NameContext
from full_name_splitter.main import app
from full_name_splitter.sessions import store


CSRF = {"X-Requested-With": "full-name-splitter"}


# ─── helpers ────────────────────────────────────────────────────────────


def _make_ctx(*, first=None, last=None, original="") -> NameContext:
    ctx = NameContext(original=original, current="", first=first, last=last)
    ctx.is_null = first is None and last is None
    return ctx


def _seed_done_session(tmp_path: Path, contexts, source_df: pd.DataFrame,
                       *, column: str = "full_name") -> str:
    """Create a session that looks like a completed run, with the result CSV
    already written. Returns the sid."""
    loop = asyncio.new_event_loop()
    try:
        sess = store.create(kind="fullname", email="anonymous", loop=loop)
        sess.selected_column = column
        sess.contexts = list(contexts)
        sess.source_df = source_df
        sess.state = "done"
        out_path = sess.output_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df_out = build_export_df(source_df, column, list(contexts))
        df_out.to_csv(out_path, index=False, encoding="utf-8-sig")
        sess.result_csv_path = out_path
        sess.result_row_count = len(contexts)
        return sess.sid
    finally:
        # Drop the loop ref — the worker thread isn't running, the session
        # just needs the loop attribute set so the SSE machinery doesn't
        # crash if something tries to push.
        pass


# ─── OverrideBody shape ─────────────────────────────────────────────────


def test_override_body_accepts_first_and_last(tmp_path):
    client = TestClient(app)
    contexts = [
        _make_ctx(first="John", last="Smith", original="John Smith"),
        _make_ctx(first="Mary", last="Watson", original="Mary Watson"),
    ]
    df = pd.DataFrame({"full_name": ["John Smith", "Mary Watson"]})
    sid = _seed_done_session(tmp_path, contexts, df)

    r = client.post(
        f"/api/rows/{sid}/2",
        json={"first": "Mary Jane", "last": "Watson"},
        headers=CSRF,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["first"] == "Mary Jane"
    assert body["last"] == "Watson"
    assert body["clean"] == "Mary Jane Watson"
    assert body["status"] == "changed"
    # Session state — overrides dict stores the tuple.
    sess = store.get(sid)
    assert sess is not None
    assert sess.overrides[1] == ("Mary Jane", "Watson")


def test_override_body_allows_null_last(tmp_path):
    """A mononym override: first='Madonna', last=None — last cell goes empty."""
    client = TestClient(app)
    contexts = [_make_ctx(first="Madonna", last=None, original="Madonna")]
    df = pd.DataFrame({"full_name": ["Madonna"]})
    sid = _seed_done_session(tmp_path, contexts, df)

    r = client.post(
        f"/api/rows/{sid}/1",
        json={"first": "Madonna", "last": None},
        headers=CSRF,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["first"] == "Madonna"
    assert body["last"] is None
    sess = store.get(sid)
    assert sess is not None
    assert sess.overrides[0] == ("Madonna", None)


def test_override_body_both_null_clears_override(tmp_path):
    """Both first and last empty → override is removed entirely."""
    client = TestClient(app)
    contexts = [_make_ctx(first="John", last="Smith", original="John Smith")]
    df = pd.DataFrame({"full_name": ["John Smith"]})
    sid = _seed_done_session(tmp_path, contexts, df)

    # Plant an override first.
    r = client.post(
        f"/api/rows/{sid}/1",
        json={"first": "Jonathan", "last": "Smith"},
        headers=CSRF,
    )
    assert r.status_code == 200
    sess = store.get(sid)
    assert sess is not None and 0 in sess.overrides

    # Clear it.
    r = client.post(
        f"/api/rows/{sid}/1",
        json={"first": None, "last": None},
        headers=CSRF,
    )
    assert r.status_code == 200
    sess = store.get(sid)
    assert sess is not None and 0 not in sess.overrides


def test_override_rejects_legacy_cleaned_field(tmp_path):
    """The old ``{cleaned: str}`` body is no longer the supported shape —
    the splitter expects ``{first, last}``. A legacy ``cleaned`` field is
    silently ignored (Pydantic extra fields default to ignore), first/last
    default to None, and the route treats that as "clear override". Any
    existing Grok context for the row remains untouched.

    Documents the migration boundary: old callers must move to {first, last}.
    """
    client = TestClient(app)
    contexts = [_make_ctx(first="John", last="Smith", original="John Smith")]
    df = pd.DataFrame({"full_name": ["John Smith"]})
    sid = _seed_done_session(tmp_path, contexts, df)

    r = client.post(
        f"/api/rows/{sid}/1",
        json={"cleaned": "John Smith"},
        headers=CSRF,
    )
    assert r.status_code == 200
    # The override was treated as "clear" (no override stored). The
    # response payload reflects the existing Grok context, not the legacy
    # value.
    sess = store.get(sid)
    assert sess is not None
    assert 0 not in sess.overrides
    body = r.json()
    # Existing Grok context still wins.
    assert body["first"] == "John"
    assert body["last"] == "Smith"


# ─── /api/download dropNull ────────────────────────────────────────────


def test_download_returns_full_csv_without_dropnull(tmp_path):
    """No dropNull param → full file, every row preserved."""
    client = TestClient(app)
    contexts = [
        _make_ctx(first="John", last="Smith", original="John Smith"),
        _make_ctx(first=None, last=None, original="Madonna"),
        _make_ctx(first="Mary", last="Watson", original="Mary Watson"),
    ]
    df = pd.DataFrame({
        "full_name": ["John Smith", "Madonna", "Mary Watson"],
    })
    sid = _seed_done_session(tmp_path, contexts, df)

    r = client.get(f"/api/download/{sid}", headers=CSRF)
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    lines = [ln for ln in text.splitlines() if ln]
    # Header + 3 rows.
    assert len(lines) == 4
    # Madonna row preserved with empty First/Last cells.
    assert "Madonna" in text


def test_download_dropnull_filters_both_empty_rows(tmp_path):
    """?dropNull=1 → rows where both First Name and Last Name are empty drop."""
    client = TestClient(app)
    contexts = [
        _make_ctx(first="John", last="Smith", original="John Smith"),
        _make_ctx(first=None, last=None, original="Madonna"),
        _make_ctx(first="Mary", last="Watson", original="Mary Watson"),
        _make_ctx(first=None, last=None, original="???"),
    ]
    df = pd.DataFrame({
        "full_name": ["John Smith", "Madonna", "Mary Watson", "???"],
    })
    sid = _seed_done_session(tmp_path, contexts, df)

    r = client.get(f"/api/download/{sid}?dropNull=1", headers=CSRF)
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    lines = [ln for ln in text.splitlines() if ln]
    # Header + 2 surviving rows.
    assert len(lines) == 3
    # The null-name originals were dropped.
    assert "Madonna" not in text
    assert "???" not in text
    # The real splits stayed.
    assert "John" in text and "Smith" in text
    assert "Mary" in text and "Watson" in text


def test_download_dropnull_keeps_partial_split(tmp_path):
    """A row with first=X, last=None is NOT dropped (only one cell is empty)."""
    client = TestClient(app)
    contexts = [
        _make_ctx(first="Madonna", last=None, original="Madonna"),
        _make_ctx(first=None, last=None, original="??"),
    ]
    df = pd.DataFrame({"full_name": ["Madonna", "??"]})
    sid = _seed_done_session(tmp_path, contexts, df)

    r = client.get(f"/api/download/{sid}?dropNull=1", headers=CSRF)
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert "Madonna" in text
    assert "??" not in text


def test_download_filename_changes_with_dropnull(tmp_path):
    """The Content-Disposition filename signals the drop-null variant."""
    client = TestClient(app)
    contexts = [_make_ctx(first="John", last="Smith", original="John Smith")]
    df = pd.DataFrame({"full_name": ["John Smith"]})
    sid = _seed_done_session(tmp_path, contexts, df)

    r_plain = client.get(f"/api/download/{sid}", headers=CSRF)
    assert r_plain.status_code == 200
    assert "__cleaned.csv" in r_plain.headers.get("content-disposition", "")
    assert "dropnull" not in r_plain.headers.get("content-disposition", "").lower()

    r_drop = client.get(f"/api/download/{sid}?dropNull=1", headers=CSRF)
    assert r_drop.status_code == 200
    assert "dropnull" in r_drop.headers.get("content-disposition", "").lower()
