// Zustand store. One slice per kind (company / name) plus shared whoami.

import { create } from 'zustand';
import type { ColumnsResponse, DryRunResponse, ErrorPayload, Kind, Row, RunState, Telemetry, UploadResponse, WhoamiResponse } from './types';

const EMPTY_TELEMETRY: Telemetry = {
  rowsPerSecond: 0,
  tokensIn: 0,
  tokensOut: 0,
  nullCount: 0,
  rulesFired: 0,
  costUsd: 0,
};

export interface KindSlice {
  kind: Kind;
  state: RunState;
  upload?: UploadResponse;
  columns?: ColumnsResponse;
  selectedColumn?: string;
  rowLimit?: number;
  dryRun?: DryRunResponse;
  rows: Row[];
  telemetry: Telemetry;
  error?: ErrorPayload;
  spendBlocked?: { todayUsd: number; capUsd: number };
  eventStream?: EventSource;

  // mutations
  reset: () => void;
  setUpload: (u: UploadResponse) => void;
  setColumns: (c: ColumnsResponse) => void;
  setSelectedColumn: (c: string | undefined) => void;
  setRowLimit: (n: number | undefined) => void;
  setDryRun: (d: DryRunResponse | undefined) => void;
  setState: (s: RunState) => void;
  upsertRows: (rows: Row[]) => void;
  setTelemetry: (t: Partial<Telemetry>) => void;
  setError: (e: ErrorPayload | undefined) => void;
  setSpendBlocked: (b: { todayUsd: number; capUsd: number } | undefined) => void;
  setEventStream: (es: EventSource | undefined) => void;
}

interface RootState {
  whoami?: WhoamiResponse;
  setWhoami: (w: WhoamiResponse) => void;
  active: Kind;
  setActive: (k: Kind) => void;
  company: KindSlice;
  name: KindSlice;
}

export const useStore = create<RootState>((set, get) => {
  const initSlice = (kind: Kind): KindSlice => ({
    kind,
    state: 'idle',
    rows: [],
    telemetry: { ...EMPTY_TELEMETRY },
    reset: () => {
      const cur = get()[kind];
      cur.eventStream?.close();
      set((s) => ({
        ...s,
        [kind]: {
          ...initSlice(kind),
        },
      }));
    },
    setUpload: (u) =>
      set((s) => ({ ...s, [kind]: { ...s[kind], upload: u, state: 'uploaded' } })),
    setColumns: (c) =>
      set((s) => ({
        ...s,
        [kind]: {
          ...s[kind],
          columns: c,
          state: 'columns_loaded',
          selectedColumn: c.suggested ?? s[kind].selectedColumn,
        },
      })),
    setSelectedColumn: (c) =>
      set((s) => ({ ...s, [kind]: { ...s[kind], selectedColumn: c } })),
    setRowLimit: (n) =>
      set((s) => ({ ...s, [kind]: { ...s[kind], rowLimit: n } })),
    setDryRun: (d) =>
      set((s) => ({ ...s, [kind]: { ...s[kind], dryRun: d } })),
    setState: (st) =>
      set((s) => ({ ...s, [kind]: { ...s[kind], state: st } })),
    upsertRows: (rows) => {
      const cur = get()[kind].rows;
      const idx = new Map<number, number>();
      cur.forEach((r, i) => idx.set(r.n, i));
      const next = cur.slice();
      for (const r of rows) {
        const i = idx.get(r.n);
        if (i === undefined) {
          next.push(r);
          idx.set(r.n, next.length - 1);
        } else {
          next[i] = r;
        }
      }
      next.sort((a, b) => a.n - b.n);
      set((s) => ({ ...s, [kind]: { ...s[kind], rows: next } }));
    },
    setTelemetry: (t) =>
      set((s) => ({
        ...s,
        [kind]: { ...s[kind], telemetry: { ...s[kind].telemetry, ...t } },
      })),
    setError: (e) =>
      set((s) => ({ ...s, [kind]: { ...s[kind], error: e } })),
    setSpendBlocked: (b) =>
      set((s) => ({ ...s, [kind]: { ...s[kind], spendBlocked: b } })),
    setEventStream: (es) =>
      set((s) => ({ ...s, [kind]: { ...s[kind], eventStream: es } })),
  });
  return {
    active: 'company',
    setActive: (k) => set((s) => ({ ...s, active: k })),
    setWhoami: (w) => set((s) => ({ ...s, whoami: w })),
    company: initSlice('company'),
    name: initSlice('name'),
  };
});

export function useSlice(kind: Kind): KindSlice {
  return useStore((s) => s[kind]);
}
