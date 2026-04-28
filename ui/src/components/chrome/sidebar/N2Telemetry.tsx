import { N2, fSerif, fMono } from '../../../theme';
import { N2Label } from '../../atoms/N2Label';
import { N2Number } from '../../atoms/N2Number';
import { N2Spark } from '../../atoms/N2Spark';
import { useLiveTelemetry } from '../../../hooks';
import type { AppState } from '../../../types';
import { useStore } from '../../../store';
import { SPARKLINE } from '../../../utils/fixtures';

function fmtK(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return Math.round(n).toString();
}

function fmtInt(n: number): string {
  return Math.round(n).toLocaleString('en-US');
}

export function N2Telemetry({ view }: { view: AppState }) {
  const slice = useStore((s) => s[s.active]);
  const t = slice.telemetry;
  const history = t.rowsPerSecondHistory.length >= 10 ? t.rowsPerSecondHistory : SPARKLINE;

  // Smooth tokens / cost between batch frames using rowsPerSecond × per-row
  // averages from the snapshot. Snaps to truth when the next telemetry
  // event lands.
  const total = slice.file?.rows ?? 0;
  const processedSnap = slice.rows.filter((r) => r.status !== 'pending').length;
  const live = useLiveTelemetry({
    processed: processedSnap,
    total,
    rowsPerSecond: t.rowsPerSecond,
    tokensIn: t.tokensIn,
    tokensOut: t.tokensOut,
    costUsd: t.costUsd,
    lastTelemetryAt: slice.lastTelemetryAt,
    active: view === 'running',
  });

  const cells: [string, string, string][] = [
    ['Tokens in', fmtK(live.tokensIn), N2.text],
    ['Tokens out', fmtK(live.tokensOut), N2.text],
    ['Nulls', fmtInt(t.nullCount), N2.rose],
    ['API calls', fmtInt(t.rulesFired), N2.text],
    ['Cost', `$${live.costUsd.toFixed(2)}`, N2.accent],
  ];

  return (
    <>
      <div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            marginBottom: 4,
          }}
        >
          <N2Label>Throughput</N2Label>
          <span>
            <N2Number
              value={t.rowsPerSecond || 0}
              size={18}
              color={N2.text}
              format={(v) => (v as number).toFixed(1)}
            />
            <span
              style={{
                fontFamily: fMono,
                fontSize: 9.5,
                color: N2.text3,
                marginLeft: 4,
                letterSpacing: 1,
                textTransform: 'uppercase',
              }}
            >
              rows/s
            </span>
          </span>
        </div>
        <N2Spark values={history} w={292} h={40} color={N2.accent} live={view === 'running'} />
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          rowGap: 14,
          columnGap: 18,
          paddingTop: 4,
        }}
      >
        {cells.map(([l, v, c]) => (
          <div key={l} style={{ borderTop: `1px solid ${N2.hair}`, paddingTop: 8 }}>
            <div
              style={{
                fontFamily: fMono,
                fontSize: 9,
                color: N2.text3,
                letterSpacing: 1.8,
                textTransform: 'uppercase',
              }}
            >
              {l}
            </div>
            <div
              style={{
                fontFamily: fSerif,
                fontSize: 30,
                color: c,
                fontWeight: 400,
                marginTop: 4,
                letterSpacing: -1,
                lineHeight: 1,
                fontVariationSettings: '"opsz" 72',
                fontFeatureSettings: '"lnum", "tnum"',
              }}
            >
              {v}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
