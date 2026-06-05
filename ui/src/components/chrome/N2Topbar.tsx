import { N2, fSerif, fMono, fBody } from '../../theme';
import type { AppState } from '../../types';
import { useStore } from '../../store';
import { getBackAction, openHistory } from '../../lib/actions';

const LABELS: Record<AppState, { txt: string; color: string }> = {
  empty: { txt: 'awaiting source', color: N2.text3 },
  awaiting_column: { txt: 'pick column', color: N2.accent },
  indexed: { txt: 'indexed', color: N2.accent },
  running: { txt: 'in motion', color: N2.accent },
  done: { txt: 'reconciled', color: N2.sage },
  cancelled: { txt: 'paused', color: N2.ochre },
  error: { txt: 'error', color: N2.rose },
};

interface Props {
  view: AppState;
}

export function N2Topbar({ view }: Props) {
  const l = LABELS[view];
  const whoami = useStore((s) => s.whoami);
  const setSettingsOpen = useStore((s) => s.setSettingsModalOpen);
  // Re-render when dry-run flips so the back-button label re-evaluates.
  const dryRun = useStore((s) => s.fullname.dryRun);
  const dryRunLoading = useStore((s) => s.fullname.dryRunLoading);
  void dryRun;
  void dryRunLoading;
  const back = getBackAction();

  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 18,
        rowGap: 10,
        padding: '10px 22px',
        minHeight: 60,
        borderBottom: `1px solid ${N2.hair}`,
        background: 'rgba(14,15,23,0.55)',
        backdropFilter: 'blur(24px)',
        minWidth: 0,
        flexWrap: 'wrap',
      }}
    >
      {/* Brand block: back button (when relevant) + brand mark + scope label.
          Splitter is single-kind, so the segmented tab control from the
          original cleaners-hub topbar collapses into a static label. */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          flex: '0 1 auto',
          minWidth: 0,
        }}
      >
        {back && (
          <button
            type="button"
            onClick={back.onClick}
            title={back.label}
            aria-label={back.label}
            style={{
              background: 'transparent',
              border: `1px solid ${N2.hair2}`,
              color: N2.text2,
              padding: '6px 10px',
              borderRadius: 2,
              fontFamily: fMono,
              fontSize: 10,
              letterSpacing: 1.4,
              textTransform: 'uppercase',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
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
            whiteSpace: 'nowrap',
          }}
        >
          Full Name Splitter
        </div>
        <Divider />
        <div
          aria-label="scope"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            padding: '7px 14px',
            border: `1px solid ${N2.hair2}`,
            borderRadius: 2,
            background: 'rgba(199,179,255,0.08)',
            color: N2.accent,
            fontFamily: fMono,
            fontSize: 10,
            letterSpacing: 1.6,
            textTransform: 'uppercase',
            fontWeight: 700,
            boxShadow: `inset 0 -2px 0 ${N2.accent}`,
          }}
        >
          Full Names
        </div>
      </div>

      {/* Status pill — center of mass when there's room; pushed right by
          marginLeft:auto. Single visual element, not three glued together. */}
      <div
        style={{
          fontFamily: fMono,
          fontSize: 9.5,
          color: l.color,
          letterSpacing: 2.5,
          textTransform: 'uppercase',
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 12px',
          border: `1px solid ${l.color}33`,
          background: `${l.color}10`,
          borderRadius: 2,
          flex: '0 0 auto',
          marginLeft: 'auto',
          whiteSpace: 'nowrap',
        }}
      >
        <span
          style={{
            width: 5,
            height: 5,
            background: l.color,
            borderRadius: 3,
            boxShadow: `0 0 6px ${l.color}`,
            animation: view === 'running' ? 'n2Pulse 1.5s ease-in-out infinite' : 'none',
          }}
        />
        {l.txt}
      </div>

      {/* Right block: spend → help / history / settings → grok chip. */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flex: '0 0 auto',
        }}
      >
        {whoami && (
          <SpendBadge
            today={whoami.today_usd}
            cap={whoami.cap_usd}
            email={whoami.email}
          />
        )}
        <div
          role="group"
          aria-label="actions"
          style={{
            display: 'inline-flex',
            border: `1px solid ${N2.hair2}`,
            borderRadius: 2,
            overflow: 'hidden',
          }}
        >
          <ChromeBtn label="Help" onClick={() => window.open('/help', '_blank', 'noopener,noreferrer')} />
          <ChromeBtn label="History" onClick={() => openHistory()} />
          {whoami?.is_admin && (
            <ChromeBtn label="Settings" onClick={() => setSettingsOpen(true)} last />
          )}
        </div>
        <ProviderChip />
      </div>
    </header>
  );
}

// Splitter is Grok-only — no Gemini / OpenRouter branch.
function ProviderChip() {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        padding: '5px 12px 5px 6px',
        border: `1px solid ${N2.hair}`,
        borderRadius: 100,
        fontSize: 11,
        color: N2.text2,
        whiteSpace: 'nowrap',
      }}
    >
      <span
        style={{
          width: 22,
          height: 22,
          borderRadius: 100,
          background: '#000',
          display: 'grid',
          placeItems: 'center',
          fontSize: 11,
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
  );
}

function Divider() {
  return (
    <span
      aria-hidden
      style={{
        width: 1,
        height: 18,
        background: N2.hair,
        display: 'inline-block',
      }}
    />
  );
}

function SpendBadge({
  today,
  cap,
  email,
}: {
  today: number;
  cap: number;
  email: string;
}) {
  const pct = cap > 0 ? Math.min(100, (today / cap) * 100) : 0;
  const tone = pct >= 90 ? N2.rose : pct >= 60 ? N2.ochre : N2.text3;
  return (
    <span
      title={`${email} · today $${today.toFixed(2)} / cap $${cap.toFixed(2)}`}
      style={{
        fontFamily: fMono,
        fontSize: 10,
        color: N2.text2,
        letterSpacing: 0.4,
        display: 'inline-flex',
        alignItems: 'baseline',
        gap: 4,
        padding: '5px 10px',
        border: `1px solid ${N2.hair2}`,
        borderRadius: 2,
        whiteSpace: 'nowrap',
      }}
    >
      <span style={{ color: tone, fontWeight: 600 }}>${today.toFixed(2)}</span>
      <span style={{ color: N2.text4 }}>/</span>
      <span style={{ color: N2.text3 }}>${cap.toFixed(0)}</span>
    </span>
  );
}

function ChromeBtn({
  label,
  onClick,
  last,
}: {
  label: string;
  onClick: () => void;
  last?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: 'transparent',
        border: 'none',
        borderRight: last ? 'none' : `1px solid ${N2.hair2}`,
        color: N2.text2,
        padding: '6px 14px',
        fontFamily: fMono,
        fontSize: 10,
        letterSpacing: 1.4,
        textTransform: 'uppercase',
        fontWeight: 600,
        cursor: 'pointer',
        transition: 'background .12s ease, color .12s ease',
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget as HTMLButtonElement;
        el.style.background = 'rgba(199,179,255,0.06)';
        el.style.color = N2.text;
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget as HTMLButtonElement;
        el.style.background = 'transparent';
        el.style.color = N2.text2;
      }}
    >
      {label}
    </button>
  );
}
