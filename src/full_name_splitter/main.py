"""FastAPI app — the only HTTP surface.

Routes (every /api/* path requires the X-Requested-With CSRF header except
/api/health and /api/events/*):

  GET    /api/health              liveness ping (no auth, no rate limit)
  GET    /api/whoami              email + today_spend_usd + cap_usd
  POST   /api/upload              multipart, ?kind=company|name → {sid, ...}
  GET    /api/columns/{sid}       column list + samples + suggested column
  POST   /api/dry-run/{sid}       body {column, rowLimit?} → {rowCount, estUsd}
  POST   /api/run/{sid}           body {column, rowLimit?} → 202 (worker spawned)
  DELETE /api/run/{sid}           cancel a running session
  GET    /api/events/{sid}        SSE: pipeline events
  GET    /api/download/{sid}      cleaned CSV (StreamingResponse)
  GET    /                        SPA shell (placeholder until ui_dist is built)

Authentication: every protected route reads ``Cf-Access-Authenticated-User-Email``
from request headers. Cloudflare Access guarantees this header on production
(only requests that passed the policy can ever reach the app). In local dev,
absent the header, the email is logged as ``anonymous`` and rate limit / spend
tracking still work.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Path as PathParam,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from full_name_splitter import __version__
from full_name_splitter.alerts import alerter
from full_name_splitter.audit import audit, setup_logging
from full_name_splitter.history import history
from full_name_splitter.middleware import CSRFCheckMiddleware
from full_name_splitter.sessions import (
    Session,
    is_valid_sid,
    session_public_dict,
    store,
    idle_sweeper_loop,
)
from full_name_splitter.settings_store import (
    ALLOWED_MODELS,
    MAX_BATCH_SIZE,
    MIN_BATCH_SIZE,
    MIN_DAILY_CAP_USD,
    settings as app_settings,
)
from full_name_splitter.spend import SPEND_CAP_USD_PER_DAY, SpendTracker
from full_name_splitter.streaming import sse_event_stream
from full_name_splitter.workers import (
    apply_override,
    dry_run_sample,
    rerun_one_row,
    spawn_run,
)

# ─── Constants ──────────────────────────────────────────────────────────────

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".xlsx", ".csv"}
ALLOWED_KINDS = {"fullname"}
EST_USD_PER_ROW = Decimal("0.000011")  # observed: ~$0.0081 / 748 rows on Grok-4-fast (2026-04-27)

# Emails allowed to PUT /api/settings + see other users' run history.
# Hardcoded in code, not env, to keep admin gating outside the blast
# radius of a compromised .env file.
#
# CSO 2026-05-14: swapped from personal Gmail to Benchmark federated
# identity. Personal Gmail lacked Benchmark MFA enforcement and was
# subject to separate password-reuse risk; SOC 2 CC6.1 requires admin
# access via federated identity with enforced MFA. CF Access wildcard
# *.maxcommandcenter.com allows both Google SSO and Benchmark M365 SSO,
# so the auth path is preserved.
ADMIN_EMAILS: frozenset[str] = frozenset({"jazif@benchmarkintl.com"})


def _is_admin(email: str | None) -> bool:
    return email is not None and email.lower() in {e.lower() for e in ADMIN_EMAILS}

_log = logging.getLogger("full_name_splitter.main")
_spend = SpendTracker()


# ─── Helpers ────────────────────────────────────────────────────────────────

def _email_from_request(request: Request) -> str:
    """Read the Cloudflare Access header. Falls back to 'anonymous' in dev."""
    return request.headers.get("Cf-Access-Authenticated-User-Email") or "anonymous"


def _rate_limit_key(request: Request) -> str:
    return _email_from_request(request)


limiter = Limiter(key_func=_rate_limit_key)


def _suggest_column(kind: str, columns: list[str]) -> str | None:
    """Heuristic: pick a column whose name looks like a full-name field.

    Splitter only has one kind (``fullname``). Strong hints (exact or
    substring match) come first; weak hints fall back to anything with
    "name" that isn't already a first/last/middle column.
    """
    fullname_strong = [
        "full name", "full_name", "fullname",
        "contact name", "contact_name", "contactname",
        "name", "person name", "person_name",
        "display name", "display_name", "displayname",
    ]
    # "first name" / "last name" columns should NOT be suggested — those
    # are split outputs, not the unified input the splitter wants.
    name_negative = ["first name", "first_name", "firstname",
                     "last name", "last_name", "lastname",
                     "middle name", "middle_name", "middlename"]

    lowered = [(c, c.lower().strip()) for c in columns]

    def is_negative(low: str) -> bool:
        return any(h in low for h in name_negative)

    if kind == "fullname":
        # Tier 1: exact match on a strong hint.
        for h in fullname_strong:
            for c, low in lowered:
                if low == h:
                    return c
        # Tier 2: substring match, excluding split-field columns.
        for h in fullname_strong:
            for c, low in lowered:
                if h in low and not is_negative(low):
                    return c
        return None
    return None


# ─── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(level=logging.INFO)
    _log.info(
        "startup",
        extra={
            "action": "startup",
            "version": __version__,
            "env": os.environ.get("CLEANERS_HUB_ENV", "prod"),
            "spend_cap_usd": float(SPEND_CAP_USD_PER_DAY),
        },
    )
    sweeper_task = asyncio.create_task(idle_sweeper_loop(), name="idle-sweeper")
    try:
        yield
    finally:
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass
        _log.info("shutdown", extra={"action": "shutdown"})


# ─── App ────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="full-name-splitter",
    version=__version__,
    docs_url=None,        # OpenAPI/Swagger disabled in prod (info disclosure)
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# slowapi wiring
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: same-origin only. Cloudflare Tunnel rewrites Origin to the public host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://full-name-splitter.maxcommandcenter.com", "http://localhost:5173"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-Requested-With", "Content-Type"],
    allow_credentials=True,
    max_age=600,
)

# CSRF check on /api/*
app.add_middleware(CSRFCheckMiddleware)


# ─── Dependency helpers ─────────────────────────────────────────────────────

def _audit_request(request: Request, action: str, **extra) -> str:
    """Stamp a request with audit + login-of-day side effect. Returns email."""
    email = _email_from_request(request)
    if email != "anonymous":
        try:
            alerter().login_of_day(email)
        except Exception as e:
            _log.warning("login_of_day alert failed: %r", e)
    audit(action, email=email, **extra)
    return email


def _require_session(sid: str) -> Session:
    if not is_valid_sid(sid):
        raise HTTPException(400, detail="invalid session id")
    sess = store.get(sid)
    if sess is None:
        raise HTTPException(404, detail="session not found or expired")
    return sess


def _require_owned_session(request: Request, sid: str) -> Session:
    """Same as _require_session, plus the requesting email must own the
    session (or be admin). Used on every per-sid live route — events,
    download, run, dry-run, preview, dry-run-sample, columns, rows,
    rerun-row, cancel — so a coworker can't read another's session by
    sniffing/guessing the UUID. Returns 404 (not 403) when the session
    exists but isn't yours, matching the historical-runs gate, so an
    unauthorized user can't probe the session-id space."""
    sess = _require_session(sid)
    email = _email_from_request(request)
    if _is_admin(email):
        return sess
    owner = (sess.email or "").lower()
    if owner and owner != email.lower():
        raise HTTPException(404, detail="session not found or expired")
    return sess


