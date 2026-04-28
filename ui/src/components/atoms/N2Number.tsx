import { useCountUp } from '../../hooks';
import { N2, fSerif } from '../../theme';

interface Props {
  value: number;
  format?: (v: number) => string | number;
  size?: number;
  color?: string;
  animate?: boolean;
  italic?: boolean;
}

export function N2Number({
  value,
  format = (x) => x,
  size = 28,
  color = N2.text,
  animate = true,
  italic = false,
}: Props) {
  const v = useCountUp(value, 1100, animate);
  return (
    <span
      style={{
        fontFamily: fSerif,
        fontSize: size,
        fontWeight: 400,
        color,
        letterSpacing: -size * 0.025,
        lineHeight: 1,
        fontStyle: italic ? 'italic' : 'normal',
        fontVariationSettings: '"opsz" 72, "SOFT" 50',
        fontFeatureSettings: '"ss01", "lnum", "tnum"',
      }}
    >
      {format(v)}
    </span>
  );
}
