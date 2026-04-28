// Zustand store. One slice per kind (company / name) shaped to mirror the
// desktop Nocturne store, plus shared whoami / settings / history. SSE
// events are dispatched into the active slice via `handleSseEvent`.

import { create } from 'zustand';
import type {
  AppSettings,
  AppState,
  CostModalState,
  DryRunUiResult,
  ErrorPayload,
  FileMeta,
  FilterKind,
  Kind,
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
  kind: Kind;
  // Backend session state, as last seen on SSE / HTTP.
  runState: RunState;
  // Session id from the most recent /api/upload for this kind.
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
  // Cost-ceiling confirm modal (per-kind so the right slice's run starts).
  costModal?: CostModalState;
  // Mapper selection — the column the user clicked but hasn't confirmed yet.
  mapperSelectedColumn?: string;
  // Active SSE subscription, if any.
  eventStream?: EventSource;
  // Wall-clock millis (Date.now()) of the last telemetry frame the store
  // saw. The N2Progress / N2Telemetry / N2Thinking components extrapolate
  // forward from this point using rowsPerSecond so the UI moves smoothly
  // between batches instead of sitting still for ~14s and then jumping.
  lastTelemetryAt?: number;
  // Row numbers currently being rerun via ▶ (or override). Drives the
  // sidebar's clay-style "thinking" strip — when this is non-empty we
  // visually mirror the running state even though runState is still
  // 'columns_loaded' / 'done'.
  rowsInFlight: number[];
}

interface RootState {
  active: Kind;
  whoami?: WhoamiResponse;
  settings?: AppSettings;
  // Run-history drawer state — list of runs is fetched on open.
  history: { open: boolean; loading: boolean; runs: RunRecord[]; total: number };
  // Settings modal open/closed.
  settingsModalOpen: boolean;
  company: KindSlice;
  name: KindSlice;
}

interface RootActions {
  setActive: (k: Kind) => void;
  setWhoami: (w: WhoamiResponse) => void;
  setSettings: (s: AppSettings) => void;
  setSettingsModalOpen: (open: boolean) => void;
  setHistory: (patch: Partial<RootState['history']>) => void;
  // Slice mutators — k is the target slice; defaults to active when omitted.
  resetSlice: (k?: Kind) => void;
  patchSlice: (k: Kind, patch: Partial<KindSlice>) => void;
  setRunState: (k: Kind, s: RunState) => void;
  setFile: (k: Kind, f?: FileMeta) => void;
  setColumn: (k: Kind, col: string) => void;
  setProgress: (k: Kind, p: Partial<Progress>) => void;
  setTelemetry: (k: Kind, t: Partial<Telemetry>) => void;
  appendRows: (k: Kind, rs: Row[]) => void;
  upsertRow: (k: Kind, r: Row) => void;
  upsertRows: (k: Kind, rs: Row[]) => void;
  replaceRows: (k: Kind, rs: Row[]) => void;
  selectRow: (k: Kind, idx?: number) => void;
  setUiError: (k: Kind, e?: UiError) => void;
  setSpendBlocked: (k: Kind, b?: { todayUsd: number; capUsd: number }) => void;
  setFilter: (k: Kind, f: FilterKind) => void;
  setDryRun: (k: Kind, d?: DryRunUiResult) => void;
  setDryRunFilter: (k: Kind, f: KindSlice['dryRunFilter']) => void;
  setDryRunLoading: (k: Kind, b: boolean) => void;
  setCostModal: (k: Kind, m?: CostModalState) => void;
  setMapperSelectedColumn: (k: Kind, col?: string) => void;
  setEventStream: (k: Kind, es?: EventSource) => void;
  markRowInFlight: (k: Kind, n: number) => void;
  unmarkRowInFlight: (k: Kind, n: number) => void;
}

type Store = RootState & RootActions;

