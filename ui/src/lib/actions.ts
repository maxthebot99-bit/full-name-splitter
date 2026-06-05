// High-level actions — what UI components call. Wraps the HTTP api.ts and
// keeps the store consistent. Splitter shape: one kind, one slice, no kind
// parameter threaded through.

import {
  cancelRun as httpCancelRun,
  dryRunSample as httpDryRunSample,
  getColumns,
  getSettings,
  historyDownloadUrl,
  listRuns,
  openEventStream,
  overrideRow as httpOverrideRow,
  preview as httpPreview,
  putSettings as httpPutSettings,
  rerunRow as httpRerunRow,
  startRun as httpStartRun,
  uploadFile,
  whoami as httpWhoami,
  estimateRunCost,
  estimateRunSeconds,
  costCeiling,
} from '../api';
import { handleSseEvent, useStore, viewState } from '../store';
import { mapDryRunSample } from './mapping';
import type {
  AppSettings,
  AppSettingsPatch,
  MapperColumn,
  Row,
} from '../types';

// ─── whoami / settings / history ────────────────────────────────────────

export async function refreshWhoami(): Promise<void> {
  try {
    const w = await httpWhoami();
    useStore.getState().setWhoami(w);
  } catch (err) {
    console.warn('[whoami] failed:', err);
  }
}

export async function refreshSettings(): Promise<void> {
  try {
    const s = await getSettings();
    useStore.getState().setSettings(s);
  } catch (err) {
    console.warn('[settings] failed:', err);
  }
}

export async function saveSettings(patch: AppSettingsPatch): Promise<AppSettings> {
  const s = await httpPutSettings(patch);
  useStore.getState().setSettings(s);
  return s;
}

export async function openHistory(opts?: { mineOnly?: boolean }): Promise<void> {
  const s = useStore.getState();
  s.setHistory({ open: true, loading: true });
  try {
    const r = await listRuns({ limit: 50, mineOnly: opts?.mineOnly ?? false });
    s.setHistory({ loading: false, runs: r.rows, total: r.total });
  } catch (err) {
    console.warn('[history] failed:', err);
    s.setHistory({ loading: false, runs: [], total: 0 });
  }
}
export function closeHistory(): void {
  useStore.getState().setHistory({ open: false });
}
export function pastRunDownloadUrl(runId: string): string {
  return historyDownloadUrl(runId);
}

// ─── upload + columns ───────────────────────────────────────────────────

// Browse-via-OS-dialog. Spawns a hidden <input type="file"> so we don't
// have to wire one into every empty-state surface.
export function pickFile(): void {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.csv,.xlsx';
  input.onchange = () => {
    const f = input.files?.[0];
    if (f) void handleFileSelected(f);
  };
  input.click();
}

// Drop-target onDrop also routes through here.
export async function handleFileSelected(file: File): Promise<void> {
  const s = useStore.getState();
  s.resetSlice();
  try {
    const up = await uploadFile(file);
    s.patchSlice({
      sid: up.sid,
      runState: 'uploaded',
      file: {
        name: up.filename,
        rows: up.row_count ?? 0,
        encoding: 'utf-8',
        column: '',
      },
    });
    const cols = await getColumns(up.sid);
    const colNames = cols.columns.map((c) => c.name);
    s.patchSlice({
      file: {
        name: up.filename,
        rows: cols.row_count_estimate,
        encoding: 'utf-8',
        column: '', // user picks via the mapper
        columns: colNames,
      },
      mapperSelectedColumn: cols.suggested ?? undefined,
    });
  } catch (err) {
    console.error('[upload] failed:', err);
    const msg = err instanceof Error ? err.message : 'upload failed';
    s.setUiError({ code: 0, message: msg, retryAfter: 0, lastRow: 0 });
    s.setRunState('error');
  }
}

