import { N2, fSerif, fMono } from '../../../theme';

interface Props {
  label: string;
  sub: string;
  disabled?: boolean;
  variant?: 'accent' | 'rose';
  onClick?: () => void;
}

export function N2CtaPrimary({ label, sub, disabled, variant, onClick }: Props) {
  const c = variant === 'rose' ? N2.rose : N2.accent;
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        background: disabled
          ? 'transparent'
          : `linear-gradient(180deg, ${c}, ${variant === 'rose' ? '#a8746f' : N2.accentSoft})`,
        border: disabled ? `1px solid ${N2.hair2}` : 'none',
        color: disabled ? N2.text3 : '#0a0612',
        padding: '14px 16px',
        cursor: disabled ? 'not-allowed' : 'pointer',
        fontFamily: fSerif,
        fontSize: 18,
        fontWeight: 500,
        letterSpacing: -0.3,
        borderRadius: 2,
        boxShadow: disabled
          ? 'none'
          : `0 0 26px ${c}44, inset 0 1px 0 rgba(255,255,255,0.22), inset 0 -1px 0 rgba(0,0,0,0.15)`,
      }}
    >
      {label}
      <span
        style={{
          display: 'block',
          fontFamily: fMono,
          fontSize: 9.5,
          letterSpacing: 1.5,
          textTransform: 'uppercase',
          marginTop: 3,
          opacity: disabled ? 0.7 : 0.65,
          fontWeight: 500,
        }}
      >
        {sub}
      </span>
    </button>
  );
}
