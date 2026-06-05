import { useEffect } from 'react';
import { N2, fSerif, fBody, fMono } from '../../theme';
import { useStore } from '../../store';
import { confirmCostModal, cancelCostModal } from '../../lib/actions';

// Cost-ceiling confirmation. Mounted when the active slice has costModal
// populated. Confirm routes the pending args to startRun; Cancel clears.
export function N2CostModal() {
  const modal = useStore((s) => s.fullname.costModal);

  // Escape closes the modal — standard ARIA dialog behavior. Hook is
  // declared at the top level (before the early return) so React's rules
  // of hooks aren't violated when the modal mounts and unmounts.
  useEffect(() => {
    if (!modal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') cancelCostModal();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [modal]);

  if (!modal) return null;

  const { rows, costUsd, elapsedSeconds, column } = modal;
  const mins = Math.round(elapsedSeconds / 60);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="cost-modal-title"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(8,9,15,0.72)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) cancelCostModal();
      }}
    >
      <div
        style={{
          width: 480,
          maxWidth: '100%',
          background: N2.bg,
          border: `1px solid ${N2.hair2}`,
          borderRadius: 4,
          padding: '32px 36px 28px',
          boxShadow: '0 40px 120px rgba(0,0,0,0.55)',
          fontFamily: fBody,
        }}
      >
        <div
          style={{
            fontFamily: fMono,
            fontSize: 10,
            letterSpacing: 2,
            textTransform: 'uppercase',
            color: N2.ochre,
            marginBottom: 12,
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
              background: N2.ochre,
              boxShadow: '0 0 10px rgba(255,209,102,0.5)',
              display: 'inline-block',
            }}
          />
          Cost check
        </div>
        <h3
          id="cost-modal-title"
          style={{
            fontFamily: fSerif,
            fontSize: 30,
            lineHeight: 1.15,
            fontWeight: 500,
            color: N2.text,
            margin: 0,
            letterSpacing: -0.5,
            fontVariationSettings: '"opsz" 80, "SOFT" 40',
          }}
        >
          This run will cost about{' '}
          <span style={{ color: N2.ochre, fontWeight: 500 }}>${costUsd.toFixed(2)}</span>.
        </h3>
        <p
          style={{
            color: N2.text2,
            fontSize: 13.5,
            lineHeight: 1.55,
            marginTop: 10,
            marginBottom: 22,
          }}
        >
          You're above the <b style={{ color: N2.text2, fontWeight: 500 }}>$5</b> ceiling.
          Double-check the column before committing — a dry run is a way cheaper sanity check.
        </p>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 1fr',
            gap: 12,
            padding: '14px 0 18px',
            borderTop: `1px solid ${N2.hair}`,
            borderBottom: `1px solid ${N2.hair}`,
            marginBottom: 22,
          }}
        >
          <Figure label="rows" value={rows.toLocaleString('en-US')} />
          <Figure label="column" value={column} mono />
          <Figure label="est. time" value={`~${mins}m`} />
        </div>

        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
          <button
            type="button"
            onClick={() => cancelCostModal()}
            style={{
              background: 'transparent',
              color: N2.text2,
              border: `1px solid ${N2.hair2}`,
              padding: '10px 18px',
              borderRadius: 2,
              fontFamily: fMono,
              fontSize: 10.5,
              letterSpacing: 1.6,
              textTransform: 'uppercase',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => confirmCostModal()}
            style={{
              background: `linear-gradient(180deg, ${N2.accent}, ${N2.accentSoft})`,
              color: '#0a0612',
              border: 'none',
              padding: '10px 22px',
              borderRadius: 2,
              fontFamily: fMono,
              fontSize: 10.5,
              letterSpacing: 1.6,
              textTransform: 'uppercase',
              fontWeight: 700,
              cursor: 'pointer',
              boxShadow: `0 0 18px ${N2.accentGlow}`,
            }}
          >
            Spend ${costUsd.toFixed(2)} · Run
          </button>
        </div>
      </div>
    </div>
  );
}

function Figure({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div
        style={{
          fontFamily: fMono,
          fontSize: 9,
          letterSpacing: 1.6,
          textTransform: 'uppercase',
          color: N2.text3,
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: mono ? fMono : fSerif,
          fontSize: mono ? 13 : 20,
          fontWeight: 500,
          color: N2.text,
          fontVariationSettings: mono ? undefined : '"opsz" 60',
          wordBreak: 'break-all',
        }}
      >
        {value}
      </div>
    </div>
  );
}
