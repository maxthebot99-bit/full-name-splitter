import { useStore } from '../store';

export function HeaderStatus() {
  const w = useStore((s) => s.whoami);
  if (!w) return <div className="status status--loading">…</div>;

  const pct = Math.min(100, (w.today_usd / w.cap_usd) * 100);
  const danger = pct > 80;

  return (
    <div className={`status ${danger ? 'status--danger' : ''}`}>
      <div className="status-email">{w.email}</div>
      <div className="status-spend">
        <span className="status-spend-num">${w.today_usd.toFixed(2)}</span>
        <span className="status-spend-sep"> / </span>
        <span className="status-spend-cap">${w.cap_usd.toFixed(2)}</span>
        <span className="status-spend-label"> today</span>
      </div>
      <div className="status-bar">
        <div className="status-bar-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
