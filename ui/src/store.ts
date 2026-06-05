// Zustand store — splitter shape (single ``fullname`` kind).
//
// Phase C stripped this from the cleaners-hub multi-slice architecture
// (company / name / address) down to ONE slice. Callsites that used to
// pass `kind` everywhere now operate implicitly on the single slice; the
// SSE dispatcher routes events directly into it.

import { create } from 'zustand';
import type {
  AppSettings,
  AppState,
  CostModalState,
  DryRunUiResult,
  ErrorPayload,
  FileMeta,
  FilterKind,
  Progress,
  Row,
  RunRecord,
  RunState,
  SseEvent,
  Telemetry,
  UiError,
  WhoamiResponse,
} from './types';
import { mapDryRunSample } from './lib/mapping';

const initialProgress: Progress = {
  processed: 0,
  total: 0,
  etaSeconds: 0,
  elapsedSeconds: 0,
};

const initialTelemetry: Telemetry = {
  rowsPerSecond: 0,
  rowsPerSecondHistory: [],
  tokensIn: 0,
  tokensOut: 0,
  nullCount: 0,
  rulesFired: 0,
  costUsd: 0,
};

export interface KindSlice {
  // Backend session state, as last seen on SSE / HTTP.
  runState: RunState;
  // Session id from the most recent /api/upload.
  sid?: string;
  file?: FileMeta;
  progress: Progress;
  telemetry: Telemetry;
  rows: Row[];
  selectedRowIdx?: number;
  error?: UiError;
  spendBlocked?: { todayUsd: number; capUsd: number };
  filter: FilterKind;
  // Dry-run sample overlay — populated while sample results are visible.
  dryRun?: DryRunUiResult;
  dryRunFilter: 'all' | 'changed' | 'same' | 'flag' | 'blank';
  dryRunLoading: boolean;
  // Cost-ceiling confirm modal.
  costModal?: CostModalState;
  // Mapper selection — the column the user clicked but hasn't confirmed yet.
  mapperSelectedColumn?: string;
  // Active SSE subscription, if any.
  eventStream?: EventSource;
  // Wall-clock millis (Date.now()) of the last telemetry frame the store
  // saw. N2Progress / N2Telemetry / N2Thinking extrapolate forward from
  // this point using rowsPerSecond so the UI moves smoothly between
  // batches instead of sitting still and then jumping.
  lastTelemetryAt?: number;
  // Row numbers currently being rerun via ▶ (or override). Drives the
  // sidebar's clay-style "thinking" strip — when this is non-empty we
  // visually mirror the running state even though runState may be done.
  rowsInFlight: number[];
}

interface RootState {
  whoami?: WhoamiResponse;
  settings?: AppSettings;
  // Run-history drawer state — list of runs is fetched on open.
  history: { open: boolean; loading: boolean; runs: RunRecord[]; total: number };
  // Settings modal open/closed.
  settingsModalOpen: boolean;
  fullname: KindSlice;
}

interface RootActions {
  setWhoami: (w: WhoamiResponse) => void;
  setSettings: (s: AppSettings) => void;
  setSettingsModalOpen: (open: boolean) => void;
  setHistory: (patch: Partial<RootState['history']>) => void;
  resetSlice: () => void;
  patchSlice: (patch: Partial<KindSlice>) => void;
  setRunState: (s: RunState) => void;
  setFile: (f?: FileMeta) => void;
  setColumn: (col: string) => void;
  setProgress: (p: Partial<Progress>) => void;
  setTelemetry: (t: Partial<Telemetry>) => void;
  appendRows: (rs: Row[]) => void;
  upsertRow: (r: Row) => void;
  upsertRows: (rs: Row[]) => void;
  replaceRows: (rs: Row[]) => void;
  selectRow: (idx?: number) => void;
  setUiError: (e?: UiError) => void;
  setSpendBlocked: (b?: { todayUsd: number; capUsd: number }) => void;
  setFilter: (f: FilterKind) => void;
  setDryRun: (d?: DryRunUiResult) => void;
  setDryRunFilter: (f: KindSlice['dryRunFilter']) => void;
  setDryRunLoading: (b: boolean) => void;
  setCostModal: (m?: CostModalState) => void;
  setMapperSelectedColumn: (col?: string) => void;
  setEventStream: (es?: EventSource) => void;
  markRowInFlight: (n: number) => void;
  unmarkRowInFlight: (n: number) => void;
}

