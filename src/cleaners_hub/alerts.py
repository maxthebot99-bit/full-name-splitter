"""Email anomaly alerts via Resend.

Triggers (per the v1 hardening spec):
  * first successful login per email per UTC day
  * any single run with cost > $1
  * spend cap hit (once per UTC day)
  * persistent xAI 5xx errors (cool-down 30 min)

If ``RESEND_API_KEY_FILE`` is unset or empty, all methods are no-ops — the
app keeps working, alerts are simply disabled. We log a one-time WARNING at
startup so an operator notices.

Recipient is fixed at the Resend-account owner email. Resend's sandbox
sender (``onboarding@resend.dev``) refuses to deliver to anyone else
until you verify a domain at resend.com/domains — once that's done, swap
ALERT_FROM to a verified address (e.g. ``noreply@maxcommandcenter.com``)
and ALERT_TO can be retargeted at any address (e.g. work email).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from cleaners_hub.secrets import get_resend_key
from cleaners_hub.spend import _data_dir

# Recipient must match the Resend account owner email until a domain is
# verified at resend.com/domains — the sandbox sender (onboarding@resend.dev)
# refuses to deliver elsewhere. Resend account is owned by
# jazif@benchmarkintl.com (signed up 2026-04-28), so that's the only
# deliverable recipient at the moment. After domain verification: flip
# ALERT_FROM to noreply@maxcommandcenter.com (or chosen subdomain) and
# ALERT_TO can be retargeted at any address.
ALERT_TO = "jazif@benchmarkintl.com"
ALERT_FROM = "onboarding@resend.dev"  # Resend sandbox; works without DNS.
# Per-row cost is ~$0.000011 — a $5 run is ~454k rows, deeply unusual.
# $1 was too sensitive (a 91k-row file is normal-ish for sales lists).
COSTLY_RUN_THRESHOLD_USD = Decimal("5.00")
XAI_5XX_COOLDOWN_S = 30 * 60  # don't email about xAI errors more than once per 30 min

_log = logging.getLogger("cleaners_hub.alerts")


class AlertSender:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (_data_dir() / "alerts.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()
        self._xai_5xx_last_alert_ts: float = 0.0
        self._client = None
        self._client_init_error_logged = False

    # ---------- schema ----------

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init_schema(self) -> None:
        with self._lock, self._connect() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_seen (
                    bucket TEXT PRIMARY KEY,
                    ts TEXT NOT NULL
                )
                """
            )

    def _claim_once(self, bucket: str) -> bool:
        """INSERT-or-skip. Returns True if this is the first claim for the
        bucket (caller should send the alert), False if already claimed."""
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._connect() as c:
            try:
                c.execute(
                    "INSERT INTO alert_seen(bucket, ts) VALUES (?, ?)",
                    (bucket, ts),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    # ---------- transport ----------

    def _resend_client(self):
        """Lazy import + lazy auth so the module loads even without Resend."""
        if self._client is not None:
            return self._client
        key = get_resend_key()
        if not key:
            if not self._client_init_error_logged:
                _log.warning(
                    "RESEND_API_KEY_FILE not set; email alerts are disabled"
                )
                self._client_init_error_logged = True
            return None
        try:
            import resend  # type: ignore

            resend.api_key = key
            self._client = resend
            return resend
        except Exception as e:
            _log.warning("Failed to init Resend client: %r", e)
            return None

    def _send(self, subject: str, body: str) -> None:
        client = self._resend_client()
        if client is None:
            return
        try:
            client.Emails.send(
                {
                    "from": ALERT_FROM,
                    "to": [ALERT_TO],
                    "subject": subject,
                    "text": body,
                }
            )
            _log.info("alert_sent", extra={"action": "alert_sent", "subject": subject})
        except Exception as e:
            _log.warning("alert_send_failed: %r", e)

    # ---------- public triggers ----------

    def login_of_day(self, email: str) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        bucket = f"login:{email}:{today}"
        if not self._claim_once(bucket):
            return
        self._send(
            subject=f"[cleaners-hub] first login today by {email}",
            body=(
                f"Email: {email}\n"
                f"Date (UTC): {today}\n"
                f"App: cleaners.maxcommandcenter.com\n\n"
                "If this wasn't you, hit the kill switch:\n"
                "  one.dash.cloudflare.com → Access → Applications → cleaners-hub\n"
                "  → Edit policy → Action: Block → Save\n"
            ),
        )

    def run_started(
        self,
        *,
        email: str,
        session_id: str,
        kind: str,
        filename: str | None,
        column: str,
        row_count: int,
        row_limit: int | None,
        est_cost_usd: Decimal,
    ) -> None:
        """Fire on every Begin/Continue cleaning click. No dedup — each run
        gets its own email so an operator can spot runaway behavior fast.
        """
        effective = row_count if row_limit is None else min(row_limit, row_count)
        scope = (
            "all rows" if row_limit is None
            else f"first {row_limit:,} of {row_count:,}"
        )
        self._send(
            subject=(
                f"[cleaners-hub] {kind} run started by {email} "
                f"— {effective:,} rows, ~${est_cost_usd:.4f}"
            ),
            body=(
                f"Triggered by: {email}\n"
                f"Kind: {kind}\n"
                f"File: {filename or '<unknown>'}\n"
                f"Column: {column}\n"
                f"Scope: {scope}\n"
                f"Estimated cost: ${est_cost_usd:.4f}\n"
                f"Session: {session_id}\n"
            ),
        )

    def costly_run(self, *, email: str | None, session_id: str, cost_usd: Decimal,
                   row_count: int, kind: str) -> None:
        if cost_usd <= COSTLY_RUN_THRESHOLD_USD:
            return
        self._send(
            subject=f"[cleaners-hub] run cost ${cost_usd:.2f} ({kind}, {row_count} rows)",
            body=(
                f"Run completed with cost ${cost_usd:.2f}\n"
                f"Email: {email or '<unknown>'}\n"
                f"Session: {session_id}\n"
                f"Kind: {kind}\n"
                f"Rows: {row_count}\n"
            ),
        )

    def spend_cap_hit(self, *, today_total_usd: Decimal, cap_usd: Decimal) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        bucket = f"spend_cap:{today}"
        if not self._claim_once(bucket):
            return
        self._send(
            subject=f"[cleaners-hub] DAILY SPEND CAP HIT (${cap_usd:.2f})",
            body=(
                f"Today's UTC Grok spend: ${today_total_usd:.2f}\n"
                f"Cap: ${cap_usd:.2f}\n"
                "All further runs blocked until UTC midnight.\n\n"
                "If this is unexpected, investigate / consider kill switch.\n"
            ),
        )

    def test_ping(self, *, triggered_by: str) -> tuple[bool, str | None]:
        """Send an explicit test email — used by the admin Settings UI to
        verify Resend is wired up end-to-end. Returns (sent, error_or_None).
        Bypasses the bucket dedup so it always fires."""
        client = self._resend_client()
        if client is None:
            return False, "Resend client not initialized (key missing or invalid)"
        try:
            client.Emails.send(
                {
                    "from": ALERT_FROM,
                    "to": [ALERT_TO],
                    "subject": "[cleaners-hub] test ping",
                    "text": (
                        f"Triggered by: {triggered_by}\n"
                        f"App: cleaners.maxcommandcenter.com\n"
                        f"Sender: {ALERT_FROM} (Resend sandbox)\n"
                        f"Recipient: {ALERT_TO}\n\n"
                        "If you got this, the Resend wiring is working end-to-end."
                    ),
                }
            )
            _log.info("alert_test_sent",
                      extra={"action": "alert_test_sent",
                             "triggered_by": triggered_by})
            return True, None
        except Exception as e:
            _log.warning("alert_test_failed: %r", e)
            return False, f"{type(e).__name__}: {e}"

    def xai_5xx_persistent(self, *, error_count: int, window_min: int) -> None:
        now = time.time()
        if now - self._xai_5xx_last_alert_ts < XAI_5XX_COOLDOWN_S:
            return
        self._xai_5xx_last_alert_ts = now
        self._send(
            subject="[cleaners-hub] xAI 5xx errors persisting",
            body=(
                f"{error_count} 5xx errors from api.x.ai in the last "
                f"{window_min} minutes.\n"
                "Pipeline will keep retrying via tenacity; users see "
                "'paused, retrying' in the UI.\n"
            ),
        )


# Module-level singleton, lazily initialized. Avoids circular imports.
_singleton: AlertSender | None = None
_singleton_lock = threading.Lock()


def alerter() -> AlertSender:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = AlertSender()
    return _singleton
