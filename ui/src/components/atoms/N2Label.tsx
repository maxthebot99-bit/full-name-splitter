import type { ReactNode } from 'react';
import { N2, fMono } from '../../theme';

interface Props {
  children: ReactNode;
  accent?: string;
  mark?: boolean;
}

export function N2Label({ children, accent, mark }: Props) {
  return (
    <div
      style={{
        fontFamily: fMono,
        fontSize: 9.5,
        color: N2.text3,
        letterSpacing: 1.8,
        textTransform: 'uppercase',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7,
      }}
    >
      {mark && (
        <span
          style={{
            width: 4,
            height: 4,
            background: accent || N2.accent,
            borderRadius: 2,
            boxShadow: `0 0 6px ${accent || N2.accent}`,
          }}
        />
      )}
      {children}
    </div>
  );
}
