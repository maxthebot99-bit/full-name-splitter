import { N2, fMono } from '../../theme';

interface Props {
  mark?: string;
  color?: string;
}

export function N2Hairline({ mark, color = N2.hair }: Props) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: N2.text4 }}>
      <span style={{ flex: 1, height: 1, background: color }} />
      {mark && (
        <span
          style={{
            fontFamily: fMono,
            fontSize: 8.5,
            letterSpacing: 2,
            color: N2.text3,
            textTransform: 'uppercase',
          }}
        >
          {mark}
        </span>
      )}
      <span style={{ flex: 1, height: 1, background: color }} />
    </div>
  );
}
