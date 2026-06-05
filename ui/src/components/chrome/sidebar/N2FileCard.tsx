import { N2, fBody, fMono } from '../../../theme';
import { useStore, viewState } from '../../../store';

export function N2FileCard() {
  const slice = useStore((s) => s.fullname);
  const setColumn = useStore((s) => s.setColumn);
  const file = slice.file;
  if (!file) return null;

  const view = viewState(slice);
  const options = file.columns && file.columns.length > 0 ? file.columns : [file.column];
  const canEdit = view === 'indexed';
  const displayValue = view === 'awaiting_column' ? '' : file.column;

  return (
    <div style={{ paddingTop: 12, borderTop: `1px solid ${N2.hair}` }}>
      <div
        style={{
          fontFamily: fMono,
          fontSize: 9,
          color: N2.text3,
          letterSpacing: 1.8,
          textTransform: 'uppercase',
          marginBottom: 5,
        }}
      >
        Source
      </div>
      <div
        style={{
          fontFamily: fBody,
          fontSize: 13,
          fontWeight: 500,
          color: N2.text,
          letterSpacing: -0.1,
          overflowWrap: 'anywhere',
          lineHeight: 1.35,
        }}
      >
        {file.name}
      </div>
      <div
        style={{
          fontFamily: fMono,
          fontSize: 10,
          color: N2.text2,
          marginTop: 3,
          display: 'flex',
          gap: 8,
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        <span>{file.rows.toLocaleString('en-US')} rows</span>
        <span style={{ color: N2.text4 }}>·</span>
        <span>{file.encoding}</span>
      </div>

      <ColumnRow
        label="Column"
        value={displayValue}
        options={options}
        view={view}
        canEdit={canEdit}
        onChange={(v) => setColumn(v)}
      />
    </div>
  );
}


function ColumnRow({
  label,
  value,
  options,
  view,
  canEdit,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  view: ReturnType<typeof viewState>;
  canEdit: boolean;
  onChange: (v: string) => void;
}) {
  return (
    <div
      style={{
        marginTop: 10,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <span
        style={{
          fontFamily: fMono,
          fontSize: 9,
          color: N2.text3,
          letterSpacing: 1.8,
          textTransform: 'uppercase',
          minWidth: 56,
        }}
      >
        {label}
      </span>
      <select
        value={value}
        disabled={!canEdit}
        onChange={(e) => onChange(e.target.value)}
        style={{
          flex: 1,
          background: 'rgba(255,253,247,0.03)',
          color: N2.accent,
          fontFamily: fMono,
          fontSize: 11,
          letterSpacing: 0.2,
          border: `1px solid ${N2.hair2}`,
          borderRadius: 2,
          padding: '6px 8px',
          outline: 'none',
          cursor: canEdit ? 'pointer' : 'not-allowed',
          appearance: 'none',
          WebkitAppearance: 'none',
          backgroundImage: `linear-gradient(45deg, transparent 50%, ${N2.accent} 50%), linear-gradient(135deg, ${N2.accent} 50%, transparent 50%)`,
          backgroundPosition:
            'calc(100% - 12px) calc(50% - 2px), calc(100% - 7px) calc(50% - 2px)',
          backgroundSize: '5px 5px, 5px 5px',
          backgroundRepeat: 'no-repeat',
          paddingRight: 24,
        }}
      >
        {view === 'awaiting_column' && (
          <option value="" style={{ background: N2.bg3, color: N2.text3 }}>
            pick a column →
          </option>
        )}
        {options.map((c) => (
          <option key={c} value={c} style={{ background: N2.bg3, color: N2.text }}>
            {c}
          </option>
        ))}
      </select>
    </div>
  );
}
