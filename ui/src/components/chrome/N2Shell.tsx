import type { ReactNode } from 'react';
import { N2, fBody } from '../../theme';

interface Props {
  children: ReactNode;
}

export function N2Shell({ children }: Props) {
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        background: N2.bg,
        color: N2.text,
        fontFamily: fBody,
        fontSize: 13,
        lineHeight: 1.5,
        overflow: 'hidden',
        position: 'relative',
        fontFeatureSettings: '"ss01", "ss02"',
      }}
    >
      {/* Ambient breathing orbs. */}
      <div
        style={{
          position: 'absolute',
          width: 700,
          height: 700,
          borderRadius: '50%',
          background: `radial-gradient(circle, ${N2.accentGlow}, transparent 65%)`,
          top: -280,
          right: -220,
          filter: 'blur(40px)',
          pointerEvents: 'none',
          animation: 'n2Breathe 8s ease-in-out infinite',
        }}
      />
      <div
        style={{
          position: 'absolute',
          width: 500,
          height: 500,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(138,168,148,0.09), transparent 70%)',
          bottom: -220,
          left: -150,
          filter: 'blur(60px)',
          pointerEvents: 'none',
          animation: 'n2Breathe 10s ease-in-out infinite 2s',
        }}
      />
      {/* Grain. */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          opacity: 0.035,
          mixBlendMode: 'overlay',
          backgroundImage:
            "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence baseFrequency='0.9' numOctaves='2'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\")",
        }}
      />
      <div
        style={{
          position: 'relative',
          zIndex: 1,
          height: '100%',
          display: 'grid',
          gridTemplateRows: '56px 1fr 24px',
        }}
      >
        {children}
      </div>
    </div>
  );
}
