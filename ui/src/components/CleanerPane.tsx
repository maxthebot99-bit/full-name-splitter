// One pane = one cleaner kind. Wires the whole flow:
// idle → upload → columns_loaded → running → done|cancelled|error|spend_blocked

import { useEffect } from 'react';
import { useSlice, useStore } from '../store';
import * as api from '../api';
import type { Kind, Row, SseEvent, Telemetry } from '../types';
import { DropZone } from './DropZone';
import { ColumnPicker } from './ColumnPicker';
import { RunPanel } from './RunPanel';
import { ResultsTable } from './ResultsTable';
import { ErrorBanner } from './ErrorBanner';

export function CleanerPane({ kind }: { kind: Kind }) {
  const slice = useSlice(kind);

  // Tear down any active SSE on unmount. Read the slice fresh from the
  // store so we don't close a stale (likely-undefined) reference captured
  // at first render.
  useEffect(() => {
    return () => {
      useStore.getState()[kind].eventStream?.close();
    };
  }, [kind]);

  return (
    <div className="cleaner">
      <ErrorBanner kind={kind} />
      {slice.state === 'idle' && <DropZoneStep kind={kind} />}
      {slice.state === 'uploaded' && <ColumnsLoadingStep kind={kind} />}
      {(slice.state === 'columns_loaded' ||
        slice.state === 'running' ||
        slice.state === 'done' ||
        slice.state === 'cancelled' ||
        slice.state === 'error' ||
        slice.state === 'spend_blocked') && <ColumnPickerStep kind={kind} />}
    </div>
  );
}

// ─── Steps ──────────────────────────────────────────────────────────────────

function DropZoneStep({ kind }: { kind: Kind }) {
  const slice = useSlice(kind);

  async function onFile(f: File) {
    slice.setError(undefined);
    try {
      const u = await api.uploadFile(kind, f);
      slice.setUpload(u);
      const c = await api.getColumns(u.sid);
      slice.setColumns(c);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      slice.setError({ code: 0, message: msg });
    }
  }

  return <DropZone kind={kind} onFile={onFile} />;
}

function ColumnsLoadingStep({ kind }: { kind: Kind }) {
  const slice = useSlice(kind);
  // Could happen if columns fetch fails — show a hint to re-upload.
  return (
    <div className="step-loading">
      <div>Loading columns…</div>
      <button className="btn-secondary" onClick={slice.reset}>
        Cancel
      </button>
    </div>
  );
}

function ColumnPickerStep({ kind }: { kind: Kind }) {
  const slice = useSlice(kind);
  const setWhoami = useStore((s) => s.setWhoami);

  async function startTheRun() {
    if (!slice.upload || !slice.selectedColumn) return;
    const sid = slice.upload.sid;

    // Fresh dry-run for the cost preview & spend-cap check
    try {
      const dr = await api.dryRun(sid, slice.selectedColumn, slice.rowLimit);
      slice.setDryRun(dr);
      if (dr.would_exceed_cap) {
        slice.setError({
          code: 0,
          message: `Would exceed today's $${dr.cap_usd.toFixed(2)} cap (already $${dr.today_usd.toFixed(2)} used + estimated $${dr.estimated_cost_usd.toFixed(2)} for this run).`,
        });
        return;
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      slice.setError({ code: 0, message: msg });
      return;
    }

    // Wire SSE BEFORE start_run so we don't miss the leading state event
    const es = api.openEventStream(sid, (ev) => handleSseEvent(kind, ev));
    slice.setEventStream(es);
    slice.setState('running');
    slice.upsertRows([]); // clear any prior run's rows in this slice
    slice.setError(undefined);

    try {
      await api.startRun(sid, slice.selectedColumn, slice.rowLimit);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      slice.setError({ code: 0, message: msg });
      slice.setState('error');
      es.close();
    }

    // Refresh whoami once shortly after to update the spend bar
    setTimeout(() => {
      api.whoami().then(setWhoami).catch(() => {});
    }, 1000);
  }

  return (
    <div className="step-run">
      <ColumnPicker kind={kind} />
      <RunPanel kind={kind} onStart={startTheRun} />
      <ResultsTable kind={kind} />
    </div>
  );
}

// ─── SSE event handler ──────────────────────────────────────────────────────

function handleSseEvent(kind: Kind, ev: SseEvent) {
  const slice = useStore.getState()[kind];
  switch (ev.kind) {
    case 'hello':
      // session id ack
      break;
    case 'state': {
      const newState = ev.payload as string;
      // Mirror server states; the SSE stream auto-closes on terminal states.
      if (
        newState === 'running' ||
        newState === 'done' ||
        newState === 'cancelled' ||
        newState === 'error' ||
        newState === 'spend_blocked'
      ) {
        slice.setState(newState);
      }
      break;
    }
    case 'rows': {
      slice.upsertRows(ev.payload as Row[]);
      break;
    }
    case 'row_update': {
      slice.upsertRows([ev.payload as Row]);
      break;
    }
    case 'telemetry': {
      slice.setTelemetry(ev.payload as Partial<Telemetry>);
      break;
    }
    case 'error': {
      const err = ev.payload as { code: number; message: string };
      slice.setError(err);
      break;
    }
    case 'spend_cap_hit': {
      const p = ev.payload as { today_usd: number; cap_usd: number };
      slice.setSpendBlocked({ todayUsd: p.today_usd, capUsd: p.cap_usd });
      break;
    }
    default:
      // Future events (xai_throttled, etc.) — ignored for now.
      break;
  }
}
