import { useSlice } from '../store';
import * as api from '../api';
import type { Kind } from '../types';

export function RunPanel({ kind, onStart }: { kind: Kind; onStart: () => void }) {
  const slice = useSlice(kind);
  const sid = slice.upload?.sid;

  const isRunning = slice.state === 'running';
  const isDone = slice.state === 'done';
  const isCancelled = slice.state === 'cancelled';
  const isSpendBlocked = slice.state === 'spend_blocked';
  const isError = slice.state === 'error';
  const canStart =
    slice.state === 'columns_loaded' ||
    slice.state === 'cancelled' ||
    slice.state === 'error' ||
    slice.state === 'spend_blocked';

  const total = slice.columns?.row_count_estimate ?? 0;
  const processed = slice.rows.length;
  const pct = total > 0 ? Math.min(100, (processed / total) * 100) : 0;
  const t = slice.telemetry;

  return (
    <section className="run-panel">
      <div className="run-row">
        <div className="run-controls">
          <label className="row-limit">
            <span>Row limit (optional):</span>
            <input
              type="number"
              min={1}
              max={1_000_000}
              placeholder="all"
              value={slice.rowLimit ?? ''}
              disabled={isRunning}
              onChange={(e) => {
                const v = e.target.value;
                slice.setRowLimit(v ? parseInt(v, 10) : undefined);
              }}
            />
          </label>
          {canStart && (
            <button
              className="btn-primary"
              disabled={!slice.selectedColumn}
              onClick={onStart}
            >
              {isError || isCancelled ? 'Run again' : 'Clean rows'}
            </button>
          )}
          {isRunning && sid && (
            <button
              className="btn-danger"
              onClick={() => api.cancelRun(sid).catch(console.warn)}
            >
              Cancel
            </button>
          )}
          {isDone && sid && (
            <a className="btn-primary" href={api.downloadUrl(sid)} download>
              Download cleaned CSV
            </a>
          )}
        </div>
        <div className="run-stats">
          <Stat label="Rows" value={`${processed.toLocaleString()} / ${total.toLocaleString()}`} />
          <Stat label="Cost" value={`$${t.costUsd.toFixed(4)}`} />
          <Stat label="Tokens" value={`${(t.tokensIn + t.tokensOut).toLocaleString()}`} />
          {t.rowsPerSecond > 0 && <Stat label="rows/s" value={t.rowsPerSecond.toFixed(1)} />}
        </div>
      </div>
      {(isRunning || isDone || isCancelled) && (
        <div className="progress">
          <div
            className={`progress-fill ${isRunning ? 'progress-fill--running' : ''}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
      {isSpendBlocked && (
        <div className="spend-blocked-banner">
          Daily $10 spend cap hit. Try again after 00:00 UTC, or bump the cap in code &amp; redeploy.
        </div>
      )}
      {isRunning && (
        <div className="run-warning">
          Don&apos;t refresh this tab — the run keeps going on the server, but the live progress will stop streaming.
        </div>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}
