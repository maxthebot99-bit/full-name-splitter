import { useEffect, useMemo, useRef, useState } from 'react';
import { N2 } from '../../theme';
import { sparkPath } from '../../utils/sparkPath';

interface Props {
  values: number[];
  w?: number;
  h?: number;
  color?: string;
  live?: boolean;
  draw?: boolean;
}

export function N2Spark({
  values,
  w = 360,
  h = 56,
  color = N2.accent,
  live = true,
  draw = true,
}: Props) {
  const { line, area } = sparkPath(values, w, h, 3);
  const gid = useMemo(() => 'n2' + Math.random().toString(36).slice(2, 8), []);
  const pathRef = useRef<SVGPathElement | null>(null);
  const [len, setLen] = useState(0);
  useEffect(() => {
    if (pathRef.current) setLen(pathRef.current.getTotalLength());
  }, [values]);
  const last = values[values.length - 1] ?? 0;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const lastY = 3 + (h - 6) * (1 - (last - min) / (max - min || 1));
  return (
    <svg width={w} height={h} style={{ display: 'block', overflow: 'visible' }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path
        d={area}
        fill={`url(#${gid})`}
        style={{
          opacity: draw ? 1 : 0,
          transition: 'opacity 0.8s ease-out 0.6s',
        }}
      />
      <path
        ref={pathRef}
        d={line}
        fill="none"
        stroke={color}
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeDasharray={draw ? `${len} ${len}` : undefined}
        strokeDashoffset={draw ? 0 : len}
        style={{ transition: 'stroke-dashoffset 1.4s cubic-bezier(0.4,0,0.2,1)' }}
      />
      {live && (
        <>
          <circle cx={w - 3} cy={lastY} r="2.5" fill={color} />
          <circle cx={w - 3} cy={lastY} r="6" fill={color} opacity="0.35">
            <animate attributeName="r" values="3;12;3" dur="2s" repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.5;0;0.5" dur="2s" repeatCount="indefinite" />
          </circle>
        </>
      )}
    </svg>
  );
}
