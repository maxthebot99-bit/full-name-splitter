import type { ReactNode } from 'react';
import { N2, fSerif } from '../../../theme';
import type { AppState } from '../../../types';
import { useStore, processedRowCount } from '../../../store';
import { N2Thinking, PHRASES_FULLNAME } from '../../atoms/N2Thinking';

function fmtInt(n: number): string {
  return n.toLocaleString('en-US');
}

function contentFor(
  view: AppState,
  processed: number,
  total: number,
  lastRow: number,
  partialCleaned: number,
): ReactNode {
  switch (view) {
    case 'empty':
      return (
        <>
          A quiet place to <em style={{ color: N2.accent }}>split</em> full names.
        </>
      );
    case 'awaiting_column':
      return (
        <>
          {fmtInt(total)} rows — <em style={{ color: N2.accent }}>pick the full-name column</em>.
        </>
      );
    case 'indexed':
      if (partialCleaned > 0 && partialCleaned < total) {
        return (
          <>
            {fmtInt(partialCleaned)} of {fmtInt(total)},{' '}
            <em style={{ color: N2.accent }}>partially split</em>.
          </>
        );
      }
      return (
        <>
          {fmtInt(total)} rows, <em style={{ color: N2.accent }}>loaded</em>.
        </>
      );
    case 'running':
      return (
        <>
          Splitting name <em style={{ color: N2.accent }}>{fmtInt(processed)}</em> of {fmtInt(total)}.
        </>
      );
    case 'done':
      return (
        <>
          All {fmtInt(total)} names, <em style={{ color: N2.sage }}>split</em>.
        </>
      );
    case 'cancelled':
      return (
        <>
          {fmtInt(partialCleaned)} of {fmtInt(total)} split,{' '}
          <em style={{ color: N2.ochre }}>paused</em>.
        </>
      );
    case 'error':
      return (
        <>
          A pause at <em style={{ color: N2.rose }}>row {fmtInt(lastRow)}</em>.
        </>
      );
  }
}

export function N2SidebarHeadline({ view }: { view: AppState }) {
  const slice = useStore((s) => s.fullname);
  const total = slice.file?.rows ?? 0;
  const partialCleaned = processedRowCount(slice);
  const inFlight = slice.rowsInFlight;

  // ▶ rerun in flight: replace the static headline with a live "thinking"
  // strip naming the row(s) being processed.
  if (inFlight.length > 0) {
    const detail =
      inFlight.length === 1
        ? `row ${String(inFlight[0]).padStart(3, '0')}`
        : `${inFlight.length} rows`;
    return (
      <div style={{ minHeight: 32 }}>
        <N2Thinking phrases={PHRASES_FULLNAME} detail={detail} size="md" />
      </div>
    );
  }

  return (
    <div
      style={{
        fontFamily: fSerif,
        fontSize: 24,
        lineHeight: 1.2,
        letterSpacing: -0.5,
        color: N2.text,
        fontWeight: 400,
        fontVariationSettings: '"opsz" 40, "SOFT" 30',
      }}
    >
      {contentFor(
        view,
        slice.progress.processed,
        total,
        slice.error?.lastRow ?? 0,
        partialCleaned,
      )}
    </div>
  );
}
