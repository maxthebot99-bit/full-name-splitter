import { type CSSProperties } from 'react';
import { N2, fSerif, fMono } from '../../theme';
import type { AddressRow, AppState } from '../../types';
import { useStore } from '../../store';

const td: CSSProperties = {
  padding: '10px 14px',
  borderBottom: `1px solid ${N2.hair}`,
  verticalAlign: 'middle',
};

const th: CSSProperties = {
  padding: '8px 14px',
  textAlign: 'left',
  fontFamily: fMono,
  fontSize: 9.5,
  letterSpacing: 1.4,
  textTransform: 'uppercase',
  color: N2.text3,
  background: N2.panel,
  borderBottom: `1px solid ${N2.hair2}`,
  position: 'sticky',
  top: 0,
  zIndex: 1,
};

// Address-tab table — renders multi-field AddressRow rows. Used in place
// of N2Table when slice.kind === "address". Filters via slice.filter on
// the AddressRowStatus values ('extracted' | 'blank' | 'foreign' | 'fetch_failed').
export function N2AddressTable({ view: _view }: { view: AppState }) {
  const slice = useStore((s) => s[s.active]);
  const allRows = slice.addressRows;
  const rows = slice.filter === 'all'
    ? allRows
    : allRows.filter((r) => r.status === slice.filter);

  return (
    <table
      style={{
        width: '100%',
        borderCollapse: 'separate',
        borderSpacing: 0,
        fontSize: 12,
        fontFamily: fMono,
      }}
    >
      <thead>
        <tr>
          <th style={{ ...th, width: 50, textAlign: 'right' }}>#</th>
          <th style={th}>Business Name</th>
          <th style={th}>Website</th>
          <th style={th}>Street</th>
          <th style={th}>City</th>
          <th style={{ ...th, width: 56 }}>State</th>
          <th style={{ ...th, width: 70 }}>ZIP</th>
          <th style={{ ...th, width: 60 }}>Country</th>
          <th style={{ ...th, width: 80, textAlign: 'right' }}>Conf</th>
          <th style={{ ...th, width: 130 }}>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <AddressTableRow key={r.n} row={r} />
        ))}
        {rows.length === 0 && (
          <tr>
            <td colSpan={10} style={{ ...td, color: N2.text3, textAlign: 'center', padding: '40px 14px', fontFamily: fSerif, fontSize: 14 }}>
              No rows yet. Run will populate this table live.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function AddressTableRow({ row }: { row: AddressRow }) {
  const isFetchFail = row.status === 'fetch_failed';
  const isForeign = row.status === 'foreign';
  const isBlank = row.status === 'blank';
  const rowBg = isFetchFail
    ? 'rgba(255, 96, 96, 0.04)'
    : isForeign
      ? 'rgba(225, 180, 90, 0.04)'
      : isBlank
        ? 'rgba(120, 120, 130, 0.03)'
        : undefined;
  const muted = isFetchFail || isForeign || isBlank;
  const cellColor = muted ? N2.text3 : N2.text;

  return (
    <tr style={{ background: rowBg }}>
      <td style={{ ...td, color: N2.text4, textAlign: 'right' }}>{row.n}</td>
      <td style={{ ...td, color: cellColor, fontWeight: 500 }}>{row.business_name}</td>
      <td
        style={{
          ...td,
          color: N2.text3,
          maxWidth: 200,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {row.website_url}
      </td>
      <td style={{ ...td, color: cellColor }}>{row.street || em()}</td>
      <td style={{ ...td, color: cellColor }}>{row.city || em()}</td>
      <td style={{ ...td, color: cellColor }}>{row.state || em()}</td>
      <td style={{ ...td, color: cellColor }}>{row.zip || em()}</td>
      <td style={{ ...td, color: cellColor }}>{row.country || em()}</td>
      <td style={{ ...td, color: confidenceColor(row.confidence), textAlign: 'right' }}>
        {row.confidence > 0 ? row.confidence.toFixed(2) : ''}
      </td>
      <td style={td}>
        <StatusChip row={row} />
      </td>
    </tr>
  );
}

function em() {
  return <span style={{ color: N2.text4 }}>—</span>;
}

function confidenceColor(c: number): string {
  if (c >= 0.85) return N2.sage;
  if (c >= 0.5) return N2.text2;
  return N2.text3;
}

function StatusChip({ row }: { row: AddressRow }) {
  let label: string = row.status.replace('_', ' ');
  let bg: string = 'transparent';
  let border: string = N2.hair2;
  let color: string = N2.text3;
  if (row.status === 'extracted') {
    label = 'extracted';
    bg = 'rgba(111, 227, 168, 0.10)';
    border = 'rgba(111, 227, 168, 0.55)';
    color = N2.sage;
  } else if (row.status === 'foreign') {
    label = `foreign · ${row.country || '?'}`;
    bg = 'rgba(225, 180, 90, 0.08)';
    border = 'rgba(225, 180, 90, 0.45)';
    color = '#d4a35a';
  } else if (row.status === 'fetch_failed') {
    label = (row.error || 'fetch fail').toLowerCase().replace('_', ' ');
    bg = 'rgba(255, 96, 96, 0.07)';
    border = 'rgba(255, 96, 96, 0.4)';
    color = '#e57878';
  } else if (row.status === 'blank') {
    label = 'no address';
  } else if (row.status === 'pending') {
    label = 'queued';
  }
  return (
    <span
      style={{
        fontFamily: fMono,
        fontSize: 9,
        letterSpacing: 1.2,
        textTransform: 'uppercase',
        padding: '2px 8px',
        border: `1px solid ${border}`,
        background: bg,
        color,
        borderRadius: 2,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );
}
