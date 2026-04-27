import { useSlice } from '../store';
import type { Kind } from '../types';

export function ColumnPicker({ kind }: { kind: Kind }) {
  const slice = useSlice(kind);
  const cols = slice.columns?.columns ?? [];

  if (!slice.upload || !slice.columns) return null;

  const isLocked = slice.state === 'running';

  return (
    <section className="column-picker">
      <div className="file-summary">
        <div className="file-summary-name">{slice.upload.filename}</div>
        <div className="file-summary-meta">
          {slice.columns.row_count_estimate.toLocaleString()} rows ·{' '}
          {(slice.upload.size_bytes / 1024).toFixed(1)} KB
          {!isLocked && (
            <button className="link-btn" onClick={slice.reset}>
              upload a different file
            </button>
          )}
        </div>
      </div>
      <div className="columns-list">
        <div className="columns-label">Pick the column to clean:</div>
        <div className="columns-grid">
          {cols.map((c) => {
            const selected = slice.selectedColumn === c.name;
            const suggested = slice.columns?.suggested === c.name;
            return (
              <button
                key={c.name}
                type="button"
                disabled={isLocked}
                className={`column-card ${selected ? 'column-card--selected' : ''}`}
                onClick={() => slice.setSelectedColumn(c.name)}
              >
                <div className="column-name">
                  {c.name}
                  {suggested && <span className="column-suggested">suggested</span>}
                </div>
                {c.samples.length > 0 && (
                  <ul className="column-samples">
                    {c.samples.slice(0, 4).map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
