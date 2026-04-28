import { N2, fMono } from '../../theme';
import type { AppState } from '../../types';
import { useStore } from '../../store';
import { fmtCost, fmtInt } from '../../utils/format';

interface Props {
  view: AppState;
}

export function N2Footer({ view }: Props) {
  const slice = useStore((s) => s[s.active]);
  const t = slice.telemetry;
  const progress = slice.progress;
  const file = slice.file;

  const empty = view === 'empty';
  const totalN = file?.rows ?? 0;
  const cells: [string, string, string?][] = [
    ['total', empty ? '—' : fmtInt(totalN), undefined],
    ['grok', empty ? '—' : fmtInt(progress.processed), undefined],
    ['null', empty ? '—' : fmtInt(t.nullCount), N2.rose],
    ['cost', empty ? '—' : fmtCost(t.costUsd), N2.accent],
  ];
  return (
    <footer
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 18,
        padding: '0 26px',
        borderTop: `1px solid ${N2.hair}`,
        background: 'rgba(14,15,23,0.55)',
        fontFamily: fMono,
        fontSize: 9.5,
        color: N2.text3,
        letterSpacing: 1.3,
      }}
    >
      {cells.map(([l, v, c]) => (
        <span key={l}>
          <span style={{ textTransform: 'uppercase' }}>{l}</span>
          <span style={{ color: c || N2.text, marginLeft: 6 }}>{v}</span>
        </span>
      ))}
    </footer>
  );
}
