import type { CSSProperties } from 'react';
import { N2, fSerif, fMono } from '../../theme';
import { N2Chip } from '../atoms/N2Chip';
import { N2Label } from '../atoms/N2Label';
import { useStore } from '../../store';

const td: CSSProperties = {
  padding: '11px 20px',
  borderBottom: `1px solid ${N2.hair}`,
  verticalAlign: 'middle',
};

export function N2ErrorView() {
  const slice = useStore((s) => s[s.active]);
  const error = slice.error;
  const spendBlocked = slice.spendBlocked;
  const lastRows = slice.rows.slice(-3);
  // Don't fall back to "HTTP 429 · rate_limited" with a stale row 0 when
  // slice.error is genuinely missing — that misleads (a previous bug
  // surfaced this on cancellation). Prefer counting the rows that DID
  // make it through before the run hit error state.
  const cleanedFromRows = slice.rows.filter((r) => r.status !== 'pending').length;
  const last = error?.lastRow ?? cleanedFromRows;
  const cleaned = Math.max(0, last - 1);
  const retry = error?.retryAfter ?? 0;

  return (
    <div style={{ padding: 32 }}>
      <div
        style={{
          padding: '22px 24px',
          borderRadius: 2,
          background: N2.roseDim,
          border: `1px solid ${N2.rose}44`,
          display: 'grid',
          gridTemplateColumns: 'auto 1fr',
          gap: 22,
          alignItems: 'start',
        }}
      >
        <div
          style={{
            fontFamily: fSerif,
            fontStyle: 'italic',
            fontSize: 48,
            color: N2.rose,
            fontWeight: 400,
            lineHeight: 1,
          }}
        >
          !
        </div>
        <div>
          <div
            style={{
              fontFamily: fSerif,
              fontSize: 22,
              color: N2.text,
              letterSpacing: -0.4,
              lineHeight: 1.3,
            }}
          >
            {spendBlocked ? (
              <>Daily spend cap reached.</>
            ) : (
              <>
                A pause at <em style={{ color: N2.rose }}>row {last.toLocaleString('en-US')}</em>.
              </>
            )}
          </div>
          <div
            style={{
              fontFamily: fMono,
              fontSize: 10,
              color: N2.text2,
              marginTop: 8,
              lineHeight: 1.8,
              letterSpacing: 0.3,
            }}
          >
            {spendBlocked ? (
              <>
                today_usd=
                <span style={{ color: N2.rose }}>${spendBlocked.todayUsd.toFixed(2)}</span>
                {' · '}
                cap_usd=
                <span style={{ color: N2.accent }}>${spendBlocked.capUsd.toFixed(2)}</span>
              </>
            ) : error ? (
              <>
                HTTP {error.code} · {error.message}
                <br />
                retry_after=<span style={{ color: N2.accent }}>{retry}s</span>
                <br />
                partial results preserved ·{' '}
                <span style={{ color: N2.sage }}>
                  {cleaned.toLocaleString('en-US')} rows cleaned
                </span>
              </>
            ) : (
              <>
                An unexpected error occurred.
                <br />
                partial results preserved ·{' '}
                <span style={{ color: N2.sage }}>
                  {cleanedFromRows.toLocaleString('en-US')} rows cleaned
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      {lastRows.length > 0 && (
        <div style={{ marginTop: 22 }}>
          <N2Label>Cleaned so far · last 3 rows</N2Label>
          <table
            style={{
              width: '100%',
              borderCollapse: 'separate',
              borderSpacing: 0,
              fontSize: 12.5,
              marginTop: 10,
            }}
          >
            <tbody>
              {lastRows.map((r) => (
                <tr key={r.n}>
                  <td style={td}>
                    <span style={{ color: N2.text4, fontFamily: fMono, fontSize: 10 }}>
                      {String(r.n).padStart(3, '0')}
                    </span>
                  </td>
                  <td style={td}>
                    <span style={{ fontFamily: fMono, fontSize: 11.5, color: N2.text2 }}>
                      {r.orig}
                    </span>
                  </td>
                  <td style={td}>
                    <span
                      style={{
                        fontFamily: fSerif,
                        fontSize: 17,
                        color: N2.text,
                        letterSpacing: -0.3,
                      }}
                    >
                      {r.clean ?? 'null'}
                    </span>
                  </td>
                  <td style={td}>
                    <N2Chip status={r.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
