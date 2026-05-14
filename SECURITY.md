# cleaners-hub — Security Posture

Audit-grade summary for SOC 2 / ISO 27001 control mapping. Full 2026-05-14 CSO comprehensive audit at `~/vault/10-projects/CleanersHub/reports/2026-05-14-cso-comprehensive.md`.

This service handles Benchmark prospect / contact data (names, companies, websites for address extraction). Threat-model assumption: a sophisticated attacker with an authenticated CF Access session.

## Reporting a vulnerability

See `.well-known/security.txt` for the disclosure contact (`jazif@benchmarkintl.com`).

## Identity (SOC 2 CC6.1 / ISO 27001 A.5.15)

All traffic to `cleaners.maxcommandcenter.com` is gated by **Cloudflare Access** at the edge. The wildcard policy on `*.maxcommandcenter.com` enforces SSO via Benchmark M365 identity. The origin trusts the `Cf-Access-Authenticated-User-Email` header injected by `cloudflared` and uses it for: per-user ownership scoping, rate-limit bucketing, and audit-log attribution. Origin binds to `127.0.0.1:8181`, never to a public interface.

Admin operations (settings PUT, cross-user run history, model whitelist edits) are gated by an in-code allowlist (`ADMIN_EMAILS` in `src/cleaners_hub/main.py`). The allowlist is intentionally hardcoded, not env-driven, to keep admin gating outside the blast radius of a compromised `.env`.

## Secret management (SOC 2 CC6.7 / ISO 27001 A.8.24)

All production credentials (xAI, OpenRouter, Resend) are stored via **systemd-creds** as encrypted files in `/etc/credstore.encrypted/`. At unit start they are decrypted into `/run/credentials/cleaners-hub.service/<name>` (tmpfs, RAM-only) and exposed to the app via file-path environment variables (`XAI_API_KEY_FILE`, etc.). The credential VALUES are never in env strings, never in process command lines, and never readable by other users on the host.

The app's audit logger has a `RedactingFilter` (`src/cleaners_hub/audit.py`) that strips xAI key patterns from every log record before emit — defense in depth in case a key ever leaks into a log line via stack trace or httpx URL error.

## Data flow + retention (SOC 2 P4.1 / ISO 27001 A.5.14, A.8.10)

User-uploaded CSVs are written to per-session UUIDv4 directories under `/var/lib/cleaners-hub/`. The runtime stores: the upload itself, intermediate cleaning artifacts (stage1.csv, etc.), the cleaned download. Files are scoped per-session per-user and only accessible to their owner via authenticated downloads. No external persistence beyond the VPS.

LLM inputs are wrapped in `<<INPUT>>...<</INPUT>>` sentinels so that a cell containing prompt-injection-shaped text cannot break the system prompt. Per-input character cap: 1,000 chars.

Hard daily spend cap: `$100/day` as a code constant in `src/cleaners_hub/spend.py`. The admin UI can lower the cap but cannot raise the ceiling without a code change + deploy.

## Network egress (SOC 2 CC6.6 / ISO 27001 A.8.20, A.8.21)

The systemd unit (`deploy/cleaners-hub.service`) enforces `IPAddressDeny=` for RFC1918, link-local + cloud metadata (`169.254.0.0/16`), Tailscale CGNAT (`100.64.0.0/10`), and IPv6 link-local + ULA. This blocks SSRF attempts via user-supplied CSV cells (`address` tab `website_url` column) at the network layer.

The application layer adds `_is_safe_url()` (`src/cleaners_hub/cleaners/address/fetch.py`) which resolves URLs via `socket.getaddrinfo` and rejects any IP in private/loopback/link-local/multicast/reserved ranges before issuing the HTTP request. Closes the loopback path that the systemd layer intentionally leaves open for unit-internal health checks. Also re-validates redirect targets after `allow_redirects=True`.

## Application hardening (SOC 2 CC6.6 / ISO 27001 A.8.21)

The systemd unit applies 14 hardening directives:
- `NoNewPrivileges=true`
- `ProtectSystem=strict` + `ReadWritePaths=/var/lib/cleaners-hub`
- `ProtectHome=read-only`
- `PrivateTmp=true`
- `ProtectKernelTunables/Modules/Logs=true`
- `ProtectControlGroups=true`
- `ProtectClock=true`
- `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`
- `RestrictNamespaces=true`
- `RestrictRealtime=true`
- `LockPersonality=true`
- `SystemCallArchitectures=native`
- `SystemCallFilter=@system-service`
- `StateDirectory=cleaners-hub` + `RuntimeDirectory=cleaners-hub`

Three additional directives (`PrivateDevices`, `MemoryDenyWriteExecute`, restrictive `SystemCallFilter=~@privileged @resources`) were trialed and removed because they break pandas/openpyxl/numpy at import. Re-enable if a future Python upgrade allows.

