import { useSlice } from '../store';
import type { Kind, RowStatus } from '../types';

const STATUS_LABEL: Record<RowStatus, string> = {
  changed: 'changed',
  unchanged: 'no change',
  null: 'null',
  pending: 'pending',
};

export function ResultsTable({ kind }: { kind: Kind }) {
  const slice = useSlice(kind);
  const rows = slice.rows;
  if (rows.length === 0) {
    if (slice.state === 'running') return <div className="results-empty">Waiting for first batch…</div>;
    return null;
  }

  // Show last 200 rows for performance — full file is in the download.
  const visible = rows.slice(-200);

  return (
    <section className="results">
      <div className="results-header">
        <span>Results (last {visible.length} of {rows.length.toLocaleString()})</span>
      </div>
      <div className="results-table-wrap">
        <table className="results-table">
          <thead>
            <tr>
              <th className="col-n">#</th>
              <th className="col-orig">Original</th>
              <th className="col-clean">Cleaned</th>
              <th className="col-status">Status</th>
              <th className="col-reason">Reason</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.n}>
                <td className="col-n">{r.n}</td>
                <td className="col-orig">{r.orig}</td>
                <td className="col-clean">
                  {r.clean === null ? <span className="muted">—</span> : r.clean}
                </td>
                <td className="col-status">
                  <span className={`pill pill--${r.status}`}>{STATUS_LABEL[r.status]}</span>
                </td>
                <td className="col-reason">{r.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
