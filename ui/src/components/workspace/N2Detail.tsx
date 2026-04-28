import { N2, fSerif, fMono } from '../../theme';
import { N2Label } from '../atoms/N2Label';
import { useStore } from '../../store';

export function N2Detail() {
  const slice = useStore((s) => s[s.active]);
  const filtered = slice.rows.filter(
    (r) => slice.filter === 'all' || r.status === slice.filter,
  );
  const row =
    slice.selectedRowIdx !== undefined && filtered[slice.selectedRowIdx]
      ? filtered[slice.selectedRowIdx]
      : filtered[filtered.length - 1];
  if (!row) return null;

  return (
    <div
      style={{
        borderTop: `1px solid ${N2.hair}`,
        padding: '16px 28px 18px',
        background: 'rgba(20,22,33,0.45)',
        backdropFilter: 'blur(20px)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 10 }}>
        <N2Label mark>Row {String(row.n).padStart(3, '0')} · Grok's note</N2Label>
      </div>
      <div
        style={{
          fontFamily: fSerif,
          fontSize: 18,
          color: N2.text,
          letterSpacing: -0.3,
          lineHeight: 1.45,
          fontWeight: 400,
          fontVariationSettings: '"opsz" 24, "SOFT" 50',
        }}
      >
        <span style={{ color: N2.text3, fontFamily: fMono, fontSize: 14 }}>"{row.orig}"</span>
        {' — '}
        {row.clean === null ? (
          <em style={{ color: N2.rose }}>null</em>
        ) : (
          <>
            read as <em style={{ color: N2.accent }}>{row.clean}</em>
          </>
        )}
        . {row.reason}
      </div>
    </div>
  );
}