def _safe_500(action: str, exc: Exception) -> HTTPException:
    """Build a generic 500 response. Logs the real exception (with
    traceback) server-side via the audit log, but returns a safe message
    to the client so we never leak exception text — which can include the
    xAI key if a library raises with the request URL embedded."""
    audit(f"{action}_error", error=f"{type(exc).__name__}: {exc!r}",
          level=logging.ERROR)
    _log.exception("%s_error", action)
    return HTTPException(500, detail=f"internal error during {action}")


# ─── Pydantic bodies ────────────────────────────────────────────────────────

class RunBody(BaseModel):
    column: str = Field(..., min_length=1, max_length=200)
    # Address kind only: the second input column (website URL). Company/name
    # ignore this. Optional so existing single-column callers keep working.
    secondary_column: str | None = Field(None, min_length=1, max_length=200)
    rowLimit: int | None = Field(None, ge=1, le=1_000_000)


class DryRunSampleBody(BaseModel):
    column: str = Field(..., min_length=1, max_length=200)
    secondary_column: str | None = Field(None, min_length=1, max_length=200)
    count: int = Field(25, ge=1, le=100)


class PreviewBody(BaseModel):
    column: str = Field(..., min_length=1, max_length=200)
    secondary_column: str | None = Field(None, min_length=1, max_length=200)
    count: int = Field(200, ge=1, le=500)


