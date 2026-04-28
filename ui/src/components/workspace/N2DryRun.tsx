import type { CSSProperties } from 'react';
import { N2, fSerif, fBody, fMono } from '../../theme';
import { useStore } from '../../store';
import { closeDryRun } from '../../lib/actions';

// Dry-run-sample panel. Shown in the workspace while `dryRun` is populated
// in the active slice. Hosts the kicker, the meta strip (model / time /
// cost), the four tally tabs, and the diff table. Closing returns to the
// table or the column mapper.
export function N2DryRun() {
  const slice = useStore((s) => s[s.active]);
  const result = slice.dryRun;
  const loading = slice.dryRunLoading;
  const filter = slice.dryRunFilter;
  const setDryRunFilter = useStore((s) => s.setDryRunFilter);
  const file = slice.file;

  if (loading && !result) {
    return (
      <div
        style={{
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: fMono,
          fontSize: 11,
          letterSpacing: 1.6,
          textTransform: 'uppercase',
          color: N2.text3,
        }}
      >
        Grok is reading 25 rows…
      </div>
    );
  }
  if (!result) return null;

  const { rows, meta } = result;
  const counts = {
    all: rows.length,
    changed: rows.filter((r) => r.kind === 'changed').length,
    same: rows.filter((r) => r.kind === 'same').length,
    flag: rows.filter((r) => r.kind === 'flag').length,
    blank: rows.filter((r) => r.kind === 'blank').length,
  };
  const visible = filter === 'all' ? rows : rows.filter((r) => r.kind === filter);
  const totalRows = file?.rows ?? 0;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        padding: '34px 48px 28px',
        overflow: 'auto',
        height: '100%',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 40,
          marginBottom: 22,
          flexWrap: 'wrap',
          flexShrink: 0,
        }}
      >
        <div style={{ maxWidth: 680 }}>
          <div
            style={{
              fontFamily: fMono,
              fontSize: 10,
              letterSpacing: 2,
              textTransform: 'uppercase',
              color: N2.sage,
              marginBottom: 10,
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: N2.sage,
                boxShadow: `0 0 10px rgba(111,227,168,0.45)`,
                display: 'inline-block',
              }}
            />
            Dry run complete · {meta.count} rows
          </div>
          <div
            style={{
              fontFamily: fSerif,
              fontSize: 30,
              lineHeight: 1.15,
              letterSpacing: -0.6,
              color: N2.text,
              fontWeight: 500,
              fontVariationSettings: '"opsz" 80, "SOFT" 40',
            }}
          >
            Here's how Grok read the first {meta.count} rows.
          </div>
          <div
            style={{
              color: N2.text2,
              fontSize: 13.5,
              lineHeight: 1.55,
              marginTop: 8,
            }}
          >
            Scan the diff below. Commit to the full{' '}
            <b style={{ color: N2.text2, fontWeight: 500 }}>
              {totalRows.toLocaleString('en-US')}
            </b>{' '}
            from the sidebar, or hit{' '}
            <b style={{ color: N2.text2, fontWeight: 500 }}>Back</b> to adjust the row
            limit first.
          </div>
        </div>
        <div
          style={{
            display: 'flex',
            gap: 18,
            fontFamily: fMono,
            fontSize: 10.5,
            color: N2.text3,
            letterSpacing: 1.2,
            textTransform: 'uppercase',
            paddingBottom: 8,
          }}
        >
          <span>
            model
            <b
              style={{
                color: N2.text,
                fontWeight: 500,
                letterSpacing: 0.5,
                textTransform: 'none',
                fontFamily: fBody,
                fontSize: 12.5,
                marginLeft: 6,
              }}
            >
              {meta.model || '—'}
            </b>
          </span>
          <span style={{ color: N2.hair3 }}>·</span>
          <span>
            time
            <b
              style={{
                color: N2.text,
                fontWeight: 500,
                letterSpacing: 0.5,
                textTransform: 'none',
                fontFamily: fBody,
                fontSize: 12.5,
                marginLeft: 6,
              }}
            >
              {meta.elapsedSeconds.toFixed(1)}s
            </b>
          </span>
          <span style={{ color: N2.hair3 }}>·</span>
          <span>
            cost
            <b
              style={{
                color: N2.text,
                fontWeight: 500,
                letterSpacing: 0.5,
                textTransform: 'none',
                fontFamily: fBody,
                fontSize: 12.5,
                marginLeft: 6,
              }}
            >
              ${meta.costUsd.toFixed(4)}
            </b>
          </span>
        </div>
      </div>

      <div
        role="tablist"
        style={{
          display: 'flex',
          alignItems: 'stretch',
          gap: 0,
          marginBottom: 18,
          border: `1px solid ${N2.hair}`,
          borderRadius: 3,
          background: 'rgba(255,253,247,0.02)',
          flexShrink: 0,
        }}
      >
        <TallyTab active={filter === 'all'} onClick={() => setDryRunFilter(slice.kind, 'all')} count={counts.all} label="rows processed" countColor={N2.text} />
        <TallyTab active={filter === 'changed'} onClick={() => setDryRunFilter(slice.kind, 'changed')} count={counts.changed} label="cleaned" countColor={N2.accent} />
        <TallyTab active={filter === 'same'} onClick={() => setDryRunFilter(slice.kind, 'same')} count={counts.same} label="already clean" countColor={N2.text2} />
        <TallyTab active={filter === 'flag'} onClick={() => setDryRunFilter(slice.kind, 'flag')} count={counts.flag} label="flagged · review" countColor="#e8b356" />
        <TallyTab active={filter === 'blank'} onClick={() => setDryRunFilter(slice.kind, 'blank')} count={counts.blank} label="blank" countColor={N2.text4} last />
      </div>

      <div
        style={{
          border: `1px solid ${N2.hair}`,
          borderRadius: 3,
          background: 'rgba(255,253,247,0.02)',
          overflow: 'hidden',
          flexShrink: 0,
        }}
      >
        <table
          style={{
            width: '100%',
            borderCollapse: 'separate',
            borderSpacing: 0,
            fontFamily: fMono,
            fontSize: 12,
          }}
        >
          <thead>
            <tr>
              {['#', 'Original', '', 'Cleaned', 'Reason'].map((h, i) => (
                <th
                  key={i}
                  style={{
                    padding: '12px 16px 11px',
                    textAlign: i === 4 ? 'right' : 'left',
                    background: N2.bg,
                    fontSize: 9.5,
                    letterSpacing: 1.4,
                    textTransform: 'uppercase',
                    color: N2.text3,
                    fontWeight: 500,
                    borderBottom: `1px solid ${N2.hair2}`,
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ padding: 26, textAlign: 'center', color: N2.text3 }}>
                  No rows match this filter.
                </td>
              </tr>
            ) : (
              visible.map((r, i) => {
                const last = i === visible.length - 1;
                const cleanColor =
                  r.kind === 'same' ? N2.text4 :
                  r.kind === 'flag' ? '#e8b356' :
                  r.kind === 'blank' ? N2.text4 :
                  N2.text;
                const cleanStyle: CSSProperties = {
                  color: cleanColor,
                  fontWeight: r.kind === 'same' || r.kind === 'blank' ? 400 : 500,
                  fontStyle: r.kind === 'blank' ? 'italic' : 'normal',
                };
                const tagBorder = r.kind === 'flag' ? 'rgba(232,179,86,0.4)' : N2.hair2;
                const tagColor = r.kind === 'flag' ? '#e8b356' : r.kind === 'blank' ? N2.text4 : N2.text2;
                return (
                  <tr key={r.n}>
                    <td
                      style={{
                        ...cell(last),
                        width: 44,
                        color: N2.text4,
                        fontSize: 10.5,
                        textAlign: 'right',
                        background: 'rgba(255,253,247,0.03)',
                      }}
                    >
                      {String(r.n).padStart(2, '0')}
                    </td>
                    <td
                      style={{
                        ...cell(last),
                        color: N2.text3,
                        fontSize: 11.5,
                      }}
                    >
                      {r.orig || (
                        <span style={{ color: N2.text4, fontStyle: 'italic' }}>(empty)</span>
                      )}
                    </td>
                    <td
                      style={{
                        ...cell(last),
                        width: 28,
                        color: N2.text4,
                        textAlign: 'center',
                        fontSize: 11,
                      }}
                    >
                      →
                    </td>
                    <td
                      style={{
                        ...cell(last),
                        ...cleanStyle,
                        fontSize: 12,
                      }}
                    >
                      {r.clean}
                    </td>
                    <td
                      style={{
                        ...cell(last),
                        width: 200,
                        fontSize: 10,
                        letterSpacing: 1.2,
                        textTransform: 'uppercase',
                        color: N2.text3,
                        textAlign: 'right',
                      }}
                    >
                      {r.tag ? (
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '3px 7px',
                            border: `1px solid ${tagBorder}`,
                            borderRadius: 2,
                            color: tagColor,
                            background: 'rgba(255,253,247,0.02)',
                          }}
                        >
                          {r.tag}
                        </span>
                      ) : (
                        <span style={{ color: N2.text4 }}>—</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginTop: 20,
          paddingTop: 18,
          borderTop: `1px solid ${N2.hair}`,
          gap: 24,
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontSize: 12.5,
            color: N2.text3,
            lineHeight: 1.55,
            maxWidth: 560,
          }}
        >
          Looks off? Click <b style={{ color: N2.text2, fontWeight: 500 }}>Back</b> and pick
          a different column, or adjust the row limit in the sidebar before committing to
          all {totalRows.toLocaleString('en-US')}.
        </div>
        <button
          type="button"
          onClick={() => closeDryRun()}
          style={{
            background: 'transparent',
            color: N2.text2,
            border: `1px solid ${N2.hair2}`,
            padding: '11px 22px',
            borderRadius: 2,
            fontFamily: fMono,
            fontSize: 11,
            letterSpacing: 1.6,
            textTransform: 'uppercase',
            fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          ← Back
        </button>
      </div>
    </div>
  );
}

interface TallyTabProps {
  active: boolean;
  count: number;
  label: string;
  countColor: string;
  onClick: () => void;
  last?: boolean;
}
function TallyTab({ active, count, label, countColor, onClick, last }: TallyTabProps) {
  return (
    <div
      role="tab"
      tabIndex={0}
      aria-selected={active}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        padding: '14px 18px',
        cursor: 'pointer',
        borderRight: last ? 'none' : `1px solid ${N2.hair}`,
        transition: 'background .12s ease',
        boxSizing: 'border-box',
        userSelect: 'none',
        background: active ? 'rgba(199,179,255,0.08)' : 'transparent',
        boxShadow: active ? `inset 0 -2px 0 ${N2.accent}` : 'none',
      }}
    >
      <span
        style={{
          fontFamily: fSerif,
          fontSize: 26,
          lineHeight: 1,
          color: countColor,
          fontWeight: 500,
          fontVariationSettings: '"opsz" 60',
        }}
      >
        {count}
      </span>
      <span
        style={{
          fontFamily: fMono,
          fontSize: 9.5,
          letterSpacing: 1.4,
          textTransform: 'uppercase',
          color: N2.text3,
        }}
      >
        {label}
      </span>
    </div>
  );
}

function cell(last: boolean): CSSProperties {
  return {
    padding: '10px 16px',
    borderBottom: last ? 'none' : `1px solid ${N2.hair}`,
    verticalAlign: 'middle',
  };
}
