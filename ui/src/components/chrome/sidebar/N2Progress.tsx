import { N2, fSerif, fMono } from '../../../theme';
import { N2Label } from '../../atoms/N2Label';
import { N2Number } from '../../atoms/N2Number';
import type { AppState } from '../../../types';
import { useStore } from '../../../store';

function fmtHms(s: number): string {
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}m ${String(r).padStart(2, '0')}s`;
}

export function N2Progress({ view }: { view: AppState }) {
  const { processed, total, etaSeconds, elapsedSeconds } = useStore(
    (s) => s[s.active].progress,
  );
  const pct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  return (
    <div style={{ paddingTop: 14, borderTop: `1px solid ${N2.hair}` }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 8,
        }}
      >
        <N2Label mark accent={view === 'done' ? N2.sage : N2.accent}>
          {view === 'done' ? 'Complete' : 'Progress'}
        </N2Label>
        <span style={{ fontFamily: fMono, fontSize: 10, color: N2.text2, letterSpacing: 0.3 }}>
          {view === 'running' ? (
            <>
              ETA <span style={{ color: N2.text }}>{fmtHms(etaSeconds)}</span>
            </>
          ) : (
            <>
              took <span style={{ color: N2.text }}>{fmtHms(elapsedSeconds)}</span>
            </>
          )}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 10 }}>
        <N2Number
          value={pct}
          size={44}
          color={view === 'done' ? N2.sage : N2.accent}
          animate={true}
          format={(v) => Math.round(v as number).toString()}
        />
        <span style={{ fontFamily: fSerif, fontSize: 22, color: N2.text3, fontStyle: 'italic' }}>
          %
        </span>
      </div>
      <div style={{ height: 2, background: N2.hair, position: 'relative', overflow: 'hidden' }}>
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background:
              view === 'done'
                ? N2.sage
                : `linear-gradient(90deg, ${N2.accentDeep}, ${N2.accent})`,
            boxShadow: view === 'running' ? `0 0 10px ${N2.accentGlow}` : 'none',
            transition: 'width 1.2s cubic-bezier(0.4,0,0.2,1)',
            position: 'relative',
          }}
        >
          {view === 'running' && (
            <span
              style={{
                position: 'absolute',
                inset: 0,
                background:
                  'linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent)',
                animation: 'obsShimmer 2s infinite',
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
