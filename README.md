# full-name-splitter

> FastAPI + React app. AI-cleans company names and first names via the Grok (xAI) API. Two tabs (Companies / First Names) plus a third tab for Address enrichment (Gemini via OpenRouter, currently paused on cost grounds).

**Live:** https://full-name-splitter.maxcommandcenter.com
**Repo:** github.com/maxthebot99-bit/full-name-splitter
**Owner:** Jason Azif
**Status:** active
**SOP (for end users):** [SOP.md](./SOP.md)

## What this app does

Web app behind Cloudflare Access that consumes a CSV/XLSX upload, sends rows to the Grok API for company-name or first-name normalization in batches, and returns the cleaned output with a new `cleaned_<column>` column. Replaces the legacy desktop apps `company-name-cleaner` and `first-name-cleaner`. The Grok API key is encrypted via systemd-creds and never echoed to the browser.

The Address tab uses Gemini (via OpenRouter) instead of Grok. It works but Address enrichment is currently paused, since Clay is cheaper for that use case.

Sibling apps: [pipeline-hub] calls full-name-splitter as a service during stages 7-8 of the integrated campaign pipeline.

## Stack

- Python 3.11, FastAPI + Uvicorn
- React + TypeScript + Vite (UI). `ui/` source builds to `src/full_name_splitter/ui_dist/`, which the FastAPI app serves via StaticFiles
- httpx for Grok/OpenRouter HTTP calls
- tiktoken for token accounting + cost tracking
- pandas + pyarrow + openpyxl for CSV/Excel I/O
- charset-normalizer + ftfy for encoding fix-ups
- resend for email notifications on long-running runs
- curl_cffi + beautifulsoup4 + lxml for the Address tab's web fetcher

## How it runs locally

```bash
# Backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m full_name_splitter.main   # serves on :8194

# Frontend (development)
cd ui
npm install
npm run dev    # serves on :5173, proxies /api -> :8194
```

For a production-shape local run, build the UI first (`npm run build`) so `ui_dist/` is populated.

## How it's deployed

- VPS path: `/var/www/dashboard/apps/full-name-splitter/`
- Port: 8194 (bound to 127.0.0.1, fronted by cloudflared)
- Service: `full-name-splitter.service`, `User=www-data`
- Auto-deploy: `full-name-splitter-autodeploy.timer` polls `origin/main` every minute and invokes `deploy/install-vps.sh` when a new commit lands. Manual deploy: `ssh vps "sudo /var/www/dashboard/apps/full-name-splitter/deploy/install-vps.sh"`.
- Cloudflare Access: gated by the standard maxcommandcenter Access policy.

**Important:** `install-vps.sh` does NOT run `npm run build`. UI changes require either pushing the rebuilt `ui_dist/` artifacts or running the build locally before committing. The auto-deploy will deploy whatever `ui_dist/` is in the repo as-is.

## Environment variables

Loaded by systemd at service start.

| Var | Required | Notes |
|-----|----------|-------|
| `PORT` | yes | 8194 in prod |
| `GROK_API_KEY_FILE` | yes | systemd credential, path to the encrypted Grok PAT |
| `OPENROUTER_API_KEY_FILE` | for Address tab | systemd credential, Gemini-via-OpenRouter key |
| `RESEND_API_KEY_FILE` | optional | email-completion notifications |
| Per-user spend cap settings | optional | enforced in code via tiktoken cost accounting |

## Data flow

```
user upload  ->  /api/upload          (returns job_id + column list)
              ->  /api/clean/{job_id} (POST, kicks off batched Grok calls)
              ->  /api/status/{id}    (polled for progress)
              ->  /api/download/{id}  (cleaned CSV)
```

Per-job dirs are owned by `Cf-Access-Authenticated-User-Email`; users can only see/download their own jobs.

## File layout

```
full-name-splitter/
├── src/full_name_splitter/
│   ├── main.py             # FastAPI app, routes, lifespan
│   ├── ui_dist/            # built React bundle (Vite output)
│   └── ...
├── ui/                     # React/Vite source
│   ├── src/
│   │   ├── App.tsx
│   │   └── components/chrome/N2Topbar.tsx   # Topbar (Help/History/Settings)
│   ├── package.json
│   └── vite.config.ts
├── deploy/
│   ├── install-vps.sh
│   ├── auto-deploy.sh
│   ├── full-name-splitter-autodeploy.timer
│   ├── full-name-splitter-autodeploy.service
│   ├── full-name-splitter.service
│   └── start.sh
├── pyproject.toml
├── SOP.md
└── README.md               # this file
```

## Tests

No formal test suite at present. Smoke test:

```bash
curl -sI http://127.0.0.1:8194/SOP.md | head -3   # Expect 200 + text/markdown
curl http://127.0.0.1:8194/api/health             # Expect {"status":"ok",...}
```

## Known gotchas

- Grok API is non-deterministic. Same input produces variable output on different runs.
- Cost accounting via tiktoken is approximate (token estimates can drift from billed reality). Spend caps are best-effort, not guarantees.
- Address tab is **paused** on cost grounds (vs. Clay's pricing). Code remains; re-enable by talking to Jason.
- `npm run build` is NOT part of `install-vps.sh`. UI changes need a local rebuild + commit of `ui_dist/`.
- The Grok PAT is loaded via systemd-creds; rotation requires `systemd-creds encrypt --name=grok-api-key - /etc/credstore.encrypted/grok-api-key`.

## Recent changes

- 2026-05-14: SOP + /SOP.md route + /help server-rendered HTML page + Help button in Topbar.tsx.

## Related apps

- [pipeline-hub] calls full-name-splitter as a service during stages 7-8 (company name normalization on contact lists).
- [data-suppressor] / [deduplicator] should run after full-name-splitter for the cleanest dedupe (clean names dedupe better).
- The legacy desktop apps (`company-name-cleaner`, `first-name-cleaner`) this replaces still exist in archived repos.
