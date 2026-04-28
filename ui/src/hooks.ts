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
