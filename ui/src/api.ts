// HTTP + SSE client for cleaners-hub. Every /api/* request gets the
// X-Requested-With CSRF header (the FastAPI middleware rejects without it).

import type {
  ColumnsResponse,
  DryRunResponse,
  Kind,
  SseEvent,
  UploadResponse,
  WhoamiResponse,
} from './types';

const HEADERS = { 'X-Requested-With': 'cleaners-hub' };

async function jsonOrThrow(res: Response): Promise<never | unknown> {
  if (res.ok) return res.json();
  let detail = '';
  try {
    const body = await res.json();
    detail = body?.detail ?? body?.error ?? JSON.stringify(body);
  } catch {
    detail = await res.text();
  }
  const err = new Error(`${res.status} ${res.statusText}: ${detail}`) as Error & { status: number };
  err.status = res.status;
  throw err;
}

export async function whoami(): Promise<WhoamiResponse> {
  const r = await fetch('/api/whoami', { headers: HEADERS });
  return jsonOrThrow(r) as Promise<WhoamiResponse>;
}

export async function uploadFile(kind: Kind, file: File): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append('kind', kind);
  fd.append('file', file);
  const r = await fetch('/api/upload', {
    method: 'POST',
    headers: HEADERS,
    body: fd,
  });
  return jsonOrThrow(r) as Promise<UploadResponse>;
}

export async function getColumns(sid: string): Promise<ColumnsResponse> {
  const r = await fetch(`/api/columns/${sid}`, { headers: HEADERS });
  return jsonOrThrow(r) as Promise<ColumnsResponse>;
}

export async function dryRun(sid: string, column: string, rowLimit?: number): Promise<DryRunResponse> {
  const r = await fetch(`/api/dry-run/${sid}`, {
    method: 'POST',
    headers: { ...HEADERS, 'Content-Type': 'application/json' },
    body: JSON.stringify({ column, rowLimit: rowLimit ?? null }),
  });
  return jsonOrThrow(r) as Promise<DryRunResponse>;
}

export async function startRun(sid: string, column: string, rowLimit?: number): Promise<void> {
  const r = await fetch(`/api/run/${sid}`, {
    method: 'POST',
    headers: { ...HEADERS, 'Content-Type': 'application/json' },
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

// EventSource for streaming progress. Returns the EventSource so the caller
// can `.close()` when the user navigates away. EventSource sends GET, no
// custom headers — the server allows /api/events/* without X-Requested-With.
export function openEventStream(sid: string, onEvent: (e: SseEvent) => void): EventSource {
  const es = new EventSource(`/api/events/${sid}`);
  es.onmessage = (msg) => {
    try {
      const parsed = JSON.parse(msg.data) as SseEvent;
      onEvent(parsed);
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
