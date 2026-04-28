import { useState } from 'react';
import { N2, fMono } from '../../theme';
import type { AppState } from '../../types';
import { useStore } from '../../store';
import {
  beginCleaningWithCostCheck,
  cancelRun,
  confirmColumn,
  runDryRun,
  startRun,
} from '../../lib/actions';
import { estimateRunCost } from '../../api';
import { N2SidebarHeadline } from './sidebar/N2SidebarHeadline';
import { N2FileCard } from './sidebar/N2FileCard';
import { N2EmptyDrop } from './sidebar/N2EmptyDrop';
import { N2CtaPrimary } from './sidebar/N2CtaPrimary';
import { N2Progress } from './sidebar/N2Progress';
import { N2Telemetry } from './sidebar/N2Telemetry';

// Sub-cent costs round to "$0.00" with toFixed(2), which under-reads
// reality on small files. Shift to 4-decimal display below $0.01 so a
// 749-row estimate renders as "$0.0082" instead of a misleading "$0.01".
function fmtCost(n: number) {
  if (n <= 0) return '$0.00';
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}
function fmtHm(s: number) {
  const m = Math.floor(s / 60);
  return `${m}m`;
}

export function N2Sidebar({ view }: { view: AppState }) {
  const slice = useStore((s) => s[s.active]);
  const file = slice.file;
  const error = slice.error;
  const mapperSelected = slice.mapperSelectedColumn;
  const [rowLimit, setRowLimit] = useState<number>(0);

  // Partial-cleaning state: any rows have a non-pending status, but not
  // all of them. The CTA relabels to "Continue cleaning" and its cost
  // estimate covers only the rows that are still pending.
  const totalRows = file?.rows ?? 0;
  const cleanedCount = slice.rows.filter((r) => r.status !== 'pending').length;
  const isPartial = cleanedCount > 0 && cleanedCount < totalRows;
  const inFlight = slice.rowsInFlight.length > 0;
  const pendingCount = isPartial
    ? Math.max(0, totalRows - cleanedCount)
    : totalRows;

  const effectiveRows = rowLimit > 0 && file
    ? Math.min(rowLimit, pendingCount)
    : pendingCount;
  const estSub = file
    ? `${effectiveRows.toLocaleString('en-US')} rows · ~${fmtCost(estimateRunCost(effectiveRows))} · ~${fmtHm(Math.max(60, effectiveRows / 14))}`
    : 'load a csv to begin';
  const ctaLabel = isPartial ? 'Continue cleaning' : 'Begin cleaning';

  return (
    <aside
      style={{
        padding: '22px 22px',
        borderRight: `1px solid ${N2.hair}`,
        display: 'flex',
        flexDirection: 'column',
        gap: 18,
        overflow: 'auto',
        background: 'linear-gradient(180deg, rgba(14,15,23,0.3), transparent 40%)',
      }}
    >
      <N2SidebarHeadline view={view} />

      {view === 'awaiting_column' && (
        <N2CtaPrimary
          label="Confirm column"
          sub={
            mapperSelected
              ? `cleaning column "${mapperSelected}"`
              : 'pick a column on the right to continue'
          }
          disabled={!mapperSelected}
          onClick={mapperSelected ? () => void confirmColumn(mapperSelected) : undefined}
        />
      )}

      {view === 'indexed' && (
        <>
          <N2CtaPrimary
            label={ctaLabel}
            sub={estSub}
            onClick={() =>
              beginCleaningWithCostCheck(
                file?.column ?? '',
                rowLimit > 0 ? rowLimit : undefined,
              )
            }
          />
          <N2TryDryRunCta
            onClick={() => runDryRun(file?.column ?? '', 25)}
          />
        </>
      )}

      {view === 'indexed' && file && (
        <RowLimitInput value={rowLimit} onChange={setRowLimit} max={file.rows} />
      )}

      {view !== 'empty' && <N2FileCard />}
      {view === 'empty' && <N2EmptyDrop />}

      {view === 'empty' && (
        <N2CtaPrimary label="Begin cleaning" sub="load a csv to begin" disabled />
      )}
      {view === 'error' && (
        <N2CtaPrimary
          label={`Resume from ${(error?.lastRow ?? 0).toLocaleString('en-US')}`}
          sub={`retry_after=${error?.retryAfter ?? 12}s · partial results kept`}
          variant="rose"
          onClick={() => startRun(file?.column ?? '')}
        />
      )}
      {view === 'running' && (
        <button
          onClick={() => cancelRun()}
          style={{
            marginTop: -6,
            padding: '8px 14px',
            background: 'transparent',
            border: `1px solid ${N2.hair2}`,
            color: N2.text2,
            fontFamily: fMono,
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: 'uppercase',
            borderRadius: 2,
            cursor: 'pointer',
          }}
        >
          Cancel
        </button>
      )}

      {(view === 'running' || view === 'done' || inFlight || isPartial) && (
        <N2Progress view={view} />
      )}
      {(view === 'running' || view === 'done' || inFlight || isPartial) && (
        <N2Telemetry view={view} />
      )}
    </aside>
  );
}

