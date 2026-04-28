import { N2, fSerif, fMono } from '../../theme';
import type { AppState, FilterKind } from '../../types';
import { useStore } from '../../store';
import { downloadUrl } from '../../api';
import { resetActive } from '../../lib/actions';
import { N2Table } from './N2Table';
import { N2Detail } from './N2Detail';
import { N2EmptyHero } from './N2EmptyHero';
import { N2ErrorView } from './N2ErrorView';
import { N2ColumnMapper } from './N2ColumnMapper';
import { N2DryRun } from './N2DryRun';

interface PillProps {
  kind: FilterKind;
  count: number | null;
  label: string;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
}

function StatPill({ kind, count, label, active, disabled, onClick }: PillProps) {
  const activeHue =
    kind === 'changed' ? N2.sage :
    kind === 'unchanged' ? N2.ochre :
    kind === 'null' ? N2.rose :
    N2.accent;
  const activeBg =
    kind === 'changed' ? N2.sageDim :
    kind === 'unchanged' ? N2.ochreDim :
    kind === 'null' ? N2.roseDim :
    'rgba(199,179,255,0.14)';
  const sqColor =
    kind === 'all' ? (active ? N2.accent : N2.text2) :
    kind === 'changed' ? N2.sage :
    kind === 'unchanged' ? N2.ochre :
    N2.rose;
  const sqGlow =
    kind === 'all' ? (active ? '0 0 6px rgba(199,179,255,.6)' : 'none') :
    kind === 'changed' ? '0 0 6px rgba(111,227,168,.55)' :
    kind === 'unchanged' ? '0 0 6px rgba(255,209,102,.55)' :
    '0 0 6px rgba(255,122,138,.55)';

  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 14px',
        border: `1px solid ${active ? activeHue : N2.hair}`,
        background: active ? activeBg : 'transparent',
        boxShadow: active
          ? kind === 'all'
            ? '0 0 0 1px rgba(199,179,255,0.25), 0 0 14px rgba(199,179,255,0.18)'
            : `0 0 0 1px ${activeHue}33`
          : 'none',
        borderRadius: 2,
        fontFamily: fMono,
        fontSize: 10,
        letterSpacing: 1.4,
        textTransform: 'uppercase',
        color: N2.text3,
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.55 : 1,
        transition: 'border-color .15s ease, background .15s ease, box-shadow .15s ease',
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: 1,
          background: sqColor,
          boxShadow: sqGlow,
          display: 'inline-block',
        }}
      />
      <span
        style={{
          fontFamily: fSerif,
          fontSize: 20,
          fontWeight: 400,
          letterSpacing: -0.5,
          color: active ? activeHue : N2.text,
          fontFeatureSettings: '"lnum","tnum"',
          lineHeight: 1,
        }}
      >
        {count == null ? '—' : count.toLocaleString('en-US')}
      </span>
      <span>{label}</span>
    </button>
  );
}

