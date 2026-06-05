import { useState, type CSSProperties } from 'react';
import { N2, fSerif, fMono } from '../../theme';
import { N2Chip } from '../atoms/N2Chip';
import type { AppState, Row } from '../../types';
import { useStore } from '../../store';
import { overrideRow, rerunRow } from '../../lib/actions';

const td: CSSProperties = {
  padding: '11px 20px',
  borderBottom: `1px solid ${N2.hair}`,
  verticalAlign: 'middle',
};

// Splitter table: each row maps a single input cell to TWO output cells
// (First Name / Last Name). Double-click either cell to edit it
// independently of the other.
export function N2Table({ view }: { view: AppState }) {
  const slice = useStore((s) => s.fullname);
  const selectRow = useStore((s) => s.selectRow);
  const isStreaming = view === 'running';

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
            ['First Name', null],
            ['Last Name', null],
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
              selected={isSel}
              justArrived={justArrived}
              isStreaming={isStreaming}
              onSelect={() => selectRow(i)}
            />
          );
        })}
        {isStreaming && slice.progress.processed < slice.progress.total && (
          <tr>
            <td colSpan={6} style={{ padding: '14px 20px', color: N2.text3 }}>
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
  selected: boolean;
  justArrived: boolean;
  isStreaming: boolean;
  onSelect: () => void;
}

function TableRow({ row, selected, justArrived, isStreaming, onSelect }: RowProps) {
  const r = row;
  // Edit state per output cell, independent of the other.
  const [editing, setEditing] = useState<null | 'first' | 'last'>(null);
  const [draftFirst, setDraftFirst] = useState<string>(r.first ?? '');
  const [draftLast, setDraftLast] = useState<string>(r.last ?? '');

  const startEdit = (which: 'first' | 'last') => {
    if (isStreaming) return;
    setDraftFirst(r.first ?? '');
    setDraftLast(r.last ?? '');
    setEditing(which);
  };
  const commit = (which: 'first' | 'last') => {
    setEditing(null);
    const f = (which === 'first' ? draftFirst : (r.first ?? '')).trim();
    const l = (which === 'last' ? draftLast : (r.last ?? '')).trim();
    const nextF = f.length === 0 ? null : f;
    const nextL = l.length === 0 ? null : l;
    if (nextF === r.first && nextL === r.last) return; // no change
    void overrideRow(r.n, nextF, nextL);
  };
  const cancelEdit = () => {
    setEditing(null);
    setDraftFirst(r.first ?? '');
    setDraftLast(r.last ?? '');
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
      <SplitCell
        value={r.first}
        status={r.status}
        editing={editing === 'first'}
        draft={draftFirst}
        setDraft={setDraftFirst}
        onStart={() => startEdit('first')}
        onCommit={() => commit('first')}
        onCancel={cancelEdit}
        isStreaming={isStreaming}
      />
      <SplitCell
        value={r.last}
        status={r.status}
        editing={editing === 'last'}
        draft={draftLast}
        setDraft={setDraftLast}
        onStart={() => startEdit('last')}
        onCommit={() => commit('last')}
        onCancel={cancelEdit}
        isStreaming={isStreaming}
      />
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
              void rerunRow(r.n);
            }}
            title={
              r.status === 'pending'
                ? 'Split just this row through Grok'
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

interface SplitCellProps {
  value: string | null;
  status: Row['status'];
  editing: boolean;
  draft: string;
  setDraft: (v: string) => void;
  onStart: () => void;
  onCommit: () => void;
  onCancel: () => void;
  isStreaming: boolean;
}

function SplitCell({
  value,
  status,
  editing,
  draft,
  setDraft,
  onStart,
  onCommit,
  onCancel,
  isStreaming,
}: SplitCellProps) {
  return (
    <td
      style={{
        ...td,
        cursor: isStreaming || editing ? 'default' : 'pointer',
      }}
      onDoubleClick={onStart}
      title={isStreaming ? '' : 'Double-click to edit manually'}
    >
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={onCommit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onCommit();
            else if (e.key === 'Escape') onCancel();
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
      ) : status === 'pending' ? (
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
      ) : value == null || value === '' ? (
        // Null per-cell: render as italic "null" in rose (same visual as
        // the legacy single-cell null). A row with both cells empty AND
        // status=='null' is the only true "no split" state — see the row
        // status chip for that signal.
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
          {value}
        </span>
      )}
    </td>
  );
}
