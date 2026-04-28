# cleaners-hub

Web app at `cleaners.maxcommandcenter.com` that cleans company names and first names via the Grok (xAI) API. Two tabs: Companies / First Names. Behind Cloudflare Access (Google OAuth).

Replaces the desktop apps `company-name-cleaner` and `first-name-cleaner`. The Grok API key never leaves the VPS — it lives encrypted in `systemd-creds` and is loaded into the unit at runtime, never echoed back to the browser.

---

## Architecture

```
Browser (Google OAuth) → Cloudflare Access (4h JWT)
  → Cloudflare Tunnel → VPS systemd: cleaners-hub.service
    → uvicorn (User=www-data) → FastAPI app
      → outbound HTTPS → api.x.ai/v1/chat/completions
```

**Live route surface** — full list in `main.py`:

```
GET  /api/health                liveness ping (no auth, no rate limit)
GET  /api/whoami                email + soft cap + spend today + is_admin
POST /api/upload                multipart, ?kind=company|name → {sid, ...}
GET  /api/columns/{sid}         column list + samples + suggested column
POST /api/preview/{sid}         raw column values pre-cleaning (no Grok)
POST /api/dry-run/{sid}         row count + cost estimate (no Grok)
POST /api/dry-run-sample/{sid}  inline 25-row Grok sample preview
POST /api/run/{sid}             kicks off the worker thread (202 accepted)
DELETE /api/run/{sid}           cancel a running session
GET  /api/events/{sid}          SSE: state, rows, telemetry, error
GET  /api/download/{sid}        cleaned CSV (live session)
POST /api/rows/{sid}/{n}        manual cleaned-cell override
POST /api/rerun-row/{sid}       re-Grok one row
GET  /api/runs                  history (auto-scoped to caller for non-admins)
GET  /api/runs/{run_id}         run detail (owner-or-admin only)
GET  /api/runs/{run_id}/download  re-download a past CSV (owner-or-admin)
GET  /api/settings              admin runtime settings (caps, models, batches)
PUT  /api/settings              admin-only patch
POST /api/admin/test-alert      admin-only Resend test ping
```

Static React bundle served from `/`.

Both pipelines (`company` + `name`) live under `src/cleaners_hub/cleaners/`. Vendored from the legacy desktop apps; same prompt, same batch sizes, same Grok provider.

---

## Local development

```bash
# 1. Set up venv + install
~/.node/node.exe --version            # confirm node v22.x present
python -m venv .venv
source .venv/Scripts/activate          # Windows bash
pip install -e ".[dev]"

# 2. Drop the Grok key into a local file (NEVER commit)
echo -n 'xai-...' > xai-api-key.txt

# 3. Run the API
XAI_API_KEY_FILE=$(pwd)/xai-api-key.txt \
  RESEND_API_KEY_FILE=$(pwd)/resend-api-key.txt \
  CLEANERS_HUB_ENV=dev \
  uvicorn cleaners_hub.main:app --reload --port 8181

# 4. Run the UI in dev (proxies /api to :8181)
cd ui && npm install && npm run dev
```

Prod uses systemd-creds, not these local files. See "Deploy" below.

---

## Hardening (mandatory, baked in)

| Item | Where |
|---|---|
| Daily Grok spend cap | Soft cap default $10/day, admin-tunable up to a $100/day hard ceiling. Hard cap is in code (`spend.SPEND_CAP_USD_PER_DAY`); soft cap lives in `settings.json` under `/var/lib/cleaners-hub/`. |
| Per-user rate limit | `slowapi` keyed by `Cf-Access-Authenticated-User-Email` |
| Email anomaly alerts | Resend → `jazif@benchmarkintl.com`. Triggers: first-login-of-day, every run started, every run completed, costly-run (>$5), spend-cap-hit. Sender is the Resend sandbox `onboarding@resend.dev` until a domain is verified. |
| Structured audit log | JSON to journalctl, schema documented in `cleaners_hub.audit` |
| Secret redaction filter | `RedactingFilter` drops anything matching `r"xai-[A-Za-z0-9_\-]{20,}"` from log records |
| Generic 5xx responses | HTTP 500s never include exception text — full traceback goes to journalctl, only `internal error during <action>` reaches the browser |
| CSRF header on `/api/*` | Middleware requires `X-Requested-With: cleaners-hub` (download + events + health are exempted; documented in `middleware.py`) |
| Owner-or-admin checks | All `/api/runs/{id}*` history routes and all per-`{sid}` live routes 404 if the requesting email isn't the session/run owner (or admin) |
| Output retention | `/var/lib/cleaners-hub/outputs/` swept by the idle sweeper; CSVs older than 30 days are deleted (history.sqlite3 keeps the metadata; download endpoint returns 410 for missing files) |
| 4h CF Access JWT TTL | Manual setting on the wildcard policy in CF dashboard |
| systemd hardening | `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, `TimeoutStopSec=20`, etc. — see `deploy/cleaners-hub.service`. `MemoryDenyWriteExecute`/`PrivateDevices` were tried and dropped because they break pandas C-extensions (documented in the unit). |

---

## Deploy

`/usr/local/bin/app deploy` doesn't fit our shape (it auto-detects Flask, not FastAPI/uvicorn/venv apps), so we deploy via [`deploy/install-vps.sh`](deploy/install-vps.sh) — idempotent, runs the same on first install or as an updater.

**One-time setup (before first run):**

```bash
ssh kianna@127.0.0.1 -p 2222

