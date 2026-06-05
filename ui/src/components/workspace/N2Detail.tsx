import { useEffect, useState } from 'react';
import { N2, fSerif, fMono } from '../../theme';
import { N2Label } from '../atoms/N2Label';
import { useStore } from '../../store';
import { overrideRow } from '../../lib/actions';

// Selected-row detail panel. Splitter shape: TWO output cells (First Name
// / Last Name), each independently editable from this form. Pressing Save
// commits both via the override endpoint; clearing both fields restores
// Grok's verdict (or pending state pre-run).
export function N2Detail() {
  const slice = useStore((s) => s.fullname);
  const filtered = slice.rows.filter(
    (r) => slice.filter === 'all' || r.status === slice.filter,
  );
  const row =
    slice.selectedRowIdx !== undefined && filtered[slice.selectedRowIdx]
      ? filtered[slice.selectedRowIdx]
      : filtered[filtered.length - 1];

  const [first, setFirst] = useState<string>(row?.first ?? '');
  const [last, setLast] = useState<string>(row?.last ?? '');

  // Re-sync the inputs when the selected row changes — otherwise the form
  // would show the old row's values after the user clicks a new row.
  useEffect(() => {
    setFirst(row?.first ?? '');
    setLast(row?.last ?? '');
  }, [row?.n, row?.first, row?.last]);

  if (!row) return null;

  const dirty = first !== (row.first ?? '') || last !== (row.last ?? '');
  const save = () => {
    if (!dirty) return;
    const f = first.trim();
    const l = last.trim();
    void overrideRow(row.n, f.length ? f : null, l.length ? l : null);
  };
  const reset = () => {
    setFirst(row.first ?? '');
    setLast(row.last ?? '');
  };

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
          fontSize: 16,
          color: N2.text,
          letterSpacing: -0.3,
          lineHeight: 1.45,
          fontWeight: 400,
          fontVariationSettings: '"opsz" 24, "SOFT" 50',
          marginBottom: 12,
        }}
      >
        <span style={{ color: N2.text3, fontFamily: fMono, fontSize: 13 }}>"{row.orig}"</span>
        {' — '}
        {row.status === 'null' || (row.first == null && row.last == null) ? (
          <em style={{ color: N2.rose }}>null</em>
        ) : (
          <>
            split as{' '}
            <em style={{ color: N2.accent }}>
              {(row.first ?? '∅') + ' / ' + (row.last ?? '∅')}
            </em>
          </>
        )}
        . {row.reason}
      </div>

      {/* Two-input override form. Empty trimmed input = null cell; both
          empty + Save = clear the override entirely (Grok's verdict, if
          any, returns to view). */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr auto',
          gap: 10,
          alignItems: 'end',
        }}
      >
        <div>
          <div
            style={{
              fontFamily: fMono,
              fontSize: 9,
              color: N2.text3,
              letterSpacing: 1.8,
              textTransform: 'uppercase',
              marginBottom: 4,
            }}
          >
            First Name
          </div>
          <input
            value={first}
            onChange={(e) => setFirst(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') save();
            }}
            placeholder="(empty)"
            style={inputStyle()}
          />
        </div>
        <div>
          <div
            style={{
              fontFamily: fMono,
              fontSize: 9,
              color: N2.text3,
              letterSpacing: 1.8,
              textTransform: 'uppercase',
              marginBottom: 4,
            }}
          >
            Last Name
          </div>
          <input
            value={last}
            onChange={(e) => setLast(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') save();
            }}
            placeholder="(empty)"
            style={inputStyle()}
          />
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            type="button"
            onClick={reset}
            disabled={!dirty}
            style={btnGhost(!dirty)}
          >
            Reset
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!dirty}
            style={btnPrimary(!dirty)}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function inputStyle(): React.CSSProperties {
  return {
    width: '100%',
    background: 'rgba(255,253,247,0.04)',
    border: `1px solid ${N2.hair2}`,
    borderRadius: 2,
    color: N2.text,
    fontFamily: fSerif,
    fontSize: 16,
    padding: '7px 10px',
    outline: 'none',
    letterSpacing: -0.2,
  };
}

function btnGhost(disabled: boolean): React.CSSProperties {
  return {
    background: 'transparent',
    color: disabled ? N2.text4 : N2.text2,
    border: `1px solid ${N2.hair2}`,
    padding: '7px 12px',
    borderRadius: 2,
    fontFamily: fMono,
    fontSize: 10,
    letterSpacing: 1.4,
    textTransform: 'uppercase',
    fontWeight: 600,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.55 : 1,
  };
}

function btnPrimary(disabled: boolean): React.CSSProperties {
  return {
    background: disabled
      ? 'transparent'
      : `linear-gradient(180deg, ${N2.accent}, ${N2.accentSoft})`,
    color: disabled ? N2.text4 : '#0a0612',
    border: disabled ? `1px solid ${N2.hair2}` : 'none',
    padding: '7px 14px',
    borderRadius: 2,
    fontFamily: fMono,
    fontSize: 10,
    letterSpacing: 1.4,
    textTransform: 'uppercase',
    fontWeight: 700,
    cursor: disabled ? 'not-allowed' : 'pointer',
    boxShadow: disabled ? 'none' : `0 0 12px ${N2.accentGlow}`,
  };
}
