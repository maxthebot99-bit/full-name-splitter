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

from cleaners_hub import __version__
from cleaners_hub.alerts import alerter
from cleaners_hub.audit import audit, setup_logging
from cleaners_hub.middleware import CSRFCheckMiddleware
from cleaners_hub.sessions import (
    Session,
    is_valid_sid,
    session_public_dict,
    store,
    idle_sweeper_loop,
)
from cleaners_hub.spend import SPEND_CAP_USD_PER_DAY, SpendTracker
from cleaners_hub.streaming import sse_event_stream
from cleaners_hub.workers import spawn_run

# ─── Constants ──────────────────────────────────────────────────────────────

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".xlsx", ".csv"}
ALLOWED_KINDS = {"company", "name"}
EST_USD_PER_ROW = Decimal("0.00012")  # conservative: ~300 in-tok + 8 out-tok @ Grok pricing

_log = logging.getLogger("cleaners_hub.main")
_spend = SpendTracker()


# ─── Helpers ────────────────────────────────────────────────────────────────

def _email_from_request(request: Request) -> str:
    """Read the Cloudflare Access header. Falls back to 'anonymous' in dev."""
    return request.headers.get("Cf-Access-Authenticated-User-Email") or "anonymous"


def _rate_limit_key(request: Request) -> str:
    return _email_from_request(request)


limiter = Limiter(key_func=_rate_limit_key)


def _suggest_column(kind: str, columns: list[str]) -> str | None:
    """Heuristic: pick a column whose name looks right for this kind."""
    hints = {
        "company": ["company", "account", "organization", "organisation",
                    "business", "brand", "name"],
        "name": ["first name", "first_name", "firstname", "given name",
                 "given_name", "givenname", "name"],
    }[kind]
    lowered = {c: c.lower() for c in columns}
    for c, low in lowered.items():
        for h in hints:
            if low == h:
                return c
    for c, low in lowered.items():
        for h in hints:
            if h in low:
                return c
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
    title="cleaners-hub",
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
    allow_origins=["https://cleaners.maxcommandcenter.com", "http://localhost:5173"],
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


# ─── Pydantic bodies ────────────────────────────────────────────────────────

class RunBody(BaseModel):
    column: str = Field(..., min_length=1, max_length=200)
    rowLimit: int | None = Field(None, ge=1, le=1_000_000)


# ─── Routes ─────────────────────────────────────────────────────────────────

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
    return {
        "email": email,
        "today_usd": float(today),
        "cap_usd": float(SPEND_CAP_USD_PER_DAY),
        "remaining_usd": float(_spend.remaining_today_usd()),
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
    sess = _require_session(sid)
    if sess.upload_path is None:
        raise HTTPException(409, "no file uploaded")

    # Lazy import to avoid loading pandas at startup
    import importlib
    io_reader = importlib.import_module(f"cleaners_hub.cleaners.{sess.kind}.io.reader")
    try:
        meta = io_reader.inspect(sess.upload_path)
    except Exception as e:
        raise HTTPException(400, f"file inspect failed: {type(e).__name__}: {e}") from e

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
    return {
        "sid": sess.sid,
        "kind": sess.kind,
        "columns": cols_payload,
        "row_count_estimate": meta.row_count_estimate,
        "suggested": suggested,
    }


@app.post("/api/dry-run/{sid}")
@limiter.limit("30/minute")
async def dry_run(
    request: Request,
    body: RunBody,
    sid: str = PathParam(...),
) -> dict:
    sess = _require_session(sid)
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
    will_block = (today + est) > SPEND_CAP_USD_PER_DAY

    audit("dry_run", email=_email_from_request(request), session_id=sid,
          kind=sess.kind, column=body.column, row_count=rows,
          estimated_cost_usd=float(est))

    return {
        "row_count": rows,
        "estimated_cost_usd": float(est),
        "today_usd": float(today),
        "cap_usd": float(SPEND_CAP_USD_PER_DAY),
        "would_exceed_cap": will_block,
    }


@app.post("/api/run/{sid}", status_code=202)
@limiter.limit("5/minute")
async def start_run(
    request: Request,
    body: RunBody,
    sid: str = PathParam(...),
) -> dict:
    sess = _require_session(sid)
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

    spawn_run(sess, column=body.column, row_limit=body.rowLimit, spend=_spend)
    return session_public_dict(sess)


@app.delete("/api/run/{sid}")
@limiter.limit("10/minute")
async def cancel_run(request: Request, sid: str = PathParam(...)) -> dict:
    sess = _require_session(sid)
    if sess.state != "running":
        return session_public_dict(sess)
    sess.cancel_flag.set()
    audit("run_cancel_requested", email=_email_from_request(request),
          session_id=sid, kind=sess.kind)
    return session_public_dict(sess)


@app.get("/api/events/{sid}")
async def events(request: Request, sid: str = PathParam(...)):
    sess = _require_session(sid)
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
async def download(request: Request, sid: str = PathParam(...)):
    sess = _require_session(sid)
    if sess.state != "done" or sess.result_csv_path is None:
        raise HTTPException(409, "no result available")
    out = sess.result_csv_path
    if not out.exists():
        raise HTTPException(410, "result expired")
    base = Path(sess.upload_filename or "cleaned").stem
    download_name = f"{base}__cleaned.csv"
    audit("download", email=_email_from_request(request), session_id=sid,
          kind=sess.kind, row_count=sess.result_row_count,
          cost_usd=sess.result_cost_usd)
    return FileResponse(
        out,
        media_type="text/csv",
        filename=download_name,
        headers={"Cache-Control": "no-store"},
    )


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
            "<!doctype html><html><head><title>cleaners-hub</title></head>"
            "<body style='font-family:sans-serif;padding:2rem'>"
            "<h1>cleaners-hub</h1>"
            f"<p>API up (v{__version__}). UI bundle not yet built.</p>"
            "<p>Try <code>GET /api/health</code>.</p>"
            "</body></html>"
        )


def run() -> None:
    """Entrypoint for ``cleaners-hub`` console script. Used by deploy/start.sh."""
    import uvicorn

    port = int(os.environ.get("PORT", "8181"))
    uvicorn.run(
        "cleaners_hub.main:app",
        host="127.0.0.1",
        port=port,
        workers=1,
        log_config=None,  # we handle logging ourselves via setup_logging
        access_log=False,
    )


if __name__ == "__main__":
    run()