function freshSlice(kind: Kind): KindSlice {
  return {
    kind,
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

// Map (runState + slice presence) → Nocturne AppState for view conditionals.
export function viewState(slice: KindSlice): AppState {
  if (slice.runState === 'running') return 'running';
  if (slice.runState === 'done') return 'done';
  if (
    slice.runState === 'error' ||
    slice.runState === 'spend_blocked' ||
    slice.runState === 'cancelled'
  ) {
    return 'error';
  }
  if (!slice.sid || !slice.file) return 'empty';
  if (!slice.file.column) return 'awaiting_column';
  return 'indexed';
}

export const useStore = create<Store>((set, get) => {
  const update = (k: Kind, patch: Partial<KindSlice>) =>
    set((s) => ({ [k]: { ...s[k], ...patch } }) as Partial<Store>);

  return {
    active: 'company',
    history: { open: false, loading: false, runs: [], total: 0 },
    settingsModalOpen: false,
    company: freshSlice('company'),
    name: freshSlice('name'),

    setActive: (k) => set({ active: k }),
    setWhoami: (w) => set({ whoami: w }),
    setSettings: (s) => set({ settings: s }),
    setSettingsModalOpen: (open) => set({ settingsModalOpen: open }),
    setHistory: (patch) =>
      set((s) => ({ history: { ...s.history, ...patch } })),

    resetSlice: (k) => {
      const target = k ?? get().active;
      const cur = get()[target];
      cur.eventStream?.close();
      set({ [target]: freshSlice(target) } as Partial<Store>);
    },
    patchSlice: update,
    setRunState: (k, st) => update(k, { runState: st }),
    setFile: (k, f) => update(k, { file: f }),
    setColumn: (k, col) => {
      const cur = get()[k];
      if (!cur.file) return;
      update(k, { file: { ...cur.file, column: col } });
    },
    setProgress: (k, p) => {
      const cur = get()[k];
      update(k, { progress: { ...cur.progress, ...p } });
    },
    setTelemetry: (k, t) => {
      const cur = get()[k];
      // Maintain a 60-sample throughput history so the sparkline reflects
      // real backend telemetry and not a fixture.
      let history = cur.telemetry.rowsPerSecondHistory;
      if (typeof t.rowsPerSecond === 'number') {
        history = [...history, t.rowsPerSecond].slice(-60);
      }
      update(k, {
        telemetry: { ...cur.telemetry, ...t, rowsPerSecondHistory: history },
        lastTelemetryAt: Date.now(),
      });
    },
    appendRows: (k, rs) => {
      const cur = get()[k];
      update(k, { rows: [...cur.rows, ...rs] });
    },
    upsertRow: (k, r) => {
      const cur = get()[k];
      const idx = cur.rows.findIndex((x) => x.n === r.n);
      if (idx === -1) {
        update(k, { rows: [...cur.rows, r] });
        return;
      }
      const next = cur.rows.slice();
      next[idx] = r;
      update(k, { rows: next });
    },
    upsertRows: (k, rs) => {
      const cur = get()[k];
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
      update(k, { rows: next });
    },
    replaceRows: (k, rs) => update(k, { rows: rs }),
    selectRow: (k, idx) => update(k, { selectedRowIdx: idx }),
    setUiError: (k, e) => update(k, { error: e }),
    setSpendBlocked: (k, b) => update(k, { spendBlocked: b }),
    setFilter: (k, f) => update(k, { filter: f }),
    setDryRun: (k, d) => update(k, { dryRun: d }),
    setDryRunFilter: (k, f) => update(k, { dryRunFilter: f }),
    setDryRunLoading: (k, b) => update(k, { dryRunLoading: b }),
    setCostModal: (k, m) => update(k, { costModal: m }),
    setMapperSelectedColumn: (k, col) => update(k, { mapperSelectedColumn: col }),
    setEventStream: (k, es) => update(k, { eventStream: es }),
    markRowInFlight: (k, n) => {
      const cur = get()[k];
      if (cur.rowsInFlight.includes(n)) return;
      update(k, { rowsInFlight: [...cur.rowsInFlight, n] });
    },
    unmarkRowInFlight: (k, n) => {
      const cur = get()[k];
      const next = cur.rowsInFlight.filter((x) => x !== n);
      if (next.length === cur.rowsInFlight.length) return;
      update(k, { rowsInFlight: next });
    },
  };
});

// ─── SSE event dispatcher ──────────────────────────────────────────────
// Backend pushes events with these kinds (see workers.py / streaming.py):
//   hello | state | rows | row_update | telemetry | error | spend_cap_hit
// The slice is determined by the sid/kind context the caller passed in.
// `expectedSid` is the sid that owned the stream at subscription time —
// if the slice's current sid has rotated (user reset and re-uploaded),
// we drop the event so leftover frames from the old stream can't bleed
// into the new session's state.

export function handleSseEvent(kind: Kind, ev: SseEvent, expectedSid?: string): void {
  const s = useStore.getState();
  const slice = s[kind];
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
      s.setRunState(kind, next);
      // When the backend says 'done', flip the spend-blocked flag off.
      if (next === 'done' || next === 'cancelled') {
        s.setSpendBlocked(kind, undefined);
      }
      break;
    }
    case 'rows':
      s.upsertRows(kind, ev.payload as Row[]);
      break;
    case 'row_update':
      s.upsertRow(kind, ev.payload as Row);
      break;
    case 'telemetry': {
      const t = ev.payload as Partial<Telemetry>;
      s.setTelemetry(kind, t);
      // Backend telemetry doesn't include processed/total — derive from rows
      // by re-reading the LIVE slice (not the snapshot above, which can be
      // stale by the time SSE events trickle in over a long run).
      const live = useStore.getState()[kind];
      const total = live.file?.rows ?? 0;
      const processed = live.rows.filter((r) => r.status !== 'pending').length;
      const elapsedHint = (t as { elapsed_s?: number }).elapsed_s;
      s.setProgress(kind, {
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
      s.setUiError(kind, {
        code: e.code,
        message: e.message,
        retryAfter: 12, // backend doesn't surface a Retry-After; default
        lastRow: useStore.getState()[kind].progress.processed + 1,
      });
      break;
    }
    case 'spend_cap_hit': {
      const p = ev.payload as { today_usd: number; cap_usd: number };
      s.setSpendBlocked(kind, { todayUsd: p.today_usd, capUsd: p.cap_usd });
      break;
    }
    default:
      // Unknown event — log once, ignore.
      console.warn('[sse] unknown event kind:', ev.kind, ev.payload);
  }
}

// Convenience for components that want the active slice as live state.
export function useSlice(kind: Kind): KindSlice {
  return useStore((s) => s[kind]);
}
export function useActiveSlice(): KindSlice {
  return useStore((s) => s[s.active]);
}

// Re-export so callers don't have to know about the lib/ split.
export { mapDryRunSample };