class OverrideBody(BaseModel):
    """Manual override body — splitter shape.

    The splitter has TWO output cells per row (First Name / Last Name), so
    overrides arrive as an independent (first, last) pair. Either part can
    be cleared by sending null/empty for that field; sending null for BOTH
    clears the override entirely (the writer treats both-empty as is_null).
    """
    first: str | None = Field(None, max_length=1000)
    last: str | None = Field(None, max_length=1000)


class RerunRowBody(BaseModel):
    n: int = Field(..., ge=1, le=1_000_000)


class SettingsPatch(BaseModel):
    daily_cap_usd: float | None = Field(None, ge=0, le=float(SPEND_CAP_USD_PER_DAY))
    batch_size_fullname: int | None = Field(None, ge=MIN_BATCH_SIZE, le=MAX_BATCH_SIZE)
    model_fullname: str | None = None


# ─── Routes ─────────────────────────────────────────────────────────────────


_SOP_PATH = Path(__file__).resolve().parents[2] / "SOP.md"


@app.get("/SOP.md")
def sop_md() -> FileResponse:
    """Serve the end-user SOP as raw markdown (consumed by /help and by the app-dashboard)."""
    return FileResponse(_SOP_PATH, media_type="text/markdown; charset=utf-8")


@app.get("/help", response_class=HTMLResponse)
def help_page() -> HTMLResponse:
    """Standalone HTML help page. Fetches /SOP.md and renders client-side with marked."""
    return HTMLResponse("""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<title>Help - Cleaners Hub</title>
<script src="https://cdn.jsdelivr.net/npm/marked@5.1.2/marked.min.js" crossorigin="anonymous"></script>
<style>
  body { font-family: Inter, -apple-system, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 20px; color: #f0f2f5; background: #06070a; line-height: 1.6; }
  h1, h2 { color: #fff; }
  code { background: #14171f; padding: 2px 6px; border-radius: 4px; }
  a { color: #00d4ff; }
  #content { min-height: 60vh; }
</style>
</head><body>
<div id="content">Loading...</div>
<p><a href="/">Back to app</a></p>
<script>
fetch('/SOP.md').then(r => {
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.text();
}).then(md => {
  document.getElementById('content').innerHTML = marked.parse(md);
}).catch(e => {
  document.getElementById('content').innerHTML = '<p>Could not load help: ' + e.message + '</p>';
});
</script>
</body></html>""")


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "active_sessions": store.snapshot()["active"],
    }


@app.get("/api/whoami")
@limiter.limit("60/minute")
async def whoami(request: Request) -> dict:
    email = _email_from_request(request)
    today = _spend.today_total_usd()
    soft_cap = Decimal(str(app_settings().get().daily_cap_usd))
    remaining = soft_cap - today
    if remaining < 0:
        remaining = Decimal(0)
    return {
        "email": email,
        "is_admin": _is_admin(email),
        "today_usd": float(today),
        "cap_usd": float(soft_cap),                  # soft cap (settings)
        "hard_cap_usd": float(SPEND_CAP_USD_PER_DAY),  # immutable ceiling
        "remaining_usd": float(remaining),
    }


