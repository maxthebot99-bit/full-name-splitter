// Sliding-precision USD formatter. The earlier toFixed(2) collapsed
// any sub-cent run cost (e.g. a 5-row test ≈ $0.0001) into "$0.00", which
// reads as "free" — the real cost was just below the display threshold.
// This formatter keeps roughly 2-3 significant figures across the whole
// range we care about ($0.00001 → $100):
//
//   $1.23      ≥ $1      2 dp
//   $0.12      ≥ $0.10   2 dp
//   $0.011     ≥ $0.01   3 dp
//   $0.0011    ≥ $0.001  4 dp
//   $0.00011   below     5 dp
//   $0.00      exactly 0
//
// Trailing zeros are preserved on purpose — "$0.011" is easier to scan
// than "$0.011" vs "$0.110" with stripped zeros, especially in tight
// monospace columns where alignment matters.
export function fmtCost(n: number): string {
  if (!isFinite(n) || n <= 0) return '$0.00';
  if (n >= 0.1) return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(3)}`;
  if (n >= 0.001) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(5)}`;
}

// Compact integer formatter — `1_234` → `"1.2K"`, `1_234_567` → `"1.2M"`.
// Used by N2Telemetry for tokens-in / tokens-out where the absolute count
// is less interesting than the order of magnitude.
export function fmtK(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return Math.round(n).toString();
}

export function fmtInt(n: number): string {
  return Math.round(n).toLocaleString('en-US');
}