function N2TryDryRunCta({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        marginTop: -6,
        padding: '10px 14px',
        background: 'transparent',
        border: `1px solid ${N2.accentDeep}`,
        color: N2.accent,
        fontFamily: fMono,
        fontSize: 10.5,
        letterSpacing: 1.5,
        textTransform: 'uppercase',
        fontWeight: 700,
        borderRadius: 2,
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        transition: 'background .12s ease, border-color .12s ease',
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = 'rgba(199,179,255,0.08)';
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
      }}
    >
      <span>↯ Try on first 25</span>
      <span style={{ color: N2.text3, fontSize: 9.5, letterSpacing: 1.2 }}>
        ~{fmtCost(estimateRunCost(25))}
      </span>
    </button>
  );
}

function RowLimitInput({
  value,
  onChange,
  max,
}: {
  value: number;
  onChange: (n: number) => void;
  max: number;
}) {
  return (
    <div>
      <div
        style={{
          fontFamily: fMono,
          fontSize: 9,
          color: N2.text3,
          letterSpacing: 1.8,
          textTransform: 'uppercase',
          marginBottom: 6,
        }}
      >
        Rows to clean
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          placeholder="all"
          value={value === 0 ? '' : value}
          onChange={(e) => {
            const raw = e.target.value.replace(/[^0-9]/g, '');
            if (raw === '') {
              onChange(0);
              return;
            }
            const n = Math.max(0, Math.min(max, parseInt(raw, 10) || 0));
            onChange(n);
          }}
          style={{
            flex: 1,
            background: 'rgba(255,253,247,0.03)',
            border: `1px solid ${N2.hair2}`,
            borderRadius: 2,
            color: N2.text,
            fontFamily: fMono,
            fontSize: 12,
            padding: '6px 8px',
            outline: 'none',
            letterSpacing: 0.3,
          }}
        />
        <button
          type="button"
          onClick={() => onChange(0)}
          title="Clean every row"
          style={{
            background: value === 0 ? 'rgba(199,179,255,0.14)' : 'transparent',
            border: `1px solid ${value === 0 ? N2.accent : N2.hair2}`,
            color: value === 0 ? N2.accent : N2.text3,
            boxShadow: value === 0
              ? '0 0 0 1px rgba(199,179,255,0.25), 0 0 10px rgba(199,179,255,0.18)'
              : 'none',
            fontFamily: fMono,
            fontSize: 9,
            letterSpacing: 1.4,
            textTransform: 'uppercase',
            fontWeight: value === 0 ? 700 : 500,
            padding: '6px 10px',
            borderRadius: 2,
            cursor: 'pointer',
            transition: 'background .15s ease, border-color .15s ease, box-shadow .15s ease',
          }}
        >
          All
        </button>
      </div>
      <div
        style={{
          fontFamily: fMono,
          fontSize: 9,
          color: N2.text3,
          letterSpacing: 1.2,
          textTransform: 'uppercase',
          marginTop: 4,
        }}
      >
        {value === 0
          ? `all ${max.toLocaleString('en-US')} rows`
          : `first ${value.toLocaleString('en-US')} of ${max.toLocaleString('en-US')}`}
      </div>
    </div>
  );
}