@app.post("/api/upload")
@limiter.limit("10/minute")
async def upload(
    request: Request,
    kind: Annotated[str, Form(...)],
    file: Annotated[UploadFile, File(...)],
) -> dict:
    if kind not in ALLOWED_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(ALLOWED_KINDS)}")
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"only {sorted(ALLOWED_EXTENSIONS)} allowed")

    email = _audit_request(request, "upload_start", kind=kind, filename=filename)

    # Create session AFTER kind/extension validation
    loop = asyncio.get_running_loop()
    sess = store.create(kind=kind, email=email, loop=loop)

    target = sess.dir / f"upload{ext}"
    total = 0
    try:
        with target.open("wb") as out_fp:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    out_fp.close()
                    target.unlink(missing_ok=True)
                    store.delete(sess.sid)
                    raise HTTPException(413, f"file exceeds {MAX_UPLOAD_BYTES} bytes")
                out_fp.write(chunk)
    finally:
        try:
            await file.close()
        except Exception:
            pass

    sess.upload_path = target
    sess.upload_filename = filename
    sess.upload_size_bytes = total

    audit("upload_done", email=email, session_id=sess.sid, kind=kind,
          filename=filename, size_bytes=total)

    return session_public_dict(sess)


@app.get("/api/columns/{sid}")
@limiter.limit("60/minute")
async def list_columns(request: Request, sid: str = PathParam(...)) -> dict:
    sess = _require_owned_session(request, sid)
    if sess.upload_path is None:
        raise HTTPException(409, "no file uploaded")

    # Lazy import to avoid loading pandas at startup
    import importlib
    io_reader = importlib.import_module(f"full_name_splitter.cleaners.{sess.kind}.io.reader")
    try:
        meta = io_reader.inspect(sess.upload_path)
    except Exception as e:
        raise _safe_500("file_inspect", e) from e

    sess._file_meta_obj = meta  # used by worker
    sess.row_count = meta.row_count_estimate

    # Sample up to 5 values from each column (capped at 60 chars each)
    samples: dict[str, list[str]] = {}
    try:
        if str(meta.path).lower().endswith(".xlsx"):
            df_head = pd.read_excel(meta.path, sheet_name=meta.sheet, dtype=str,
                                    nrows=5, keep_default_na=False)
        else:
            df_head = pd.read_csv(
                meta.path, encoding=meta.encoding, sep=meta.delimiter,
                dtype=str, nrows=5, keep_default_na=False, engine="python",
            )
        for c in meta.columns:
            vals = []
            if c in df_head.columns:
                for v in df_head[c].astype(str).tolist():
                    s = (v or "").strip()
                    if not s:
                        continue
                    vals.append(s[:60])
            samples[c] = vals
    except Exception as e:
        _log.warning("samples failed: %r", e)

    cols_payload = [
        {"name": c, "samples": samples.get(c, [])} for c in meta.columns
    ]
    suggested = _suggest_column(sess.kind, list(meta.columns))
    sess.columns = cols_payload
    body: dict = {
        "sid": sess.sid,
        "kind": sess.kind,
        "columns": cols_payload,
        "row_count_estimate": meta.row_count_estimate,
        "suggested": suggested,
    }
    # Splitter only has the ``fullname`` kind — single suggested column.
    return body


@app.post("/api/dry-run/{sid}")
@limiter.limit("30/minute")
async def dry_run(
    request: Request,
    body: RunBody,
    sid: str = PathParam(...),
) -> dict:
    sess = _require_owned_session(request, sid)
    meta = getattr(sess, "_file_meta_obj", None)
    if meta is None:
        raise HTTPException(409, "must call /api/columns first")
    if body.column not in meta.columns:
        raise HTTPException(400, f"unknown column: {body.column!r}")

    rows = meta.row_count_estimate
    if body.rowLimit is not None:
        rows = min(rows, body.rowLimit)

    est = (Decimal(rows) * EST_USD_PER_ROW).quantize(Decimal("0.0001"))
    today = _spend.today_total_usd()
    soft_cap = Decimal(str(app_settings().get().daily_cap_usd))
    will_block = (today + est) > soft_cap

    audit("dry_run", email=_email_from_request(request), session_id=sid,
          kind=sess.kind, column=body.column, row_count=rows,
          estimated_cost_usd=float(est))

    return {
        "row_count": rows,
        "estimated_cost_usd": float(est),
        "today_usd": float(today),
        "cap_usd": float(soft_cap),
        "would_exceed_cap": will_block,
    }


