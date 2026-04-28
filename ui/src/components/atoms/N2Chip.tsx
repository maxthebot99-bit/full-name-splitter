import { N2, fMono } from '../../theme';
import type { RowStatus } from '../../types';

interface Props {
  status: RowStatus;
  size?: 'sm' | 'dot';
}

const M: Record<RowStatus, { color: string; label: string }> = {
  changed: { color: N2.sage, label: 'changed' },
  unchanged: { color: N2.ochre, label: 'unchanged' },
  null: { color: N2.rose, label: 'null' },
  pending: { color: N2.text3, label: 'pending' },
};

export function N2Chip({ status, size = 'sm' }: Props) {
  const m = M[status];
  if (size === 'dot') {
    return (
      <span
        style={{
          display: 'inline-block',
          width: 5,
          height: 5,
          background: m.color,
          boxShadow: `0 0 6px ${m.color}`,
        }}
      />
    );
  }
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        fontFamily: fMono,
        fontSize: 9.5,
        fontWeight: 500,
        color: m.color,
        letterSpacing: 1.2,
        textTransform: 'uppercase',
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          background: m.color,
          borderRadius: 1,
          boxShadow: `0 0 8px ${m.color}99`,
        }}
      />
      {m.label}
    </span>
  );
}
