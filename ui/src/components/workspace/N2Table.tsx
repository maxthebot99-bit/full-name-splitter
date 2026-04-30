import { useState, type CSSProperties } from 'react';
import { N2, fSerif, fMono } from '../../theme';
import { N2Chip } from '../atoms/N2Chip';
import type { AppState, Kind, Row } from '../../types';
import { useStore } from '../../store';
import { overrideRow, rerunRow } from '../../lib/actions';

const td: CSSProperties = {
  padding: '11px 20px',
  borderBottom: `1px solid ${N2.hair}`,
  verticalAlign: 'middle',
};

export function N2Table({ view }: { view: AppState }) {
  const slice = useStore((s) => s[s.active]);
  const selectRow = useStore((s) => s.selectRow);
  const isStreaming = view === 'running';
  // The address tab renders via a dedicated multi-field table component.
  // For now this single-column table is a no-op when active === 'address'.
  if (slice.kind === 'address') {
    return null;
  }
  const sliceKind = slice.kind as Exclude<Kind, 'address'>;
  const filtered = slice.rows.filter(
    (r) => slice.filter === 'all' || r.status === slice.filter,
  );

  return (
    <table
      style={{
        width: '100%',
        borderCollapse: 'separate',
        borderSpacing: 0,
        fontSize: 12.5,
      }}
    >
      <style>{`
        .n2-row:hover > td { background: rgba(199,179,255,0.035); }
        .n2-row.n2-row-sel > td { background: ${N2.accent}0c; }
        .n2-orig-cell:hover > .n2-orig-text { color: ${N2.text}; }
      `}</style>
      <thead>
        <tr>
          {[
            ['№', 40],
            ['Original', null],
            ['Cleaned', null],
            ['Status', 140],
            ['Grok’s rationale', null],
          ].map(([h, w], i) => (
            <th
              key={i}
              style={{
                textAlign: 'left',
                padding: '10px 20px 8px',
                fontSize: 9,
                fontWeight: 500,
                color: N2.text3,
                letterSpacing: 1.8,
                textTransform: 'uppercase',
                borderBottom: `1px solid ${N2.hair}`,
                fontFamily: fMono,
                position: 'sticky',
                top: 0,
                background: N2.bg,
                width: (w as number) || undefined,
                zIndex: 1,
              }}
            >
              {h as string}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {filtered.map((r, i) => {
          const isSel = slice.selectedRowIdx === i;
          const justArrived = isStreaming && i === filtered.length - 1;
          return (
            <TableRow
              key={r.n}
              row={r}
              kind={sliceKind}
              selected={isSel}
              justArrived={justArrived}
              isStreaming={isStreaming}
              onSelect={() => selectRow(slice.kind, i)}
            />
          );
        })}
        {isStreaming && slice.progress.processed < slice.progress.total && (
          <tr>
            <td colSpan={5} style={{ padding: '14px 20px', color: N2.text3 }}>
              <span
                style={{
                  fontFamily: fMono,
                  fontSize: 10,
                  letterSpacing: 1.5,
                  textTransform: 'uppercase',
                  display: 'inline-flex',
                  gap: 6,
                  alignItems: 'center',
                }}
              >
                <span style={{ display: 'inline-flex', gap: 3 }}>
                  <span
                    style={{
                      width: 3,
                      height: 3,
                      background: N2.accent,
                      borderRadius: 3,
                      animation: 'n2Dot 1.2s ease-in-out infinite',
                    }}
                  />
                  <span
                    style={{
                      width: 3,
                      height: 3,
                      background: N2.accent,
                      borderRadius: 3,
                      animation: 'n2Dot 1.2s ease-in-out 0.15s infinite',
                    }}
                  />
                  <span
                    style={{
                      width: 3,
                      height: 3,
                      background: N2.accent,
                      borderRadius: 3,
                      animation: 'n2Dot 1.2s ease-in-out 0.3s infinite',
                    }}
                  />
                </span>
                reading row {String(slice.progress.processed + 1).padStart(3, '0')}…
              </span>
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

interface RowProps {
  row: Row;
  // Address kind has its own table component; this one only handles
  // single-string-output rows from the company/name pipelines.
  kind: Exclude<Kind, 'address'>;
  selected: boolean;
  justArrived: boolean;
  isStreaming: boolean;
  onSelect: () => void;
}

function TableRow({ row, kind, selected, justArrived, isStreaming, onSelect }: RowProps) {
  const r = row;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>(r.clean ?? '');

  const startEdit = () => {
    if (isStreaming) return;
    setDraft(r.clean ?? '');
    setEditing(true);
  };
  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    const cleanedNext = next.length === 0 ? null : next;
    if (cleanedNext === r.clean) return; // no change
    void overrideRow(r.n, cleanedNext, kind);
  };
  const cancel = () => {
    setEditing(false);
    setDraft(r.clean ?? '');
  };

  return (
    <tr
      className={`n2-row${selected ? ' n2-row-sel' : ''}`}
      style={{
        animation: justArrived ? 'n2RowIn 0.55s cubic-bezier(0.4,0,0.2,1)' : 'none',
        borderLeft: selected ? `2px solid ${N2.accent}` : 'none',
      }}
    >
      <td style={td}>
        <span style={{ color: N2.text4, fontVariantNumeric: 'tabular-nums' }}>
          {String(r.n).padStart(3, '0')}
        </span>
      </td>
      <td
        className="n2-orig-cell"
        onClick={onSelect}
        style={{ ...td, cursor: 'pointer' }}
        title="Click to see Grok's note for this row"
      >
        <span
          className="n2-orig-text"
          style={{
            fontFamily: fMono,
            fontSize: 11.5,
            color: N2.text2,
            letterSpacing: 0.1,
            transition: 'color .12s ease',
          }}
        >
          {r.orig}
        </span>
      </td>
      <td
        style={{
          ...td,
          cursor: isStreaming || editing ? 'default' : 'pointer',
        }}
        onDoubleClick={startEdit}
        title={isStreaming ? '' : 'Double-click to edit manually'}
      >
        {editing ? (
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit();
              else if (e.key === 'Escape') cancel();
            }}
            style={{
              fontFamily: fSerif,
              fontSize: 17,
              letterSpacing: -0.3,
              color: N2.text,
              background: 'rgba(255,253,247,0.05)',
              border: `1px solid ${N2.accent}`,
              borderRadius: 2,
              padding: '4px 8px',
              width: '100%',
              outline: 'none',
            }}
          />
        ) : r.status === 'pending' ? (
          <span
            style={{
              fontFamily: fMono,
              fontSize: 14,
              color: N2.text4,
              letterSpacing: 2,
            }}
            aria-label="pending"
          >
            — — —
          </span>
        ) : r.clean == null ? (
          <span
            style={{
              fontFamily: fSerif,
              fontStyle: 'italic',
              fontSize: 17,
              color: N2.rose,
              letterSpacing: -0.2,
              fontWeight: 400,
            }}
          >
            null
          </span>
        ) : (
          <span
            style={{
              fontFamily: fSerif,
              fontSize: 17,
              color: N2.text,
              letterSpacing: -0.3,
              fontWeight: 400,
              fontVariationSettings: '"opsz" 40, "SOFT" 30',
            }}
          >
            {r.clean}
          </span>
        )}
      </td>
      <td style={td}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 10,
          }}
        >
          <N2Chip status={r.status} />
          <button
            type="button"
            disabled={isStreaming}
            onClick={(e) => {
              e.stopPropagation();
              void rerunRow(r.n, kind);
            }}
            title={
              r.status === 'pending'
                ? 'Clean just this row through Grok'
                : 'Re-run this row through Grok'
            }
            aria-label={`Run row ${r.n}`}
            style={{
              background: 'transparent',
              border: `1px solid ${isStreaming ? N2.hair : N2.hair3}`,
              color: isStreaming ? N2.text4 : N2.accent,
              width: 24,
              height: 24,
              borderRadius: 2,
              padding: 0,
              fontSize: 10,
              lineHeight: 1,
              cursor: isStreaming ? 'not-allowed' : 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontFamily: fMono,
            }}
          >
            ▶
          </button>
        </div>
      </td>
      <td
        style={{
          ...td,
          color: N2.text2,
          maxWidth: 380,
          fontSize: 12,
          lineHeight: 1.5,
        }}
      >
        {r.reason}
      </td>
    </tr>
  );
}