@app.post("/api/run/{sid}", status_code=202)
@limiter.limit("5/minute")
async def start_run(
    request: Request,
    body: RunBody,
    sid: str = PathParam(...),
) -> dict:
    sess = _require_owned_session(request, sid)
    if sess.state == "running":
        raise HTTPException(409, "session already running")
    meta = getattr(sess, "_file_meta_obj", None)
    if meta is None:
        raise HTTPException(409, "must call /api/columns first")
    if body.column not in meta.columns:
        raise HTTPException(400, f"unknown column: {body.column!r}")

    sess.cancel_flag.clear()
    sess.selected_column = body.column
    sess.state = "running"

    email = _email_from_request(request)
    audit("run_start", email=email, session_id=sid, kind=sess.kind,
          column=body.column, row_limit=body.rowLimit)

    # Email the operator on every run-start so misuse / accidental large
    # runs / unfamiliar emails surface immediately — not just at done.
    rows_in_file = meta.row_count_estimate
    effective = (
        rows_in_file if body.rowLimit is None
        else min(body.rowLimit, rows_in_file)
    )
    est_cost = (Decimal(effective) * EST_USD_PER_ROW).quantize(Decimal("0.0001"))
    try:
        alerter().run_started(
            email=email,
            session_id=sid,
            kind=sess.kind,
            filename=sess.upload_filename,
            column=body.column,
            row_count=rows_in_file,
            row_limit=body.rowLimit,
            est_cost_usd=est_cost,
        )
    except Exception as e:
        _log.warning("alert run_started failed: %r", e)

    # For address kind, body.secondary_column carries the business-name column.
    spawn_run(
        sess, column=body.column, row_limit=body.rowLimit,
        spend=_spend, secondary_column=body.secondary_column,
    )
    return session_public_dict(sess)


@app.delete("/api/run/{sid}")
@limiter.limit("10/minute")
async def cancel_run(request: Request, sid: str = PathParam(...)) -> dict:
    sess = _require_owned_session(request, sid)
    if sess.state != "running":
        return session_public_dict(sess)
    sess.cancel_flag.set()
    audit("run_cancel_requested", email=_email_from_request(request),
          session_id=sid, kind=sess.kind)
    return session_public_dict(sess)


