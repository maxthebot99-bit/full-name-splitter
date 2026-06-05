import { useEffect, useState } from 'react';
import { N2, fSerif, fMono, fBody } from '../../theme';
import { useStore } from '../../store';
import { closeHistory, openHistory, pastRunDownloadUrl } from '../../lib/actions';

// Slide-in drawer listing past runs (history.py SQLite). Pulls /api/runs
// when opened. Each row shows kind/filename/state/cost and a download link
// when state === 'done'. Toggle "Mine only" filters to the signed-in email.
export function N2HistoryDrawer() {
  const open = useStore((s) => s.history.open);
  const loading = useStore((s) => s.history.loading);
  const runs = useStore((s) => s.history.runs);
  const total = useStore((s) => s.history.total);
  const isAdmin = useStore((s) => s.whoami?.is_admin ?? false);
  // Non-admins are server-side restricted to their own runs regardless of
  // this toggle, so we just hide the control for them — there's nothing
  // to toggle. Admins see all runs by default and can scope to their own.
  const [mineOnly, setMineOnly] = useState(false);

  // Escape closes the drawer.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeHistory();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(8,9,15,0.55)',
        backdropFilter: 'blur(4px)',
        WebkitBackdropFilter: 'blur(4px)',
        zIndex: 40,
        display: 'flex',
        justifyContent: 'flex-end',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) closeHistory();
      }}
    >
      <aside
        style={{
          width: 560,
          maxWidth: '100%',
          height: '100%',
          background: N2.bg,
          borderLeft: `1px solid ${N2.hair2}`,
          padding: '28px 28px 22px',
          display: 'grid',
          gridTemplateRows: 'auto auto 1fr',
          gap: 16,
          overflow: 'hidden',
          fontFamily: fBody,
          boxShadow: '-30px 0 80px rgba(0,0,0,0.4)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div
            style={{
              fontFamily: fSerif,
              fontSize: 26,
              color: N2.text,
              letterSpacing: -0.5,
              fontVariationSettings: '"opsz" 60',
            }}
          >
            Run history
          </div>
          <button
            type="button"
            onClick={closeHistory}
            style={{
              background: 'transparent',
              color: N2.text2,
              border: `1px solid ${N2.hair2}`,
              padding: '6px 10px',
              borderRadius: 2,
              fontFamily: fMono,
              fontSize: 10,
              letterSpacing: 1.4,
              textTransform: 'uppercase',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            close
          </button>
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            paddingBottom: 10,
            borderBottom: `1px solid ${N2.hair}`,
          }}
        >
          <span style={{ fontFamily: fMono, fontSize: 10, color: N2.text3, letterSpacing: 1.4 }}>
            {total.toLocaleString('en-US')} {isAdmin ? 'total' : 'of yours'}
          </span>
          {isAdmin && (
            <label
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                fontFamily: fMono,
                fontSize: 10,
                color: N2.text2,
                letterSpacing: 1.2,
                textTransform: 'uppercase',
                cursor: 'pointer',
              }}
            >
              <input
                type="checkbox"
                checked={mineOnly}
                onChange={(e) => {
                  const v = e.target.checked;
                  setMineOnly(v);
                  void openHistory({ mineOnly: v });
                }}
                style={{ accentColor: N2.accent as string }}
              />
              mine only
            </label>
          )}
        </div>

        <div style={{ overflow: 'auto' }}>
          {loading ? (
            <div style={{ padding: 26, textAlign: 'center', color: N2.text3, fontFamily: fMono, fontSize: 11 }}>
              loading…
            </div>
          ) : runs.length === 0 ? (
            <div style={{ padding: 26, textAlign: 'center', color: N2.text3, fontFamily: fMono, fontSize: 11 }}>
              no runs yet
            </div>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 8 }}>
              {runs.map((r) => {
                const stateColor =
                  r.state === 'done' ? N2.sage :
                  r.state === 'cancelled' ? N2.text3 :
                  r.state === 'error' || r.state === 'spend_blocked' ? N2.rose :
                  N2.accent;
                const ts = new Date(r.started_at);
                return (
                  <li
                    key={r.run_id}
                    style={{
                      border: `1px solid ${N2.hair}`,
                      borderRadius: 3,
                      background: N2.panel,
                      padding: '12px 14px',
                      display: 'grid',
                      gridTemplateColumns: '1fr auto',
                      gap: 12,
                      alignItems: 'center',
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div
                        style={{
                          fontFamily: fSerif,
                          fontSize: 17,
                          color: N2.text,
                          letterSpacing: -0.2,
                          fontWeight: 500,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {r.filename ?? '(no filename)'}
                      </div>
                      <div
                        style={{
                          fontFamily: fMono,
                          fontSize: 9.5,
                          color: N2.text3,
                          letterSpacing: 1.1,
                          textTransform: 'uppercase',
                          marginTop: 4,
                          display: 'flex',
                          gap: 10,
                          flexWrap: 'wrap',
                        }}
                      >
                        <span>full names</span>
                        <span style={{ color: N2.hair3 }}>·</span>
                        <span style={{ color: stateColor }}>{r.state}</span>
                        <span style={{ color: N2.hair3 }}>·</span>
                        <span>{r.row_count ?? '—'} rows</span>
                        <span style={{ color: N2.hair3 }}>·</span>
                        <span>${(r.cost_usd ?? 0).toFixed(3)}</span>
                        <span style={{ color: N2.hair3 }}>·</span>
                        <span>{ts.toLocaleString()}</span>
                      </div>
                      <div
                        style={{
                          fontFamily: fMono,
                          fontSize: 9,
                          color: N2.text4,
                          letterSpacing: 0.6,
                          marginTop: 2,
                        }}
                      >
                        {r.email}
                      </div>
                    </div>
                    {r.state === 'done' && r.output_path ? (
                      <a
                        href={pastRunDownloadUrl(r.run_id)}
                        style={{
                          background: 'transparent',
                          color: N2.accent,
                          border: `1px solid ${N2.accent}66`,
                          padding: '6px 10px',
                          borderRadius: 2,
                          fontFamily: fMono,
                          fontSize: 9.5,
                          letterSpacing: 1.4,
                          textTransform: 'uppercase',
                          fontWeight: 700,
                          textDecoration: 'none',
                        }}
                      >
                        ↓ csv
                      </a>
                    ) : (
                      <span
                        style={{
                          color: N2.text4,
                          fontFamily: fMono,
                          fontSize: 9.5,
                          letterSpacing: 1.2,
                          textTransform: 'uppercase',
                        }}
                      >
                        —
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </aside>
    </div>
  );
}
