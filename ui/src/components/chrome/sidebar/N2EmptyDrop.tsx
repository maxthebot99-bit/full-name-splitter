import { useState } from 'react';
import { N2, fSerif, fMono } from '../../../theme';
import { useStore } from '../../../store';
import { handleFileSelected, pickFile } from '../../../lib/actions';

export function N2EmptyDrop() {
  const kind = useStore((s) => s.active);
  const [hover, setHover] = useState(false);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => pickFile(kind)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') pickFile(kind);
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setHover(true);
      }}
      onDragLeave={() => setHover(false)}
      onDrop={(e) => {
        e.preventDefault();
        setHover(false);
        const f = e.dataTransfer.files?.[0];
        if (f) void handleFileSelected(kind, f);
      }}
      style={{
        padding: '36px 18px',
        textAlign: 'center',
        borderRadius: 2,
        border: `1px dashed ${hover ? N2.accent : N2.hair3}`,
        position: 'relative',
        background: `radial-gradient(circle at center, ${N2.accentGlow}, transparent 70%)`,
        cursor: 'pointer',
        boxShadow: hover ? `0 0 24px ${N2.accentGlow}` : 'none',
        transition: 'border-color .12s ease, box-shadow .12s ease',
      }}
    >
      <div
        style={{
          fontFamily: fSerif,
          fontStyle: 'italic',
          fontSize: 32,
          color: N2.accent,
          letterSpacing: -1,
          lineHeight: 1,
          fontWeight: 400,
        }}
      >
        Drop a CSV
      </div>
      <div
        style={{
          fontFamily: fSerif,
          fontSize: 20,
          color: N2.text,
          marginTop: 4,
          letterSpacing: -0.4,
          lineHeight: 1.1,
        }}
      >
        or click to browse
      </div>
      <div
        style={{
          fontFamily: fMono,
          fontSize: 9.5,
          color: N2.text3,
          letterSpacing: 1.8,
          textTransform: 'uppercase',
          marginTop: 14,
        }}
      >
        .csv or .xlsx · max 50MB
      </div>
    </div>
  );
}