// Mapper data — fetch /api/columns again (cheap; cached server-side via
// the session's _file_meta_obj) and compute display meta.
export async function listColumnsWithSamples(): Promise<MapperColumn[]> {
  const slice = useStore.getState().fullname;
  if (!slice.sid) return [];
  try {
    const cols = await getColumns(slice.sid);
    const suggested = cols.suggested;
    return cols.columns.map((c): MapperColumn => {
      const previewVals = c.samples.filter(Boolean).slice(0, 5);
      const inferType = (() => {
        if (previewVals.length === 0) return 'empty';
        const numeric = previewVals.every((v) => /^-?\d+(?:\.\d+)?$/.test(v));
        return numeric ? 'integer' : 'text';
      })();
      return {
        id: c.name,
        name: c.name,
        meta: `${inferType} · ${cols.row_count_estimate.toLocaleString('en-US')} rows`,
        preview: previewVals,
        suggested: c.name === suggested,
      };
    });
  } catch (err) {
    console.error('[columns] failed:', err);
    return [];
  }
}

export async function confirmColumn(column: string): Promise<void> {
  const s = useStore.getState();
  s.setColumn(column);
  s.setMapperSelectedColumn(undefined);
  s.setRunState('columns_loaded');
  // Fetch the first ~200 raw values for that column and seed them as
  // `pending` rows. The user sees actual data top-down before paying for
  // Grok; real cleaned values replace these in-place once the run starts.
  const slice = s.fullname;
  if (!slice.sid) return;
  const total = slice.file?.rows ?? 0;
  const n = Math.min(total > 0 ? total : 200, 200);
  try {
    const res = await httpPreview(slice.sid, column, n);
    s.replaceRows(res.rows);
  } catch (err) {
    console.warn('[preview] failed, falling back to empty placeholders:', err);
    const placeholders: Row[] = Array.from({ length: n }, (_, i) => ({
      n: i + 1,
      orig: '',
      first: null,
      last: null,
      clean: null,
      status: 'pending',
      reason: '',
    }));
    s.replaceRows(placeholders);
  }
}

// ─── run start (with $5 cost-ceiling modal) ─────────────────────────────

export function beginCleaningWithCostCheck(column: string, rowLimit?: number): void {
  const s = useStore.getState();
  const slice = s.fullname;
  const total = slice.file?.rows ?? 0;
  const effective = rowLimit && rowLimit > 0 ? Math.min(rowLimit, total) : total;
  const costUsd = estimateRunCost(effective);
  const elapsedSeconds = estimateRunSeconds(effective);
  if (costUsd > costCeiling()) {
    s.setCostModal({ rows: effective, costUsd, elapsedSeconds, column, rowLimit });
    return;
  }
  void startRun(column, rowLimit);
}

export function confirmCostModal(): void {
  const s = useStore.getState();
  const m = s.fullname.costModal;
  s.setCostModal(undefined);
  if (!m) return;
  void startRun(m.column, m.rowLimit);
}
export function cancelCostModal(): void {
  useStore.getState().setCostModal(undefined);
}

export async function startRun(column: string, rowLimit?: number): Promise<void> {
  const s = useStore.getState();
  const slice = s.fullname;
  if (!slice.sid) return;
  s.setDryRun(undefined);
  s.setUiError(undefined);
  s.setSpendBlocked(undefined);
  s.setRunState('running');
  openSse();
  try {
    await httpStartRun(slice.sid, column, rowLimit);
  } catch (err) {
    console.error('[run] start failed:', err);
    const msg = err instanceof Error ? err.message : 'run failed';
    s.setUiError({ code: 0, message: msg, retryAfter: 0, lastRow: 0 });
    s.setRunState('error');
  }
}

export async function cancelRun(): Promise<void> {
  const s = useStore.getState();
  const slice = s.fullname;
  if (!slice.sid) return;
  try {
    await httpCancelRun(slice.sid);
  } catch (err) {
    console.warn('[cancel] failed:', err);
  }
}

// ─── dry-run sample ─────────────────────────────────────────────────────