function N2WorkspaceHeader({ view }: { view: AppState }) {
  const slice = useStore((s) => s[s.active]);
  const setFilter = useStore((s) => s.setFilter);
  const rows = slice.rows;
  const file = slice.file;

  const isEmpty = view === 'empty' || view === 'awaiting_column';
  const changedCount = rows.filter((r) => r.status === 'changed').length;
  const unchangedCount = rows.filter((r) => r.status === 'unchanged').length;
  const nullCount = rows.filter((r) => r.status === 'null').length;
  const allCount = Math.max(rows.length, file?.rows ?? 0);

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '14px 28px',
        borderBottom: `1px solid ${N2.hair}`,
      }}
    >
      <StatPill
        kind="all"
        count={isEmpty ? null : allCount}
        label="all"
        active={slice.filter === 'all'}
        disabled={isEmpty}
        onClick={() => setFilter(slice.kind, 'all')}
      />
      <StatPill
        kind="changed"
        count={isEmpty ? null : changedCount}
        label="changed"
        active={slice.filter === 'changed'}
        disabled={isEmpty}
        onClick={() => setFilter(slice.kind, 'changed')}
      />
      <StatPill
        kind="unchanged"
        count={isEmpty ? null : unchangedCount}
        label="unchanged"
        active={slice.filter === 'unchanged'}
        disabled={isEmpty}
        onClick={() => setFilter(slice.kind, 'unchanged')}
      />
      <StatPill
        kind="null"
        count={isEmpty ? null : nullCount}
        label="null"
        active={slice.filter === 'null'}
        disabled={isEmpty}
        onClick={() => setFilter(slice.kind, 'null')}
      />

      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
        <GhostButton
          label="↺ Reset"
          title="Clear the current file and results, return to the empty screen"
          disabled={view === 'empty'}
          onClick={() => {
            if (view === 'running') {
              if (!confirm('A run is in progress. Reset anyway? The current job will be cancelled.')) return;
            }
            resetActive();
          }}
        />
        <a
          href={view === 'done' && slice.sid ? downloadUrl(slice.sid) : undefined}
          onClick={(e) => {
            if (view !== 'done' || !slice.sid) e.preventDefault();
          }}
          style={{
            background:
              view === 'done'
                ? `linear-gradient(180deg, ${N2.accent}, ${N2.accentSoft})`
                : 'transparent',
            color: view === 'done' ? '#0a0612' : N2.text3,
            border: view === 'done' ? 'none' : `1px solid ${N2.hair2}`,
            padding: '7px 14px',
            borderRadius: 2,
            fontSize: 11,
            fontFamily: fMono,
            fontWeight: 600,
            letterSpacing: 1.2,
            textTransform: 'uppercase',
            cursor: view === 'done' ? 'pointer' : 'not-allowed',
            boxShadow: view === 'done' ? `0 0 18px ${N2.accentGlow}` : 'none',
            textDecoration: 'none',
            display: 'inline-block',
          }}
        >
          ↓ Export CSV
        </a>
      </div>
    </div>
  );
}

interface GhostButtonProps {
  label: string;
  title: string;
  onClick: () => void | Promise<void>;
  disabled?: boolean;
}
function GhostButton({ label, title, onClick, disabled = false }: GhostButtonProps) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={disabled ? undefined : onClick}
      style={{
        background: 'transparent',
        color: disabled ? N2.text4 : N2.text2,
        border: `1px solid ${disabled ? N2.hair : N2.hair2}`,
        padding: '7px 12px',
        borderRadius: 2,
        fontSize: 10.5,
        fontFamily: fMono,
        fontWeight: 600,
        letterSpacing: 1.2,
        textTransform: 'uppercase',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.6 : 1,
        transition: 'background .12s ease, color .12s ease, border-color .12s ease',
      }}
    >
      {label}
    </button>
  );
}

export function N2Workspace({ view }: { view: AppState }) {
  const dryRun = useStore((s) => s[s.active].dryRun);
  const dryRunLoading = useStore((s) => s[s.active].dryRunLoading);
  const showDryRun = (dryRun != null || dryRunLoading) && view !== 'empty' && view !== 'error';

  return (
    <section
      style={{
        display: 'grid',
        gridTemplateRows: 'auto 1fr auto',
        overflow: 'hidden',
        minWidth: 0,
      }}
    >
      <N2WorkspaceHeader view={view} />
      <div style={{ overflow: 'hidden' }}>
        {showDryRun ? (
          <N2DryRun />
        ) : view === 'empty' ? (
          <div style={{ height: '100%', overflow: 'auto' }}><N2EmptyHero /></div>
        ) : view === 'awaiting_column' ? (
          <N2ColumnMapper />
        ) : view === 'error' ? (
          <div style={{ height: '100%', overflow: 'auto' }}><N2ErrorView /></div>
        ) : (
          <div style={{ height: '100%', overflow: 'auto' }}><N2Table view={view} /></div>
        )}
      </div>
      {!showDryRun && view !== 'empty' && view !== 'awaiting_column' && view !== 'error' && (
        <N2Detail />
      )}
    </section>
  );
}
