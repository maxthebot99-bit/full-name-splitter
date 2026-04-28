"""Daily Grok spend circuit breaker.

Records every API call's token usage + USD cost into a SQLite file. Before
each batch, the worker calls ``would_exceed_cap`` with an estimate; if the
sum of today's running total plus the estimate would cross
``SPEND_CAP_USD_PER_DAY``, the batch is rejected and an SSE event surfaces
to the UI.

The cap lives in code, not in env. Bumping the cap requires a code edit +
deploy — a compromised .env or a leaked CF Access JWT cannot raise it.

DB location: $CLEANERS_HUB_DATA_DIR/spend.sqlite3 (default /var/lib/cleaners-hub).
This must be a path that survives systemd restarts, so it lives outside the
unit's PrivateTmp. The unit's ReadWritePaths must include this dir.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# HARD daily-cap ceiling — the absolute maximum the soft cap (in
# AppSettings.daily_cap_usd) can be raised to via the UI. To raise above
# this, edit this constant and redeploy. Pinned in code (not env / not
# settings.json) so a compromised .env or a leaked admin JWT can't push
# spending past this number.
#
# The DEFAULT soft cap is set in settings_store.AppSettings (currently
# $10/day); admin can dial it anywhere in [MIN_DAILY_CAP_USD, this].
SPEND_CAP_USD_PER_DAY: Decimal = Decimal("100.00")

# Grok-4 fast (non-reasoning) pricing. Update if xAI changes published rates.
# These mirror the desktop xai.py constants.
XAI_INPUT_USD_PER_1K: Decimal = Decimal("0.0002")
XAI_OUTPUT_USD_PER_1K: Decimal = Decimal("0.0005")

_DEFAULT_DATA_DIR = Path("/var/lib/cleaners-hub")


def _data_dir() -> Path:
    p = os.environ.get("CLEANERS_HUB_DATA_DIR")
    return Path(p) if p else _DEFAULT_DATA_DIR


def usd_for_tokens(prompt_tokens: int, completion_tokens: int) -> Decimal:
    return (
        Decimal(prompt_tokens) * XAI_INPUT_USD_PER_1K / Decimal(1000)
        + Decimal(completion_tokens) * XAI_OUTPUT_USD_PER_1K / Decimal(1000)
    )


class SpendTracker:
    """Thread-safe SQLite-backed spend log. Singleton-ish — one per process."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (_data_dir() / "spend.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init_schema(self) -> None:
        with self._lock, self._connect() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS spend (
                    ts TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    session_id TEXT,
                    email TEXT,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_spend_ts ON spend(ts)")

    def record(
        self,
        *,
        kind: str,
        session_id: str | None,
        email: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: Decimal,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._connect() as c:
            c.execute(
                "INSERT INTO spend(ts,kind,session_id,email,prompt_tokens,"
                "completion_tokens,cost_usd) VALUES (?,?,?,?,?,?,?)",
                (
                    ts,
                    kind,
                    session_id,
                    email,
                    int(prompt_tokens),
                    int(completion_tokens),
                    float(cost_usd),
                ),
            )

    def today_total_usd(self) -> Decimal:
        # SQLite ``date('now')`` is UTC. Cap reset is at UTC midnight.
        with self._lock, self._connect() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(cost_usd),0) FROM spend "
                "WHERE date(ts)=date('now')"
            ).fetchone()
        return Decimal(str(row[0] or 0))

    def would_exceed_cap(self, estimated_usd: Decimal) -> bool:
        return (self.today_total_usd() + estimated_usd) > SPEND_CAP_USD_PER_DAY

    def remaining_today_usd(self) -> Decimal:
        rem = SPEND_CAP_USD_PER_DAY - self.today_total_usd()
        return rem if rem > 0 else Decimal("0")
