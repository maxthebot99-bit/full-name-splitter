import type { ReactNode } from 'react';
import { N2, fSerif } from '../../../theme';
import type { AppState, Kind } from '../../../types';
import { useStore } from '../../../store';

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
      )}
    </div>
  );
}
