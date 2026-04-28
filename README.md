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

`/api/upload` (multipart) → `/api/columns` → `/api/dry-run` → `/api/run` → `/api/events` (SSE) → `/api/download`. Static React bundle served from `/`.

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

## v1 hardening (mandatory, baked in)

| Item | Where |
|---|---|
| $10/day Grok spend cap | `cleaners_hub.spend.SpendTracker` (SQLite under tempdir) |
| Per-user rate limit | `slowapi` keyed by `Cf-Access-Authenticated-User-Email` |
| Email anomaly alerts | Resend → `jazif@benchmarkintl.com` |
| Structured audit log | JSON to journalctl, schema documented in `cleaners_hub.audit` |
| Secret redaction filter | `RedactingFilter` drops anything matching `r"xai-[A-Za-z0-9]{20,}"` |
| CSRF header on `/api/*` | Middleware requires `X-Requested-With: cleaners-hub` |
| 4h CF Access JWT TTL | Manual setting on the wildcard policy in CF dashboard |
| systemd hardening | `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, etc. — see `deploy/cleaners-hub.service` |

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

**Updates (after first deploy):**

```bash
git push                              # from your laptop
ssh kianna@127.0.0.1 -p 2222 'sudo /var/www/dashboard/apps/cleaners-hub/deploy/install-vps.sh'
```

The script is idempotent — if cloudflared ingress and DNS already exist, it skips them and just refreshes code + venv + restarts the service.

**After first deploy:** in the Cloudflare dashboard, set the Access JWT TTL on the `*.maxcommandcenter.com` policy to 4h.

## v1 limitations (documented, not bugs)

- **Sessions don't survive service restarts.** `PrivateTmp=true` wipes `/var/tmp/cleaners-hub/` on every unit start, so any in-flight run is lost on `systemctl restart`. Acceptable for v1; deferred to v2 (move outputs to `/var/lib/cleaners-hub/outputs/`).
- **No mid-run resume.** If you refresh the browser during a run, the SSE stream drops; the worker keeps going on the server but the new tab can't reconstruct progress. Banner in the UI says don't refresh during a run.
- **No resumable downloads.** Browser drop = click Download again.
- **60-min idle TTL.** Walk away for an hour, come back, you re-upload.
- **Resend disabled by default in v1.** The `resend-api-key` credential can be the literal string `disabled`; alerts silently no-op until you replace it with a real Resend API key + restart.

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
