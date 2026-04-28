// High-level actions — what UI components call. Wraps the HTTP api.ts and
// keeps the store consistent. Mirrors the shape of the desktop Nocturne
// api.ts (pickFile / listColumnsWithSamples / confirmColumn / startRun /
// dryRun / cancelRun / rerunRow / closeDryRun / getBackAction / etc.) but
// every backend hop is HTTP + SSE.

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
  Kind,
  MapperColumn,
  Row,
} from '../types';

function active(): Kind {
  return useStore.getState().active;
}

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
export function pickFile(kind?: Kind): void {
  const target = kind ?? active();
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.csv,.xlsx';
  input.onchange = () => {
    const f = input.files?.[0];
    if (f) void handleFileSelected(target, f);
  };
  input.click();
}

// Drop-target onDrop also routes through here.
export async function handleFileSelected(kind: Kind, file: File): Promise<void> {
  const s = useStore.getState();
  s.resetSlice(kind);
  try {
    const up = await uploadFile(kind, file);
    // Stash sid + provisional file meta so the empty/awaiting_column view
    // shows the filename right away. Columns + row count come from
    // /api/columns next.
    s.patchSlice(kind, {
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
    s.patchSlice(kind, {
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
    s.setUiError(kind, { code: 0, message: msg, retryAfter: 0, lastRow: 0 });
    s.setRunState(kind, 'error');
  }
}

// Mapper data — fetch /api/columns again (cheap; cached server-side via
// the session's _file_meta_obj) and compute display meta.
export async function listColumnsWithSamples(kind?: Kind): Promise<MapperColumn[]> {
  const target = kind ?? active();
  const slice = useStore.getState()[target];
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

export async function confirmColumn(column: string, kind?: Kind): Promise<void> {
  const target = kind ?? active();
  const s = useStore.getState();
  s.setColumn(target, column);
  s.setMapperSelectedColumn(target, undefined);
  s.setRunState(target, 'columns_loaded');
  // Fetch the first ~200 raw values for that column and seed them as
  // `pending` rows. The user sees actual data top-down before paying for
  // Grok; real cleaned values replace these in-place once the run starts.
  const slice = s[target];
  if (!slice.sid) return;
  const total = slice.file?.rows ?? 0;
  const n = Math.min(total > 0 ? total : 200, 200);
  try {
    const res = await httpPreview(slice.sid, column, n);
    s.replaceRows(target, res.rows);
  } catch (err) {
    console.warn('[preview] failed, falling back to empty placeholders:', err);
    const placeholders: Row[] = Array.from({ length: n }, (_, i) => ({
      n: i + 1,
      orig: '',
      clean: null,
      status: 'pending',
      reason: '',
    }));
    s.replaceRows(target, placeholders);
  }
}

// ─── run start (with $5 cost-ceiling modal) ─────────────────────────────

export function beginCleaningWithCostCheck(
  column: string,
  rowLimit?: number,
  kind?: Kind,
): void {
  const target = kind ?? active();
  const s = useStore.getState();
  const slice = s[target];
  const total = slice.file?.rows ?? 0;
  const effective = rowLimit && rowLimit > 0 ? Math.min(rowLimit, total) : total;
  const costUsd = estimateRunCost(effective);
  const elapsedSeconds = estimateRunSeconds(effective);
  if (costUsd > costCeiling()) {
    s.setCostModal(target, { rows: effective, costUsd, elapsedSeconds, column, rowLimit });
    return;
  }
  void startRun(column, rowLimit, target);
}

export function confirmCostModal(kind?: Kind): void {
  const target = kind ?? active();
  const s = useStore.getState();
  const m = s[target].costModal;
  s.setCostModal(target, undefined);
  if (!m) return;
  void startRun(m.column, m.rowLimit, target);
}
export function cancelCostModal(kind?: Kind): void {
  useStore.getState().setCostModal(kind ?? active(), undefined);
}

export async function startRun(
  column: string,
  rowLimit?: number,
  kind?: Kind,
): Promise<void> {
  const target = kind ?? active();
  const s = useStore.getState();
  const slice = s[target];
  if (!slice.sid) return;
  // Clear any prior dry-run / error state, but keep `pending` placeholders
  // so the table doesn't empty out at the start of every run.
  s.setDryRun(target, undefined);
  s.setUiError(target, undefined);
  s.setSpendBlocked(target, undefined);
  s.setRunState(target, 'running');
  // Open SSE before sending the start so we don't miss the first batch.
  openSseFor(target);
  try {
    await httpStartRun(slice.sid, column, rowLimit);
  } catch (err) {
    console.error('[run] start failed:', err);
    const msg = err instanceof Error ? err.message : 'run failed';
    s.setUiError(target, { code: 0, message: msg, retryAfter: 0, lastRow: 0 });
    s.setRunState(target, 'error');
  }
}

export async function cancelRun(kind?: Kind): Promise<void> {
  const target = kind ?? active();
  const s = useStore.getState();
  const slice = s[target];
  if (!slice.sid) return;
  try {
    await httpCancelRun(slice.sid);
  } catch (err) {
    console.warn('[cancel] failed:', err);
  }
}

// ─── dry-run sample ─────────────────────────────────────────────────────

export async function runDryRun(
  column: string,
  count = 25,
  kind?: Kind,
): Promise<void> {
  const target = kind ?? active();
  const s = useStore.getState();
  const slice = s[target];
  if (!slice.sid) return;
  s.setDryRunLoading(target, true);
  s.setDryRunFilter(target, 'all');
  try {
    const resp = await httpDryRunSample(slice.sid, column, count);
    s.setDryRun(target, mapDryRunSample(resp));
  } catch (err) {
    console.error('[dry-run-sample] failed:', err);
    const msg = err instanceof Error ? err.message : 'dry run failed';
    s.setUiError(target, { code: 0, message: msg, retryAfter: 0, lastRow: 0 });
  } finally {
    s.setDryRunLoading(target, false);
  }
}

export function closeDryRun(kind?: Kind): void {
  const target = kind ?? active();
  const s = useStore.getState();
  s.setDryRun(target, undefined);
  s.setDryRunFilter(target, 'all');
  s.setDryRunLoading(target, false);
}

// ─── per-row actions ────────────────────────────────────────────────────

export async function rerunRow(n: number, kind?: Kind): Promise<void> {
  const target = kind ?? active();
  const s = useStore.getState();
  const slice = s[target];
  if (!slice.sid) return;
  // Mark in-flight so the sidebar shows the clay-style "thinking" strip.
  s.markRowInFlight(target, n);
  // Optimistically flip the row to pending so the table reads correctly.
  const existing = slice.rows.find((r) => r.n === n);
  if (existing) {
    s.upsertRow(target, { ...existing, status: 'pending', reason: '' });
  }
  try {
    const updated = await httpRerunRow(slice.sid, n);
    s.upsertRow(target, updated);
  } catch (err) {
    console.error('[rerun-row] failed:', err);
    if (existing) s.upsertRow(target, existing);
  } finally {
    s.unmarkRowInFlight(target, n);
  }
}

export async function overrideRow(
  n: number,
  cleaned: string | null,
  kind?: Kind,
): Promise<void> {
  const target = kind ?? active();
  const s = useStore.getState();
  const slice = s[target];
  if (!slice.sid) return;
  s.markRowInFlight(target, n);
  try {
    const updated = await httpOverrideRow(slice.sid, n, cleaned);
    s.upsertRow(target, updated);
  } catch (err) {
    console.error('[override] failed:', err);
  } finally {
    s.unmarkRowInFlight(target, n);
  }
}

// ─── reset / soft reset ─────────────────────────────────────────────────

export function resetActive(): void {
  const s = useStore.getState();
  s.resetSlice(s.active);
}

// ─── back-button policy ─────────────────────────────────────────────────

export interface BackAction {
  label: string;
  onClick: () => void;
}
export function getBackAction(): BackAction | null {
  const s = useStore.getState();
  const slice = s[s.active];
  if (slice.dryRun != null || slice.dryRunLoading) {
    return { label: 'Back to table', onClick: () => closeDryRun() };
  }
  const v = viewState(slice);
  switch (v) {
    case 'awaiting_column':
      return {
        label: 'Pick a different file',
        onClick: () => s.resetSlice(s.active),
      };
    case 'indexed':
      return {
        label: 'Pick a different column',
        onClick: () => {
          s.replaceRows(s.active, []);
          s.setColumn(s.active, '');
          s.setRunState(s.active, 'uploaded');
        },
      };
    case 'error':
      return {
        label: 'Back to table',
        onClick: () => {
          s.setUiError(s.active, undefined);
          s.setSpendBlocked(s.active, undefined);
          s.setRunState(s.active, slice.rows.length ? 'done' : 'uploaded');
        },
      };
    default:
      return null;
  }
}

// ─── SSE plumbing ────────────────────────────────────────────────────────

function openSseFor(kind: Kind): void {
  const s = useStore.getState();
  const slice = s[kind];
  if (!slice.sid) return;
  // Close any existing stream before opening a new one.
  slice.eventStream?.close();
  const es = openEventStream(slice.sid, (ev) => handleSseEvent(kind, ev));
  s.setEventStream(kind, es);
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
