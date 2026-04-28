// Smooth sparkline path + matching area-fill path. Light catmull-rom-ish
// curve so the line reads as "live" without polyline jitter.
export function sparkPath(
  values: number[],
  w: number,
  h: number,
  pad = 2,
): { line: string; area: string } {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = (w - pad * 2) / Math.max(1, values.length - 1);
  const pts = values.map(
    (v, i): [number, number] => [
      pad + i * stepX,
      pad + (h - pad * 2) * (1 - (v - min) / range),
    ],
  );
  let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) {
    const [x1, y1] = pts[i - 1];
    const [x2, y2] = pts[i];
    const cx = (x1 + x2) / 2;
    d += ` C ${cx.toFixed(1)} ${y1.toFixed(1)}, ${cx.toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  }
  const area =
    d +
    ` L ${pts[pts.length - 1][0].toFixed(1)} ${h} L ${pts[0][0].toFixed(1)} ${h} Z`;
  return { line: d, area };
}
