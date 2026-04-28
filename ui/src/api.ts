// HTTP + SSE client for cleaners-hub. Every /api/* request gets the
// X-Requested-With CSRF header (the FastAPI middleware rejects without it).

import type {
  AppSettings,
  AppSettingsPatch,
  ColumnsResponse,
  DryRunResponse,
  DryRunSampleResponse,
  Kind,
  RunRecord,
  RunsListResponse,
  SseEvent,
  UploadResponse,
  WhoamiResponse,
  Row,
} from './types';

const HEADERS = { 'X-Requested-With': 'cleaners-hub' };
const HEADERS_JSON = { ...HEADERS, 'Content-Type': 'application/json' };

async function jsonOrThrow(res: Response): Promise<unknown> {
  if (res.ok) return res.json();
  let detail = '';
  try {
    const body = await res.json();
    detail = body?.detail ?? body?.error ?? JSON.stringify(body);
  } catch {
    detail = await res.text();
  }
  const err = new Error(`${res.status} ${res.statusText}: ${detail}`) as Error & {
    status: number;
  };
  err.status = res.status;
  throw err;
}

// ─── Cost estimator (mirrors backend EST_USD_PER_ROW = 0.000011) ────────
// Observed: ~$0.0081 / 748 rows on Grok-4-fast. Keep this in sync with
// EST_USD_PER_ROW in main.py — the dry-run endpoint uses the backend value
// for spend-cap checks; this client-side number drives the sidebar
// estimate and the cost-ceiling modal trigger.
const COST_CEILING_USD = 5.0;
export const COST_USD_PER_ROW = 0.000011;
export function estimateRunCost(rows: number): number {
  return rows * COST_USD_PER_ROW;
}
export function estimateRunSeconds(rows: number): number {
  return Math.max(60, rows / 14);
}
export function costCeiling(): number {
  return COST_CEILING_USD;
}

// ─── v1 endpoints ───────────────────────────────────────────────────────

export async function whoami(): Promise<WhoamiResponse> {
  const r = await fetch('/api/whoami', { headers: HEADERS });
  return jsonOrThrow(r) as Promise<WhoamiResponse>;
}

export async function uploadFile(kind: Kind, file: File): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append('kind', kind);
  fd.append('file', file);
  const r = await fetch('/api/upload', { method: 'POST', headers: HEADERS, body: fd });
  return jsonOrThrow(r) as Promise<UploadResponse>;
}

export async function getColumns(sid: string): Promise<ColumnsResponse> {
  const r = await fetch(`/api/columns/${sid}`, { headers: HEADERS });
  return jsonOrThrow(r) as Promise<ColumnsResponse>;
}

export async function dryRun(
  sid: string,
  column: string,
  rowLimit?: number,
): Promise<DryRunResponse> {
  const r = await fetch(`/api/dry-run/${sid}`, {
    method: 'POST',
    headers: HEADERS_JSON,
    body: JSON.stringify({ column, rowLimit: rowLimit ?? null }),
  });
  return jsonOrThrow(r) as Promise<DryRunResponse>;
}

export async function startRun(
  sid: string,
  column: string,
  rowLimit?: number,
): Promise<void> {
  const r = await fetch(`/api/run/${sid}`, {
    method: 'POST',
    headers: HEADERS_JSON,
    body: JSON.stringify({ column, rowLimit: rowLimit ?? null }),
  });
  if (!r.ok && r.status !== 202) await jsonOrThrow(r);
}

export async function cancelRun(sid: string): Promise<void> {
  const r = await fetch(`/api/run/${sid}`, { method: 'DELETE', headers: HEADERS });
  if (!r.ok) await jsonOrThrow(r);
}

export function downloadUrl(sid: string): string {
  return `/api/download/${sid}`;
}

// ─── v1.5 endpoints ─────────────────────────────────────────────────────

export interface PreviewResponse {
  column: string;
  rows: Row[];
}

export async function preview(
  sid: string,
  column: string,
  count = 200,
): Promise<PreviewResponse> {
  const r = await fetch(`/api/preview/${sid}`, {
    method: 'POST',
    headers: HEADERS_JSON,
    body: JSON.stringify({ column, count }),
  });
  return jsonOrThrow(r) as Promise<PreviewResponse>;
}

export async function dryRunSample(
  sid: string,
  column: string,
  count = 25,
): Promise<DryRunSampleResponse> {
  const r = await fetch(`/api/dry-run-sample/${sid}`, {
    method: 'POST',
    headers: HEADERS_JSON,
    body: JSON.stringify({ column, count }),
  });
  return jsonOrThrow(r) as Promise<DryRunSampleResponse>;
}

export async function overrideRow(
  sid: string,
  n: number,
  cleaned: string | null,
): Promise<Row> {
  const r = await fetch(`/api/rows/${sid}/${n}`, {
    method: 'POST',
    headers: HEADERS_JSON,
    body: JSON.stringify({ cleaned }),
  });
  return jsonOrThrow(r) as Promise<Row>;
}

export async function rerunRow(sid: string, n: number): Promise<Row> {
  const r = await fetch(`/api/rerun-row/${sid}`, {
    method: 'POST',
    headers: HEADERS_JSON,
    body: JSON.stringify({ n }),
  });
  return jsonOrThrow(r) as Promise<Row>;
}

export async function listRuns(opts?: {
  kind?: Kind;
  limit?: number;
  offset?: number;
  mineOnly?: boolean;
}): Promise<RunsListResponse> {
  const params = new URLSearchParams();
  if (opts?.kind) params.set('kind', opts.kind);
  if (opts?.limit != null) params.set('limit', String(opts.limit));
  if (opts?.offset != null) params.set('offset', String(opts.offset));
  if (opts?.mineOnly) params.set('mine_only', 'true');
  const qs = params.toString();
  const r = await fetch(`/api/runs${qs ? '?' + qs : ''}`, { headers: HEADERS });
  return jsonOrThrow(r) as Promise<RunsListResponse>;
}

export async function getRun(runId: string): Promise<RunRecord> {
  const r = await fetch(`/api/runs/${runId}`, { headers: HEADERS });
  return jsonOrThrow(r) as Promise<RunRecord>;
}

export function historyDownloadUrl(runId: string): string {
  return `/api/runs/${runId}/download`;
}

export async function getSettings(): Promise<AppSettings> {
  const r = await fetch('/api/settings', { headers: HEADERS });
  return jsonOrThrow(r) as Promise<AppSettings>;
}

export async function putSettings(patch: AppSettingsPatch): Promise<AppSettings> {
  const r = await fetch('/api/settings', {
    method: 'PUT',
    headers: HEADERS_JSON,
    body: JSON.stringify(patch),
  });
  return jsonOrThrow(r) as Promise<AppSettings>;
}

// ─── SSE ────────────────────────────────────────────────────────────────

// EventSource for streaming progress. The caller handles routing the events
// to the right slice — see store.handleSseEvent. EventSource sends GET with
// no custom headers; the server allows /api/events/* without X-Requested-With.
export function openEventStream(
  sid: string,
  onEvent: (e: SseEvent) => void,
): EventSource {
  const es = new EventSource(`/api/events/${sid}`);
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as SseEvent);
    } catch (err) {
      console.warn('[sse] bad frame:', msg.data, err);
    }
  };
  es.onerror = (err) => {
    // EventSource auto-reconnects on transient errors; only log.
    console.warn('[sse] error', err);
  };
  return es;
}