# 1. Plant the Grok key (use `read -rs` so the value never hits your shell history)
read -rs XAI_KEY
echo -n "$XAI_KEY" | sudo systemd-creds encrypt --name=xai-api-key - /etc/credstore.encrypted/xai-api-key
unset XAI_KEY
sudo chmod 600 /etc/credstore.encrypted/xai-api-key

# 2. Plant the Resend key the same way (or `disabled` placeholder for v1)
read -rs RESEND_KEY
echo -n "$RESEND_KEY" | sudo systemd-creds encrypt --name=resend-api-key - /etc/credstore.encrypted/resend-api-key
unset RESEND_KEY
sudo chmod 600 /etc/credstore.encrypted/resend-api-key
```

**First deploy:**

```bash
# Bootstrap clone + run the install script
sudo bash <<'BOOT'
GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/usr/local/bin/github-pat-askpass \
  git -c credential.helper= clone \
  https://github.com/maxthebot99-bit/cleaners-hub.git \
  /home/kianna/github-repos/cleaners-hub
chown -R kianna:kianna /home/kianna/github-repos/cleaners-hub
bash /home/kianna/github-repos/cleaners-hub/deploy/install-vps.sh
BOOT
```

**Updates (after first deploy):** just push.

```bash
git push   # from your laptop
```

A `cleaners-hub-autodeploy.timer` on the VPS polls origin/main every 60s, runs `auto-deploy.sh` (which `git fetch` + `git reset --hard` + invokes `install-vps.sh`), and restarts the service. New commits land within ~60-90s with no SSH dance.

To pause / inspect:

```bash
sudo systemctl stop cleaners-hub-autodeploy.timer        # pause
sudo journalctl -u cleaners-hub-autodeploy.service -f    # tail deploys
```

Manual install-vps.sh is always still safe — the script is idempotent — useful when you want to verify a deploy before the timer fires or after a broken-state recovery.

**After first deploy:** in the Cloudflare dashboard, set the Access JWT TTL on the `*.maxcommandcenter.com` policy to 4h.

## Known limitations (documented, not bugs)

- **In-flight session memory dies on service restart.** Output CSVs for completed runs persist (under `/var/lib/cleaners-hub/outputs/`, survives `systemctl restart`) but the in-memory session — uploaded file, current run state, SSE queue — is wiped. The worker's last-batch context lives in `session.contexts`, so "Continue cleaning" after a restart works only if the user has the same session ID and re-attaches; in practice they'll re-upload.
- **No mid-run resume across page refresh.** If you refresh the browser during a run, the SSE stream drops; the worker keeps going on the server but the new tab can't reconstruct progress. Banner in the UI says don't refresh during a run.
- **No resumable downloads.** Browser drop = click Download again.
- **60-min idle TTL.** Walk away for an hour with no activity, come back, you re-upload. (An open SSE stream keeps the session alive, so an idle run is fine.)
- **Resend in placeholder mode.** If the `resend-api-key` credential file contains the literal string `disabled` (or the `RESEND_API_KEY_FILE` env is unset), `secrets.get_resend_key()` returns `None` and all alert methods no-op. Replace the credential and `systemctl restart cleaners-hub` to enable.
- **Sandbox sender.** Until a domain is verified at resend.com/domains, alerts send from `onboarding@resend.dev` and can only be delivered to the Resend account-owner email. Verify a maxcommandcenter.com subdomain to lift this — three DNS records, one constant in `alerts.py`.

---

## Kill switch

If something looks wrong, two ways to take the app offline:

**From any browser (works on phone):**
```
one.dash.cloudflare.com → Access → Applications → cleaners-hub
  → Edit policy → Action: Block → Save
```
Effective globally in <30 seconds.

**From SSH:**
```
ssh kianna@127.0.0.1 -p 2222 'sudo systemctl stop cleaners-hub'
```

---

## Key rotation drill (target time: 60 seconds)

```bash
# 1. Generate fresh key in xAI console; copy to clipboard.
# 2. SSH:
ssh kianna@127.0.0.1 -p 2222
# 3. Re-encrypt:
echo -n "<paste-key>" | sudo systemd-creds encrypt \
  --name=xai-api-key - /etc/credstore.encrypted/xai-api-key
# 4. Restart:
sudo systemctl restart cleaners-hub
# 5. Revoke old key in xAI console.
```

Practice this once after first deploy so it's muscle memory.

---

## Security model summary

What an attacker who breaches Cloudflare Access *can* do:
- Trigger Grok runs (capped at $10/day in code)
- Upload `.xlsx`/`.csv` (parsed read-only, no formula execution)
- Get rate-limited at 10 uploads/min, 5 runs/min

What they *cannot* do, no matter what:
- Read the xAI key from any HTTP response (no endpoint returns it)
- See the key in client-side JS (it's never in the bundle)
- See the key in any log line (redaction filter)
- Make the app call a non-xAI URL (outbound URL is hardcoded)

What v1 does NOT defend against (out of scope):
- VPS provider compromise (Hostinger admin reading process memory)
- Kernel LPE on the box
- Compromise of an authorized Google account (mitigation: 2FA + WebAuthn at Google)

Full security model in `docs/SECURITY.md` (TBD) and in the plan file at `~/.claude/plans/hola-now-that-drifting-glacier.md`.