type Store = RootState & RootActions;

function freshSlice(): KindSlice {
  return {
    runState: 'idle',
    progress: { ...initialProgress },
    telemetry: { ...initialTelemetry },
    rows: [],
    filter: 'all',
    dryRunFilter: 'all',
    dryRunLoading: false,
    rowsInFlight: [],
  };
}

/**
 * Count of rows the backend has finished processing for the slice.
 * Preview rows pre-populated before the run sit at status='pending' and
 * are excluded.
 */
export function processedRowCount(slice: KindSlice): number {
  return slice.rows.filter((r) => r.status !== 'pending').length;
}


// Map (runState + slice presence) → AppState for view conditionals.
export function viewState(slice: KindSlice): AppState {
  if (slice.runState === 'running') return 'running';
  if (slice.runState === 'done') return 'done';
  // Cancellation is NOT an error — the user did it on purpose. Keep the
  // table visible with whatever rows were cleaned, and let them resume
  // via "Continue cleaning" (the worker skips already-done rows).
  if (slice.runState === 'cancelled') return 'cancelled';
  if (slice.runState === 'error' || slice.runState === 'spend_blocked') {
    return 'error';
  }
  if (!slice.sid || !slice.file) return 'empty';
  if (!slice.file.column) return 'awaiting_column';
  return 'indexed';
}

export const useStore = create<Store>((set, get) => {
  const update = (patch: Partial<KindSlice>) =>
    set((s) => ({ fullname: { ...s.fullname, ...patch } }));

  return {
    history: { open: false, loading: false, runs: [], total: 0 },
    settingsModalOpen: false,
    fullname: freshSlice(),

    setWhoami: (w) => set({ whoami: w }),
    setSettings: (s) => set({ settings: s }),
    setSettingsModalOpen: (open) => set({ settingsModalOpen: open }),
    setHistory: (patch) =>
      set((s) => ({ history: { ...s.history, ...patch } })),

    resetSlice: () => {
      const cur = get().fullname;
      cur.eventStream?.close();
      set({ fullname: freshSlice() });
    },
    patchSlice: update,
    setRunState: (st) => update({ runState: st }),
    setFile: (f) => update({ file: f }),
    setColumn: (col) => {
      const cur = get().fullname;
      if (!cur.file) return;
      update({ file: { ...cur.file, column: col } });
    },
    setProgress: (p) => {
      const cur = get().fullname;
      update({ progress: { ...cur.progress, ...p } });
    },
    setTelemetry: (t) => {
      const cur = get().fullname;
      // Maintain a 60-sample throughput history so the sparkline reflects
      // real backend telemetry and not a fixture.
      let history = cur.telemetry.rowsPerSecondHistory;
      if (typeof t.rowsPerSecond === 'number') {
        history = [...history, t.rowsPerSecond].slice(-60);
      }
      update({
        telemetry: { ...cur.telemetry, ...t, rowsPerSecondHistory: history },
        lastTelemetryAt: Date.now(),
      });
    },
    appendRows: (rs) => {
      const cur = get().fullname;
      update({ rows: [...cur.rows, ...rs] });
    },
    upsertRow: (r) => {
      const cur = get().fullname;
      const idx = cur.rows.findIndex((x) => x.n === r.n);
      if (idx === -1) {
        update({ rows: [...cur.rows, r] });
        return;
      }
      const next = cur.rows.slice();
      next[idx] = r;
      update({ rows: next });
    },
    upsertRows: (rs) => {
      const cur = get().fullname;
      const next = cur.rows.slice();
      const idxByN = new Map<number, number>();
      for (let i = 0; i < next.length; i++) idxByN.set(next[i].n, i);
      for (const r of rs) {
        const idx = idxByN.get(r.n);
        if (idx === undefined) {
          idxByN.set(r.n, next.length);
          next.push(r);
        } else {
          next[idx] = r;
        }
      }
      update({ rows: next });
    },
    replaceRows: (rs) => update({ rows: rs }),
    selectRow: (idx) => update({ selectedRowIdx: idx }),
    setUiError: (e) => update({ error: e }),
    setSpendBlocked: (b) => update({ spendBlocked: b }),
    setFilter: (f) => update({ filter: f }),
    setDryRun: (d) => update({ dryRun: d }),
    setDryRunFilter: (f) => update({ dryRunFilter: f }),
    setDryRunLoading: (b) => update({ dryRunLoading: b }),
    setCostModal: (m) => update({ costModal: m }),
    setMapperSelectedColumn: (col) => update({ mapperSelectedColumn: col }),
    setEventStream: (es) => update({ eventStream: es }),
    markRowInFlight: (n) => {
      const cur = get().fullname;
      if (cur.rowsInFlight.includes(n)) return;
      update({ rowsInFlight: [...cur.rowsInFlight, n] });
    },
    unmarkRowInFlight: (n) => {
      const cur = get().fullname;
      const next = cur.rowsInFlight.filter((x) => x !== n);
      if (next.length === cur.rowsInFlight.length) return;
      update({ rowsInFlight: next });
    },
  };
});