@app.get("/api/events/{sid}")
async def events(request: Request, sid: str = PathParam(...)):
    sess = _require_owned_session(request, sid)
    return StreamingResponse(
        sse_event_stream(sess),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/download/{sid}")
@limiter.limit("30/minute")
async def download(
    request: Request,
    sid: str = PathParam(...),
    dropNull: int = Query(0, ge=0, le=1),
):
    """Stream the cleaned CSV.

    ``?dropNull=1`` filters out rows where BOTH "First Name" and "Last Name"
    cells are empty (the splitter's null sentinel). Used by the "Download
    cleaned (drop NULL rows)" button in the result panel.
    """
    sess = _require_owned_session(request, sid)
    if sess.state != "done" or sess.result_csv_path is None:
        raise HTTPException(409, "no result available")
    out = sess.result_csv_path
    if not out.exists():
        raise HTTPException(410, "result expired")
    base = Path(sess.upload_filename or "cleaned").stem
    drop = bool(dropNull)
    download_name = (
        f"{base}__cleaned__dropnull.csv" if drop else f"{base}__cleaned.csv"
    )
    audit("download", email=_email_from_request(request), session_id=sid,
          kind=sess.kind, row_count=sess.result_row_count,
          cost_usd=sess.result_cost_usd, drop_null=drop)
    if not drop:
        return FileResponse(
            out,
            media_type="text/csv",
            filename=download_name,
            headers={"Cache-Control": "no-store"},
        )
    # dropNull mode: read, filter, stream. Stays in memory — runs already
    # fit in RAM at write time (build_export_df does the same). For huge
    # outputs the trade-off is acceptable; the soft-cap keeps row counts
    # in a sane range.
    try:
        df = pd.read_csv(out, dtype=str, keep_default_na=False)
    except Exception as e:
        raise _safe_500("download_dropnull_read", e) from e

    first_col = "First Name"
    last_col = "Last Name"
    if first_col not in df.columns or last_col not in df.columns:
        # Defensive: a malformed output would otherwise blow up below. Fall
        # back to the full file.
        _log.warning("download dropNull: expected columns missing; serving full file")
        return FileResponse(
            out,
            media_type="text/csv",
            filename=download_name,
            headers={"Cache-Control": "no-store"},
        )

    # Treat empty / whitespace-only cells as null.
    keep = (df[first_col].astype(str).str.strip() != "") | (
        df[last_col].astype(str).str.strip() != ""
    )
    filtered = df[keep]

    import io

    buf = io.StringIO()
    filtered.to_csv(buf, index=False)
    payload = buf.getvalue().encode("utf-8-sig")

    def _gen():
        yield payload

    return StreamingResponse(
        _gen(),
        media_type="text/csv",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )


# ─── v2 routes: preview, dry-run sample, overrides, rerun, history, settings

@app.post("/api/preview/{sid}")
@limiter.limit("30/minute")
async def preview(
    request: Request,
    body: PreviewBody,
    sid: str = PathParam(...),
) -> dict:
    """Return raw column values without running Grok.

    Uses the same ``io_reader.read_chunks`` path the run worker uses, so
    the preview is consistent with what the actual cleaning will see —
    same encoding/delimiter detection, same malformed-row handling.
    """
    sess = _require_owned_session(request, sid)
    meta = getattr(sess, "_file_meta_obj", None)
    if meta is None:
        raise HTTPException(409, "must call /api/columns first")

    # Resolve the column case-insensitively and trim whitespace so a
    # frontend-sent " Company Name " still finds "Company Name".
    target_col: str | None = None
    wanted = body.column.strip()
    wanted_low = wanted.lower()
    for c in meta.columns:
        if c == wanted or c.strip() == wanted or c.lower() == wanted_low:
            target_col = c
            break
    if target_col is None:
        raise HTTPException(400, f"unknown column: {body.column!r}")

    n = body.count
    import importlib
    io_reader = importlib.import_module(f"full_name_splitter.cleaners.{sess.kind}.io.reader")

    try:
        chunks = io_reader.read_chunks(meta, target_col, chunk_rows=max(n, 100))
        df_chunk = next(iter(chunks), None)
    except Exception as e:
        raise _safe_500("preview_read", e) from e

    if df_chunk is None or target_col not in df_chunk.columns:
        audit("preview", email=_email_from_request(request), session_id=sid,
              kind=sess.kind, column=target_col, count=0,
              note="column missing from chunk")
        return {"column": target_col, "rows": []}

    vals = df_chunk[target_col].astype(str).tolist()[:n]

    rows = [
        {
            "n": i + 1,
            "orig": (v or "").strip(),
            # Splitter shape: two output cells (first, last) per row.
            # Pre-run preview rows are pending — both empty.
            "first": None,
            "last": None,
            "clean": None,
            "status": "pending",
            "reason": "",
        }
        for i, v in enumerate(vals)
    ]
    nonempty = sum(1 for r in rows if r["orig"])
    # Stash the user's column choice on the session so per-row ▶ / override
    # clicks (which can fire before the full run) know which column to read.
    sess.selected_column = target_col
    audit("preview", email=_email_from_request(request), session_id=sid,
          kind=sess.kind, column=target_col, count=len(rows),
          nonempty=nonempty)
    return {"column": target_col, "rows": rows}


@app.post("/api/dry-run-sample/{sid}")
@limiter.limit("10/minute")
async def dry_run_sample_route(
    request: Request,
    body: DryRunSampleBody,
    sid: str = PathParam(...),
) -> dict:
    sess = _require_owned_session(request, sid)
    if sess.upload_path is None:
        raise HTTPException(409, "no file uploaded")
    # Run synchronously in a thread-pool slot (clean_batch is sync httpx).
    # Doesn't block the asyncio loop because FastAPI runs def routes via
    # the threadpool, but this is async, so wrap in run_in_executor for
    # consistency with our worker model.
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: dry_run_sample(sess, column=body.column, count=body.count, spend=_spend),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise _safe_500("dry_run_sample", e) from e

    audit("dry_run_sample_request", email=_email_from_request(request),
          session_id=sid, kind=sess.kind, column=body.column, count=body.count)
    return result


@app.post("/api/rows/{sid}/{n}")
@limiter.limit("60/minute")
async def override_row(
    request: Request,
    body: OverrideBody,
    sid: str = PathParam(...),
    n: int = PathParam(..., ge=1, le=1_000_000),
) -> dict:
    sess = _require_owned_session(request, sid)
    payload = apply_override(sess, n=n, first=body.first, last=body.last)
    if payload is None:
        raise HTTPException(404, f"row {n} not found in session")
    cleared = (body.first is None or body.first == "") and (
        body.last is None or body.last == ""
    )
    audit("override_request", email=_email_from_request(request),
          session_id=sid, kind=sess.kind, row_n=n, cleared=cleared)
    return payload


@app.post("/api/rerun-row/{sid}")
@limiter.limit("30/minute")
async def rerun_row_route(
    request: Request,
    body: RerunRowBody,
    sid: str = PathParam(...),
) -> dict:
    sess = _require_owned_session(request, sid)
    loop = asyncio.get_running_loop()
    try:
        payload = await loop.run_in_executor(
            None, lambda: rerun_one_row(sess, n=body.n, spend=_spend)
        )
    except Exception as e:
        raise _safe_500("rerun_one_row", e) from e
    if payload is None:
        raise HTTPException(404, f"row {body.n} not found in session")
    audit("rerun_request", email=_email_from_request(request),
          session_id=sid, kind=sess.kind, row_n=body.n)
    return payload


@app.get("/api/runs")
@limiter.limit("60/minute")
async def list_runs(
    request: Request,
    kind: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    mine_only: bool = Query(False),
) -> dict:
    if kind is not None and kind not in ALLOWED_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(ALLOWED_KINDS)}")
    email = _email_from_request(request)
    # Non-admins can only see their own runs — never expose other users'
    # filenames / row counts / costs. Admins see everything by default;
    # they can still pass mine_only=true to filter their own.
    is_admin = _is_admin(email)
    effective_mine_only = mine_only or not is_admin
    filter_email = email if effective_mine_only else None
    h = history()
    rows = h.list_runs(
        kind=kind,
        email=filter_email,
        limit=limit,
        offset=offset,
    )
    total = h.count_runs(kind=kind, email=filter_email)
    return {"total": total, "limit": limit, "offset": offset, "rows": rows}


