import { useEffect, useState } from 'react';
import { N2, fSerif, fBody, fMono } from '../../theme';
import type { MapperColumn } from '../../types';
import { listColumnsWithSamples, confirmColumn } from '../../lib/actions';
import { useStore } from '../../store';

// Column-picker workspace — shown after a file is uploaded and before the
// run starts. Renders one card per column with a short type hint and 5
// sample values. The suggested column gets a sage "Grok's guess" badge.
export function N2ColumnMapper() {
  const kind = useStore((s) => s.active);
  const selected = useStore((s) => s[s.active].mapperSelectedColumn) ?? null;
  const setSelected = useStore((s) => s.setMapperSelectedColumn);
  const [columns, setColumns] = useState<MapperColumn[] | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void listColumnsWithSamples(kind).then((cols) => {
      if (cancelled) return;
      setColumns(cols);
      // Pre-pick suggested if user hasn't manually picked yet.
      const already = useStore.getState()[kind].mapperSelectedColumn;
      if (!already) {
        const sug = cols.find((c) => c.suggested);
        if (sug) setSelected(kind, sug.id);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [kind, setSelected]);

  const onConfirm = async () => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      await confirmColumn(selected, kind);
    } finally {
      setBusy(false);
    }
  };

  const selectedCol = columns?.find((c) => c.id === selected) ?? null;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        padding: '38px 48px 28px',
        overflow: 'auto',
        height: '100%',
      }}
    >
      <div style={{ marginBottom: 26, maxWidth: 720 }}>
        <div
          style={{
            fontFamily: fSerif,
            fontSize: 34,
            lineHeight: 1.15,
            letterSpacing: -0.8,
            color: N2.text,
            fontWeight: 500,
            fontVariationSettings: '"opsz" 80, "SOFT" 40',
          }}
        >
          {kind === 'company'
            ? 'Which column holds the company name?'
            : 'Which column holds the first name?'}
        </div>
        <div
          style={{
            color: N2.text2,
            fontSize: 14,
            lineHeight: 1.55,
            marginTop: 10,
            maxWidth: 620,
          }}
        >
          We peeked at the first few rows of each column and flagged one. Pick it if it
          looks right, or choose another.
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 14,
          marginBottom: 20,
        }}
      >
        {columns === null
          ? Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)
          : columns.map((c) => (
              <ColCard
                key={c.id}
                col={c}
                selected={selected === c.id}
                onClick={() => setSelected(kind, c.id)}
              />
            ))}
      </div>

      <div
        style={{
          marginTop: 'auto',
          paddingTop: 18,
          borderTop: `1px solid ${N2.hair}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 14,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            fontFamily: fBody,
            fontSize: 13,
            color: N2.text2,
          }}
        >
          {selectedCol ? (
            <>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '3px 8px',
                  border: `1px solid ${N2.sage}`,
                  background: N2.sageDim,
                  borderRadius: 2,
                  fontFamily: fMono,
                  fontSize: 9.5,
                  letterSpacing: 1.2,
                  textTransform: 'uppercase',
                  color: N2.sage,
                }}
              >
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: 1,
                    background: N2.sage,
                    boxShadow: '0 0 6px rgba(111,227,168,.55)',
                  }}
                />
                selected
              </span>
              <span style={{ color: N2.text3 }}>
                Cleaning{' '}
                <b
                  style={{
                    color: N2.text,
                    fontWeight: 600,
                    fontFamily: fMono,
                    fontSize: 11.5,
                    letterSpacing: 0.3,
                  }}
                >
                  {selectedCol.name}
                </b>
                .
              </span>
            </>
          ) : (
            <span style={{ color: N2.text3 }}>Pick a column to continue.</span>
          )}
        </div>
        <button
          type="button"
          disabled={!selected || busy}
          onClick={onConfirm}
          style={{
            background:
              selected && !busy
                ? `linear-gradient(180deg, ${N2.accent}, ${N2.accentSoft})`
                : 'transparent',
            color: selected && !busy ? '#1a152e' : N2.text4,
            border: selected && !busy ? 'none' : `1px solid ${N2.hair2}`,
            padding: '11px 22px',
            borderRadius: 2,
            fontFamily: fMono,
            fontSize: 11,
            letterSpacing: 1.6,
            textTransform: 'uppercase',
            fontWeight: 700,
            cursor: selected && !busy ? 'pointer' : 'not-allowed',
            boxShadow: selected && !busy ? `0 0 18px ${N2.accentGlow}` : 'none',
          }}
        >
          {busy ? 'Loading…' : 'Confirm column'}
        </button>
      </div>
    </div>
  );
}

function ColCard({
  col,
  selected,
  onClick,
}: {
  col: MapperColumn;
  selected: boolean;
  onClick: () => void;
}) {
  const isSuggested = col.suggested && !selected;
  const border = selected
    ? N2.accent
    : isSuggested
      ? 'rgba(111,227,168,0.55)'
      : N2.hair;
  const shadow = selected
    ? `0 0 0 1px ${N2.accent}, 0 0 22px ${N2.accentGlow}`
    : isSuggested
      ? '0 0 0 1px rgba(111,227,168,0.2), 0 0 16px rgba(111,227,168,0.12)'
      : 'none';
  const background = selected ? 'rgba(199,179,255,0.07)' : N2.panel;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
      style={{
        background,
        border: `1px solid ${border}`,
        borderRadius: 3,
        padding: '14px 14px 10px',
        cursor: 'pointer',
        transition: 'all .14s ease',
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        minHeight: 190,
        boxShadow: shadow,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 8,
        }}
      >
        <span
          style={{
            fontFamily: fMono,
            fontSize: 11.5,
            color: N2.text,
            letterSpacing: 0.3,
            fontWeight: 600,
            overflowWrap: 'anywhere',
          }}
        >
          {col.name}
        </span>
        {isSuggested && (
          <span
            style={{
              fontFamily: fMono,
              fontSize: 9,
              color: N2.sage,
              letterSpacing: 1.2,
              textTransform: 'uppercase',
              fontWeight: 600,
              padding: '2px 6px',
              border: '1px solid rgba(111,227,168,0.5)',
              borderRadius: 2,
              flexShrink: 0,
              whiteSpace: 'nowrap',
            }}
          >
            best guess
          </span>
        )}
      </div>
      <div
        style={{
          fontFamily: fMono,
          fontSize: 9.5,
          color: N2.text3,
          letterSpacing: 0.8,
          textTransform: 'uppercase',
        }}
      >
        {col.meta}
      </div>
      <div
        style={{
          borderTop: `1px solid ${N2.hair}`,
          paddingTop: 8,
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          marginTop: 'auto',
        }}
      >
        {col.preview.length === 0 ? (
          <div
            style={{
              fontFamily: fMono,
              fontSize: 11,
              color: N2.text4,
              fontStyle: 'italic',
            }}
          >
            (empty)
          </div>
        ) : (
          col.preview.map((p, i) => (
            <div
              key={i}
              style={{
                fontFamily: fMono,
                fontSize: 11,
                color: selected ? N2.text : N2.text2,
                letterSpacing: 0.1,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {p}
            </div>
          ))
        )}
      </div>
      {selected && (
        <span
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            width: 16,
            height: 16,
            borderRadius: '50%',
            background: N2.accent,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: `0 0 10px ${N2.accentGlow}`,
            color: '#1a152e',
            fontSize: 10,
            lineHeight: 1,
            fontWeight: 700,
          }}
        >
          ✓
        </span>
      )}
    </div>
  );
}

function SkeletonCard() {
  return (
    <div
      style={{
        background: N2.panel,
        border: `1px solid ${N2.hair}`,
        borderRadius: 3,
        padding: '14px 14px 10px',
        minHeight: 190,
        opacity: 0.5,
      }}
    />
  );
}
