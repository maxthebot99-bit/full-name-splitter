"""Structured audit log + secret-redaction filter.

Every meaningful action (upload, run-start, batch-complete, download, cancel,
spend-cap-hit, rate-limit-hit, xai-throttled, error) is logged as one JSON
line to the root logger, which systemd routes into journalctl.

The ``RedactingFilter`` is attached to the root logger and scans every
record's formatted message for live xAI-key patterns. Anything matching
``xai-[A-Za-z0-9]{20,}`` is replaced with ``xai-<REDACTED>`` before the
record is emitted. This is belt-and-suspenders against accidental
``logger.info(f"...{api_key}...")`` slips.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

# Match an xAI-style key: prefix `xai-` followed by 20+ url-safe chars. Wide
# enough to catch real keys, tight enough to avoid false positives on session
# UUIDs (which are dash-separated short hex chunks, not 20+ runs).
_XAI_KEY_RE = re.compile(r"xai-[A-Za-z0-9_\-]{20,}")
_REDACTED = "xai-<REDACTED>"


class RedactingFilter(logging.Filter):
    """Mask anything looking like a live xAI key in log output.

    Filter applies BEFORE formatting, so we patch ``record.msg`` and
    ``record.args`` directly. We do NOT scan ``record.exc_info`` — exception
    chains rarely contain raw keys (we never include the key in a raised
    exception) and traceback formatting is expensive.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = _XAI_KEY_RE.sub(_REDACTED, record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: _redact_value(v) for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(_redact_value(v) for v in record.args)
            # Also scrub any string-valued attribute set via ``extra={...}``.
            # These are stored directly on the record via setattr() and thus
            # bypass record.args entirely.
            for k, v in list(record.__dict__.items()):
                if isinstance(v, str) and "xai-" in v:
                    setattr(record, k, _XAI_KEY_RE.sub(_REDACTED, v))
        except Exception:
            # Never block a log line because of redaction errors.
            pass
        return True


def _redact_value(v: Any) -> Any:
    if isinstance(v, str):
        return _XAI_KEY_RE.sub(_REDACTED, v)
    return v


class JSONFormatter(logging.Formatter):
    """Emit each record as a single JSON line. Reserved structured fields
    (``action``, ``email``, ``session_id``, ``kind``) come from ``extra=``."""

    _RESERVED = ("action", "email", "session_id", "kind")
    _STD_KEYS = frozenset(
        # logging.LogRecord built-in attrs we don't want to spam into the JSON
        {
            "name", "msg", "args", "levelname", "levelno", "pathname",
            "filename", "module", "exc_info", "exc_text", "stack_info",
            "lineno", "funcName", "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName", "process", "taskName",
            "message", "asctime",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
        out: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k in self._RESERVED:
            v = getattr(record, k, None)
            if v is not None:
                out[k] = v
        for k, v in record.__dict__.items():
            if k in self._STD_KEYS or k in self._RESERVED:
                continue
            if k.startswith("_"):
                continue
            try:
                json.dumps(v)
                out[k] = v
            except (TypeError, ValueError):
                out[k] = repr(v)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


# Stdlib LogRecord attributes — passing any of these as `extra=` raises
# ``KeyError: "Attempt to overwrite ..."``. We auto-prefix collisions with
# ``data_`` so callers never have to think about reserved names.
_LOGRECORD_RESERVED = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
})


def _safe_extras(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        out[f"data_{k}" if k in _LOGRECORD_RESERVED else k] = v
    return out


def audit(
    action: str,
    *,
    email: str | None = None,
    session_id: str | None = None,
    kind: str | None = None,
    level: int = logging.INFO,
    **extra: Any,
) -> None:
    """Emit one structured audit line.

    Always uses the ``cleaners_hub.audit`` logger so it's easy to grep.
    """
    logger = logging.getLogger("cleaners_hub.audit")
    payload = _safe_extras(
        {
            "action": action,
            "email": email,
            "session_id": session_id,
            "kind": kind,
            **extra,
        }
    )
    logger.log(level, action, extra=payload)


def setup_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter + redaction filter on the root logger.

    Call once at app startup. Idempotent.
    """
    root = logging.getLogger()
    root.setLevel(level)
    # Strip any handlers a previous setup_logging() (or pytest) added.
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    # Quiet down chatty third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