export async function runDryRun(column: string, count = 25): Promise<void> {
  const s = useStore.getState();
  const slice = s.fullname;
  if (!slice.sid) return;
  s.setDryRunLoading(true);
  s.setDryRunFilter('all');
  try {
    const resp = await httpDryRunSample(slice.sid, column, count);
    s.setDryRun(mapDryRunSample(resp));
  } catch (err) {
    console.error('[dry-run-sample] failed:', err);
    const msg = err instanceof Error ? err.message : 'dry run failed';
    s.setUiError({ code: 0, message: msg, retryAfter: 0, lastRow: 0 });
  } finally {
    s.setDryRunLoading(false);
  }
}

export function closeDryRun(): void {
  const s = useStore.getState();
  s.setDryRun(undefined);
  s.setDryRunFilter('all');
  s.setDryRunLoading(false);
}

// ─── per-row actions ────────────────────────────────────────────────────

export async function rerunRow(n: number): Promise<void> {
  const s = useStore.getState();
  const slice = s.fullname;
  if (!slice.sid) return;
  s.markRowInFlight(n);
  const existing = slice.rows.find((r) => r.n === n);
  if (existing) {
    s.upsertRow({ ...existing, status: 'pending', reason: '' });
  }
  try {
    const updated = await httpRerunRow(slice.sid, n);
    s.upsertRow(updated);
  } catch (err) {
    console.error('[rerun-row] failed:', err);
    if (existing) s.upsertRow(existing);
  } finally {
    s.unmarkRowInFlight(n);
  }
}

export async function overrideRow(
  n: number,
  first: string | null,
  last: string | null,
): Promise<void> {
  const s = useStore.getState();
  const slice = s.fullname;
  if (!slice.sid) return;
  s.markRowInFlight(n);
  try {
    const updated = await httpOverrideRow(slice.sid, n, first, last);
    s.upsertRow(updated);
  } catch (err) {
    console.error('[override] failed:', err);
  } finally {
    s.unmarkRowInFlight(n);
  }
}

// ─── reset / soft reset ─────────────────────────────────────────────────

export function resetSlice(): void {
  useStore.getState().resetSlice();
}

// Back-compat alias for components that still import `resetActive`.
export const resetActive = resetSlice;

// ─── back-button policy ─────────────────────────────────────────────────

export interface BackAction {
  label: string;
  onClick: () => void;
}
export function getBackAction(): BackAction | null {
  const s = useStore.getState();
  const slice = s.fullname;
  if (slice.dryRun != null || slice.dryRunLoading) {
    return { label: 'Back to table', onClick: () => closeDryRun() };
  }
  const v = viewState(slice);
  switch (v) {
    case 'awaiting_column':
      return {
        label: 'Pick a different file',
        onClick: () => s.resetSlice(),
      };
    case 'indexed':
      return {
        label: 'Pick a different column',
        onClick: () => {
          s.replaceRows([]);
          s.setColumn('');
          s.setRunState('uploaded');
        },
      };
    case 'error':
      return {
        label: 'Back to table',
        onClick: () => {
          s.setUiError(undefined);
          s.setSpendBlocked(undefined);
          s.setRunState(slice.rows.length ? 'done' : 'uploaded');
        },
      };
    default:
      return null;
  }
}

// ─── SSE plumbing ────────────────────────────────────────────────────────

function openSse(): void {
  const s = useStore.getState();
  const slice = s.fullname;
  if (!slice.sid) return;
  slice.eventStream?.close();
  const sid = slice.sid;
  const es = openEventStream(sid, (ev) => handleSseEvent(ev, sid));
  s.setEventStream(es);
}

// ─── boot ───────────────────────────────────────────────────────────────

let bootDone = false;
export function boot(): void {
  if (bootDone) return;
  bootDone = true;
  void refreshWhoami();
  void refreshSettings();
  // Lightweight whoami poll so the topbar's spend-cap chip stays fresh.
  setInterval(() => {
    void refreshWhoami();
  }, 30_000);
}