## Supply chain (SOC 2 CC7.1 / ISO 27001 A.8.8)

Dependencies live in `pyproject.toml` with `uv.lock` (628 sha256 pins). The `tool.uv.exclude-newer = "7 days"` directive refuses to install any package version published in the last week, blocking Shai-Hulud-class fast-publish supply-chain attacks.

Dependabot ALERTS, version updates, and automated security fixes are all enabled at the GitHub repo level (verified 2026-05-14).

## CSRF + transport hardening (SOC 2 CC6.6 / ISO 27001 A.8.24)

Every `/api/*` route except `/api/health` enforces an `X-Requested-With: cleaners-hub` header via `CSRFCheckMiddleware`. Browser-originated requests must originate from the app's own JS to attach the header; cross-origin requests cannot.

`SecurityHeadersMiddleware` sets HSTS (`max-age=31536000; includeSubDomains`), X-Frame-Options DENY, X-Content-Type-Options nosniff, and Referrer-Policy same-origin on every response.

## Change management (SOC 2 CC8.1 / ISO 27001 A.8.30, A.8.32)

Source: `github.com/maxthebot99-bit/cleaners-hub` (private). Production deploys auto-pull from `origin/main` every 60s via `cleaners-hub-autodeploy.timer` running `deploy/auto-deploy.sh`.

This is a fast-feedback deploy model. The mitigating controls:
- GitHub credentials for auto-deploy use a systemd-creds-decrypted PAT (`github-pat-askpass`) — never readable from the app's working directory
- CODEOWNERS file routes review of every PR
- Dependabot security fixes auto-open PRs; no version bump lands without a PR + review

Known follow-up: signed-commit verification in `auto-deploy.sh` before the `git reset --hard` would close the "compromised GH PAT lands on prod in 60s" residual risk.

## Logging + monitoring (SOC 2 CC7.2 / ISO 27001 A.8.15, A.8.16)

Structured audit log written via Python `logging` to journald (`SyslogIdentifier=cleaners-hub`). The `RedactingFilter` strips secret patterns before emit. `_safe_500()` returns a generic 500 message to clients and only logs the real exception server-side.

No centralized log aggregation currently. Production journal is reviewed ad-hoc during incident response.

## Data classification

| Class | Examples | Storage |
|-------|----------|---------|
| Restricted | xAI key, OpenRouter key, Resend key, Cloudflare API key | `/etc/credstore.encrypted/` (systemd-creds) |
| Confidential | User-uploaded CSVs (Benchmark prospect data), cleaned outputs | `/var/lib/cleaners-hub/<session-uuid>/` (per-user scope) |
| Internal | journald logs, spend.sqlite3 | `/var/lib/cleaners-hub/` |

## What an auditor needs to verify

1. Cloudflare Access policy on `*.maxcommandcenter.com` — confirm SSO identity, MFA enforcement, access review cadence
2. systemd unit at `/etc/systemd/system/cleaners-hub.service` — confirm `User=www-data`, `NoNewPrivileges`, `ProtectSystem=strict`, `IPAddressDeny` rules, `LoadCredentialEncrypted` for all three keys
3. Audit log emit on a sample request — confirm `Cf-Access-Authenticated-User-Email` is captured and that secret patterns don't appear
4. `auto-deploy.sh` runtime — confirm the PAT comes from credstore, not from the working directory
5. Spend cap behavior — confirm `SPEND_CAP_USD_PER_DAY` constant is enforced server-side and admin UI cannot exceed it

## Threat model summary

| Attacker | Capability | Mitigation |
|----------|------------|-----------|
| Unauthenticated internet | Reach the public Flask port | CF Access at edge; origin binds 127.0.0.1 only; UFW + cloudflared tunnel; no public TCP listener |
| Authenticated insider (Benchmark M365) | Upload malicious CSV | CF Access logs the identity; per-session scoping; size caps; sentinel-wrapped LLM inputs; defanged CSV output |
| Authenticated insider | Try cross-user enumeration | UUID-validated session paths; 404 (not 403) on unauthorized session access prevents UUID-space probing |
| Compromised PAT (auto-deploy GH token) | Push malicious commit to main | Auto-deploys in 60s — residual risk; signed-commit verification is a planned mitigation |
| SSRF via `website_url` cell | Reach internal services | Systemd IPAddressDeny + app-layer `_is_safe_url()` rejection |
| Prompt injection via CSV cell | Hijack the LLM | Sentinel-wrapped inputs; per-row 1000-char cap; system prompt is constant |
| Cost exhaustion attack | Run up xAI bill | Hard daily spend cap (code constant); per-route slowapi rate limits; per-batch caps |
| Compromised xAI key | Exfil via redirected requests | Audit log redaction filter; outbound TLS verify; key never in command line |
