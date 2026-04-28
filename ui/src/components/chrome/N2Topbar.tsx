import { N2, fSerif, fMono, fBody } from '../../theme';
import type { AppState, Kind } from '../../types';
import { useStore } from '../../store';
import { getBackAction, openHistory } from '../../lib/actions';

const LABELS: Record<AppState, { txt: string; color: string }> = {
  empty: { txt: 'awaiting source', color: N2.text3 },
  awaiting_column: { txt: 'pick column', color: N2.accent },
  indexed: { txt: 'indexed', color: N2.accent },
  running: { txt: 'in motion', color: N2.accent },
  done: { txt: 'reconciled', color: N2.sage },
  error: { txt: 'paused', color: N2.rose },
};

interface Props {
  view: AppState;
}

export function N2Topbar({ view }: Props) {
  const l = LABELS[view];
  const active = useStore((s) => s.active);
  const setActive = useStore((s) => s.setActive);
  const whoami = useStore((s) => s.whoami);
  const setSettingsOpen = useStore((s) => s.setSettingsModalOpen);
  // Re-render the back button when dry-run state flips.
  const dryRun = useStore((s) => s[s.active].dryRun);
  const dryRunLoading = useStore((s) => s[s.active].dryRunLoading);
  void dryRun;
  void dryRunLoading;
  const back = getBackAction();

  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        rowGap: 8,
        padding: '10px 20px',
        minHeight: 56,
        borderBottom: `1px solid ${N2.hair}`,
        background: 'rgba(14,15,23,0.55)',
        backdropFilter: 'blur(24px)',
        minWidth: 0,
        flexWrap: 'wrap',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flex: '0 1 auto', minWidth: 0 }}>
        {back && (
          <button
            type="button"
            onClick={back.onClick}
            title={back.label}
            style={{
              background: 'transparent',
              border: `1px solid ${N2.hair2}`,
              color: N2.text2,
              padding: '6px 12px',
              borderRadius: 2,
              fontFamily: fMono,
              fontSize: 10,
              letterSpacing: 1.6,
              textTransform: 'uppercase',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              transition: 'background .12s ease, color .12s ease, border-color .12s ease',
            }}
          >
            <span style={{ fontSize: 12, lineHeight: 1 }}>←</span>
            <span>{back.label}</span>
          </button>
        )}
        <div
          style={{
            fontFamily: fSerif,
            fontStyle: 'italic',
            fontSize: 22,
            color: N2.accent,
            letterSpacing: -0.5,
            fontWeight: 400,
            fontVariationSettings: '"opsz" 72, "SOFT" 100',
          }}
        >
          Cleaners Hub
        </div>
        {/* Tab switcher — Companies / First Names */}
        <div style={{ display: 'flex', gap: 2, marginLeft: 6 }}>
          <TabBtn label="Companies" kind="company" active={active} onSelect={setActive} />
          <TabBtn label="First Names" kind="name" active={active} onSelect={setActive} />
        </div>
      </div>

      <div
        style={{
          fontFamily: fMono,
          fontSize: 9.5,
          color: l.color,
          letterSpacing: 2.5,
          textTransform: 'uppercase',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flex: '0 0 auto',
          marginLeft: 'auto',
        }}
      >
        <span
          style={{
            width: 4,
            height: 4,
            background: l.color,
            borderRadius: 2,
            boxShadow: `0 0 6px ${l.color}`,
            animation: view === 'running' ? 'n2Pulse 1.5s ease-in-out infinite' : 'none',
          }}
        />
        {l.txt}
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          justifyContent: 'flex-end',
          flex: '0 0 auto',
        }}
      >
        {whoami && (
          <span
            title={`signed in as ${whoami.email}`}
            style={{
              fontFamily: fMono,
              fontSize: 10,
              color: N2.text3,
              letterSpacing: 0.5,
            }}
          >
            ${whoami.today_usd.toFixed(2)} / ${whoami.cap_usd.toFixed(0)}
          </span>
        )}
        <button
          type="button"
          onClick={() => openHistory()}
          title="View past runs"
          style={chromeBtn()}
        >
          history
        </button>
        {whoami?.is_admin && (
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            title="Admin settings"
            style={chromeBtn()}
          >
            settings
          </button>
        )}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '4px 10px 4px 5px',
            border: `1px solid ${N2.hair}`,
            borderRadius: 100,
            fontSize: 11,
            color: N2.text2,
          }}
        >
          <span
            style={{
              width: 20,
              height: 20,
              borderRadius: 100,
              background: '#000',
              display: 'grid',
              placeItems: 'center',
              fontSize: 10,
              fontWeight: 700,
              color: '#fff',
              fontFamily: fBody,
            }}
          >
            𝕏
          </span>
          <span style={{ fontFamily: fMono, fontSize: 10.5, letterSpacing: 0.3 }}>
            grok
          </span>
          <span
            style={{
              width: 5,
              height: 5,
              borderRadius: 3,
              background: N2.sage,
              boxShadow: `0 0 5px ${N2.sage}`,
            }}
          />
        </div>
      </div>
    </header>
  );
}

function chromeBtn(): React.CSSProperties {
  return {
    background: 'transparent',
    border: `1px solid ${N2.hair2}`,
    color: N2.text2,
    padding: '6px 10px',
    borderRadius: 2,
    fontFamily: fMono,
    fontSize: 9.5,
    letterSpacing: 1.4,
    textTransform: 'uppercase',
    fontWeight: 600,
    cursor: 'pointer',
  };
}

function TabBtn({
  label,
  kind,
  active,
  onSelect,
}: {
  label: string;
  kind: Kind;
  active: Kind;
  onSelect: (k: Kind) => void;
}) {
  const on = active === kind;
  return (
    <button
      type="button"
      onClick={() => onSelect(kind)}
      style={{
        background: on ? 'rgba(199,179,255,0.10)' : 'transparent',
        border: `1px solid ${on ? N2.accent : N2.hair2}`,
        color: on ? N2.accent : N2.text3,
        padding: '6px 12px',
        borderRadius: 2,
        fontFamily: fMono,
        fontSize: 10,
        letterSpacing: 1.6,
        textTransform: 'uppercase',
        fontWeight: 700,
        cursor: 'pointer',
        boxShadow: on
          ? '0 0 0 1px rgba(199,179,255,0.18), 0 0 14px rgba(199,179,255,0.14)'
          : 'none',
        transition: 'all .12s ease',
      }}
    >
      {label}
    </button>
  );
}