// ─── SSE event dispatcher ──────────────────────────────────────────────
// Backend pushes events with these kinds (see workers.py / streaming.py):
//   hello | state | rows | row_update | telemetry | error | spend_cap_hit
// `expectedSid` is the sid that owned the stream at subscription time —
// if the slice's current sid has rotated (user reset and re-uploaded),
// we drop the event so leftover frames from the old stream can't bleed
// into the new session's state.

export function handleSseEvent(ev: SseEvent, expectedSid?: string): void {
  const s = useStore.getState();
  const slice = s.fullname;
  if (expectedSid && slice.sid && slice.sid !== expectedSid) {
    // Stale stream — the slice's session has been replaced since this
    // handler was attached. Discard.
    return;
  }
  switch (ev.kind) {
    case 'hello':
      // {sid} — no-op; we already know the sid.
      break;
    case 'state': {
      const next = ev.payload as RunState;
      s.setRunState(next);
      if (next === 'done' || next === 'cancelled') {
        s.setSpendBlocked(undefined);
      }
      break;
    }
    case 'rows':
      s.upsertRows(ev.payload as Row[]);
      break;
    case 'row_update':
      s.upsertRow(ev.payload as Row);
      break;
    case 'telemetry': {
      const t = ev.payload as Partial<Telemetry>;
      s.setTelemetry(t);
      // Backend telemetry doesn't include processed/total — derive from rows
      // by re-reading the LIVE slice (the snapshot above can be stale by the
      // time SSE events trickle in over a long run).
      const live = useStore.getState().fullname;
      const total = live.file?.rows ?? 0;
      const processed = live.rows.filter((r) => r.status !== 'pending').length;
      const elapsedHint = (t as { elapsed_s?: number }).elapsed_s;
      s.setProgress({
        processed,
        total,
        elapsedSeconds:
          typeof elapsedHint === 'number'
            ? elapsedHint
            : live.progress.elapsedSeconds,
        etaSeconds:
          processed > 0 && total > 0 && t.rowsPerSecond
            ? Math.max(0, (total - processed) / Math.max(0.1, t.rowsPerSecond))
            : live.progress.etaSeconds,
      });
      break;
    }
    case 'error': {
      const e = ev.payload as ErrorPayload;
      s.setUiError({
        code: e.code,
        message: e.message,
        retryAfter: 12, // backend doesn't surface a Retry-After; default
        lastRow: useStore.getState().fullname.progress.processed + 1,
      });
      break;
    }
    case 'spend_cap_hit': {
      const p = ev.payload as { today_usd: number; cap_usd: number };
      s.setSpendBlocked({ todayUsd: p.today_usd, capUsd: p.cap_usd });
      break;
    }
    case 'cost_estimate_update': {
      // Adaptive cost projection — backend tightens the forecast after
      // every batch by averaging actual tokens/row. We patch the same
      // Telemetry slice so the UI's projected-total + tokens-per-row
      // tiles snap to truth between batches.
      const p = ev.payload as {
        costSpentSoFar?: number;
        costProjectedTotal?: number;
        tokensPerRowAvg?: number;
      };
      s.setTelemetry({
        costSpentSoFar: p.costSpentSoFar,
        costProjectedTotal: p.costProjectedTotal,
        tokensPerRowAvg: p.tokensPerRowAvg,
      });
      break;
    }
    default:
      // Unknown event — log once, ignore.
      console.warn('[sse] unknown event kind:', ev.kind, ev.payload);
  }
}

// Convenience for components that want the slice as live state.
export function useSlice(): KindSlice {
  return useStore((s) => s.fullname);
}

// Re-export so callers don't have to know about the lib/ split.
export { mapDryRunSample };
