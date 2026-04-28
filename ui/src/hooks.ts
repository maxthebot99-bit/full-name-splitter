import { useEffect, useRef, useState } from 'react';

// Animated count-up with cubic ease-out. Picks up from the current displayed
// value on every target change so streaming counters drift smoothly upward
// instead of flashing back to zero.
export function useCountUp(target: number, durMs = 900, enabled = true): number {
  const [val, setVal] = useState(enabled ? 0 : target);
  const displayedRef = useRef(enabled ? 0 : target);

  useEffect(() => {
    if (!enabled) {
      displayedRef.current = target;
      setVal(target);
      return;
    }
    if (displayedRef.current === target) return;

    let raf = 0;
    let start = 0;
    const from = displayedRef.current;
    const to = target;
    const tick = (t: number) => {
      if (!start) start = t;
      const p = Math.min(1, (t - start) / durMs);
      const eased = 1 - Math.pow(1 - p, 3);
      const next = from + (to - from) * eased;
      displayedRef.current = next;
      setVal(next);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durMs, enabled]);
  return val;
}

export function useTick(interval = 1000): number {
  const [t, setT] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setT((x) => x + 1), interval);
    return () => clearInterval(id);
  }, [interval]);
  return t;
}

/**
 * Live forward-projection from the most recent telemetry snapshot.
 *
 * Backend telemetry fires once per Grok batch (~3-14s apart depending on
 * batch_size). Without smoothing the progress bar / cost / token counters
 * sit still between frames and then jump, which feels janky. This hook
 * extrapolates the snapshot forward using rowsPerSecond × elapsed-since-
 * snapshot so the UI moves continuously, then snaps to truth when the
 * next real frame lands.
 *
 * `processed`, `cost`, `tokensIn`, `tokensOut` are projected forward.
 * `rowsPerSecond` itself is unprojected — it's the rate, not a cumulative
 * quantity. `total` is unprojected for the same reason.
 *
 * Caller should clamp at `total` if rendering a percentage (we don't, so
 * the same hook works in N2Telemetry where there's no concept of total).
 */
export function useLiveTelemetry(opts: {
  processed: number;
  total: number;
  rowsPerSecond: number;
  tokensIn: number;
  tokensOut: number;
  costUsd: number;
  lastTelemetryAt: number | undefined;
  // When false (idle / done / error), don't extrapolate — return the
  // snapshot values verbatim.
  active: boolean;
}): {
  processed: number;
  tokensIn: number;
  tokensOut: number;
  costUsd: number;
} {
  // Re-render at 4 Hz so the projected values visibly tick. Faster looks
  // jittery, slower feels sluggish.
  useTick(250);

  const {
    processed, total, rowsPerSecond, tokensIn, tokensOut, costUsd,
    lastTelemetryAt, active,
  } = opts;

  if (!active || !lastTelemetryAt || rowsPerSecond <= 0) {
    return { processed, tokensIn, tokensOut, costUsd };
  }

  const elapsedS = Math.max(0, (Date.now() - lastTelemetryAt) / 1000);
  // Predicted rows-completed since the last frame, capped at remaining.
  const remaining = Math.max(0, total - processed);
  const predictedRows = Math.min(remaining, rowsPerSecond * elapsedS);

  // Per-row averages from the snapshot — used to project token / cost
  // forward at the same rate as rows. If processed is 0 (very first frame
  // before any rows) we can't compute a per-row average; just skip.
  const perRowCost = processed > 0 ? costUsd / processed : 0;
  const perRowTokenIn = processed > 0 ? tokensIn / processed : 0;
  const perRowTokenOut = processed > 0 ? tokensOut / processed : 0;

  return {
    processed: processed + predictedRows,
    tokensIn: tokensIn + predictedRows * perRowTokenIn,
    tokensOut: tokensOut + predictedRows * perRowTokenOut,
    costUsd: costUsd + predictedRows * perRowCost,
  };
}
