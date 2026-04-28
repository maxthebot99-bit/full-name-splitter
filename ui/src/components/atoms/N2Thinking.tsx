import { useEffect, useState } from 'react';
import { N2, fSerif, fMono } from '../../theme';

// Clay-style "AI thinking" strip — rotates through a list of action verbs
// every 1.6s with three pulse dots after the word. Used while a single
// row is being rerun (▶) and as the live phrase during a full run.

interface Props {
  phrases?: string[];
  // Optional suffix string shown in muted mono after the rotating phrase.
  // Used for the row number being processed: "reading row 042…".
  detail?: string;
  // 'sm' = inline size for sidebar; 'md' = larger for hero placement.
  size?: 'sm' | 'md';
  color?: string;
}

const DEFAULT_PHRASES_COMPANY = [
  'reading',
  'asking grok',
  'stripping suffixes',
  'normalizing case',
  'reconciling',
  'checking stylization',
];

export const PHRASES_COMPANY = DEFAULT_PHRASES_COMPANY;
export const PHRASES_NAME = [
  'reading',
  'asking grok',
  'parsing',
  'normalizing case',
  'expanding initials',
  'reconciling',
];

export function N2Thinking({
  phrases = DEFAULT_PHRASES_COMPANY,
  detail,
  size = 'sm',
  color = N2.accent,
}: Props) {
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setIdx((i) => (i + 1) % phrases.length);
    }, 1600);
    return () => clearInterval(id);
  }, [phrases.length]);

  const phrase = phrases[idx];
  const fontSize = size === 'md' ? 22 : 17;

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: 'inline-flex',
        alignItems: 'baseline',
        gap: 8,
        fontFamily: fSerif,
        fontStyle: 'italic',
        fontSize,
        color,
        letterSpacing: -0.3,
        lineHeight: 1.2,
        fontVariationSettings: '"opsz" 60, "SOFT" 50',
      }}
    >
      <span>{phrase}</span>
      <PulseDots color={color} />
      {detail && (
        <span
          style={{
            fontFamily: fMono,
            fontSize: size === 'md' ? 11 : 9.5,
            fontStyle: 'normal',
            color: N2.text3,
            letterSpacing: 1.2,
            textTransform: 'uppercase',
            marginLeft: 4,
          }}
        >
          {detail}
        </span>
      )}
    </div>
  );
}

function PulseDots({ color }: { color: string }) {
  const dot = (delay: string) => ({
    width: 4,
    height: 4,
    borderRadius: 4,
    background: color,
    boxShadow: `0 0 6px ${color}`,
    animation: `n2Dot 1.2s ease-in-out ${delay} infinite`,
    display: 'inline-block',
  });
  return (
    <span
      aria-hidden
      style={{ display: 'inline-flex', gap: 3, alignSelf: 'center' }}
    >
      <span style={dot('0s')} />
      <span style={dot('0.15s')} />
      <span style={dot('0.3s')} />
    </span>
  );
}
