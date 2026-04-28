import type { ReactNode } from 'react';
import { N2, fSerif } from '../../../theme';
import type { AppState, Kind } from '../../../types';
import { useStore } from '../../../store';
import {
  N2Thinking,
  PHRASES_COMPANY,
  PHRASES_NAME,
} from '../../atoms/N2Thinking';

function fmtInt(n: number): string {
  return n.toLocaleString('en-US');
}

function noun(kind: Kind, plural = true): string {
  if (kind === 'company') return plural ? 'company names' : 'company name';
  return plural ? 'first names' : 'first name';
}

function contentFor(
  view: AppState,
  kind: Kind,
  processed: number,
  total: number,
  lastRow: number,
  partialCleaned: number,
): ReactNode {
  switch (view) {
    case 'empty':
      return (
        <>
          A quiet place to <em style={{ color: N2.accent }}>tidy</em> messy {noun(kind)}.
        </>
      );
    case 'awaiting_column':
      return (
        <>
          {fmtInt(total)} rows — <em style={{ color: N2.accent }}>pick the {kind === 'company' ? 'company' : 'first-name'} column</em>.
        </>
      );
    case 'indexed':
      if (partialCleaned > 0 && partialCleaned < total) {
        return (
          <>
            {fmtInt(partialCleaned)} of {fmtInt(total)},{' '}
            <em style={{ color: N2.accent }}>partially cleaned</em>.
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
          Reading {kind === 'company' ? 'name' : 'name'} <em style={{ color: N2.accent }}>{fmtInt(processed)}</em> of {fmtInt(total)}.
        </>
      );
    case 'done':
      return (
        <>
          All {fmtInt(total)} {noun(kind)}, <em style={{ color: N2.sage }}>reconciled</em>.
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
  const slice = useStore((s) => s[s.active]);
  const total = slice.file?.rows ?? 0;
  const partialCleaned = slice.rows.filter((r) => r.status !== 'pending').length;
  const inFlight = slice.rowsInFlight;
  const phrases = slice.kind === 'company' ? PHRASES_COMPANY : PHRASES_NAME;

  // ▶ rerun in flight: replace the static headline with a live "thinking"
  // strip naming the row(s) being processed. If the user has multiple
  // reruns going, just show the count.
  if (inFlight.length > 0) {
    const detail =
      inFlight.length === 1
        ? `row ${String(inFlight[0]).padStart(3, '0')}`
        : `${inFlight.length} rows`;
    return (
      <div style={{ minHeight: 32 }}>
        <N2Thinking phrases={phrases} detail={detail} size="md" />
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
        slice.kind,
        slice.progress.processed,
        total,
        slice.error?.lastRow ?? 0,
        partialCleaned,
      )}
    </div>
  );
}