def _can_access_run(row: dict, email: str) -> bool:
    """Owner or admin only. Used to gate /api/runs/{id} and its download.

    We deliberately collapse "you don't own it" and "doesn't exist" into a
    single 404 in the callers so an unauthorized user can't probe the run
    space by sending guessed UUIDs.
    """
    if _is_admin(email):
        return True
    return (row.get("email") or "").lower() == email.lower()


@app.get("/api/runs/{run_id}")
@limiter.limit("60/minute")
async def get_run(request: Request, run_id: str = PathParam(...)) -> dict:
    if not is_valid_sid(run_id):
        raise HTTPException(400, "invalid run id")
    row = history().get_run(run_id)
    email = _email_from_request(request)
    if row is None or not _can_access_run(row, email):
        # Same 404 shape whether the run is missing or just not yours.
        raise HTTPException(404, "run not found")
    return row


@app.get("/api/runs/{run_id}/download")
@limiter.limit("30/minute")
async def download_past_run(request: Request, run_id: str = PathParam(...)):
    if not is_valid_sid(run_id):
        raise HTTPException(400, "invalid run id")
    row = history().get_run(run_id)
    email = _email_from_request(request)
    if row is None or not _can_access_run(row, email):
        raise HTTPException(404, "run not found")
    if row.get("state") != "done":
        raise HTTPException(409, f"run state is {row.get('state')}")
    out_path_str = row.get("output_path")
    if not out_path_str:
        raise HTTPException(410, "no output recorded for this run")
    out = Path(out_path_str)
    # Defense in depth: history.sqlite3 is the only thing pointing at this
    # path, but if the DB ever gets a tampered row we don't want the
    # download endpoint serving arbitrary disk files. Confine to the
    # outputs root.
    from full_name_splitter.sessions import _outputs_root
    try:
        out.resolve().relative_to(_outputs_root().resolve())
    except (ValueError, OSError):
        audit("download_history_path_escape", email=email, session_id=run_id,
              path=str(out), level=logging.ERROR)
        raise HTTPException(410, "output file missing on disk")
    if not out.exists():
        raise HTTPException(410, "output file missing on disk")
    base = Path(row.get("filename") or "cleaned").stem
    audit("download_history", email=email, session_id=run_id,
          kind=row.get("kind"), owner=row.get("email"))
    return FileResponse(
        out,
        media_type="text/csv",
        filename=f"{base}__cleaned.csv",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/settings")
@limiter.limit("60/minute")
async def get_settings(request: Request) -> dict:
    s = app_settings().get()
    return {
        **s.to_dict(),
        "is_admin": _is_admin(_email_from_request(request)),
        "hard_cap_usd": float(SPEND_CAP_USD_PER_DAY),
        "min_batch_size": MIN_BATCH_SIZE,
        "max_batch_size": MAX_BATCH_SIZE,
        "min_daily_cap_usd": MIN_DAILY_CAP_USD,
        "allowed_models": list(ALLOWED_MODELS),
    }


@app.post("/api/admin/test-alert")
@limiter.limit("5/minute")
async def test_alert(request: Request) -> dict:
    """Admin-only: send a one-off test email through the Resend wiring.

    Useful for verifying the API key + sandbox sender after planting a new
    Resend credential. Bypasses the per-day dedup, so it always fires.
    """
    email = _email_from_request(request)
    if not _is_admin(email):
        raise HTTPException(403, "admin only")
    sent, err = alerter().test_ping(triggered_by=email)
    audit("test_alert", email=email, sent=sent, error=err)
    if not sent:
        return {"sent": False, "error": err}
    return {"sent": True}


@app.put("/api/settings")
@limiter.limit("10/minute")
async def put_settings(request: Request, body: SettingsPatch) -> dict:
    email = _email_from_request(request)
    if not _is_admin(email):
        raise HTTPException(403, "admin only")
    # body.dict() is Pydantic v1 API — removed in v2. model_dump() is the
    # forward-compatible call that works on both.
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(400, "no fields to update")
    try:
        new_settings = app_settings().update(patch)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    audit("settings_changed", email=email, **patch)
    return new_settings.to_dict()


# ─── SPA shell ──────────────────────────────────────────────────────────────

_UI_DIST = Path(__file__).resolve().parent / "ui_dist"


def _has_ui_dist() -> bool:
    return (_UI_DIST / "index.html").exists()


if _has_ui_dist():
    # Production: serve the prebuilt React bundle
    app.mount(
        "/assets",
        StaticFiles(directory=_UI_DIST / "assets", check_dir=False),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # SPA fallback: any non-/api path returns index.html so React Router
        # can take over.
        if full_path.startswith("api/"):
            raise HTTPException(404)
        index = _UI_DIST / "index.html"
        return FileResponse(index, media_type="text/html",
                            headers={"Cache-Control": "no-store"})
else:
    @app.get("/", include_in_schema=False)
    async def root_placeholder() -> HTMLResponse:
        return HTMLResponse(
            "<!doctype html><html><head><title>full-name-splitter</title></head>"
            "<body style='font-family:sans-serif;padding:2rem'>"
            "<h1>full-name-splitter</h1>"
            f"<p>API up (v{__version__}). UI bundle not yet built.</p>"
            "<p>Try <code>GET /api/health</code>.</p>"
            "</body></html>"
        )


def run() -> None:
    """Entrypoint for ``full-name-splitter`` console script. Used by deploy/start.sh."""
    import uvicorn

    port = int(os.environ.get("PORT", "8181"))
    uvicorn.run(
        "full_name_splitter.main:app",
        host="127.0.0.1",
        port=port,
        workers=1,
        log_config=None,  # we handle logging ourselves via setup_logging
        access_log=False,
    )


if __name__ == "__main__":
    run()
