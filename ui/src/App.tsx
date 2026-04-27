import { useEffect } from 'react';
import { whoami } from './api';
import { useStore } from './store';
import type { Kind } from './types';
import { CleanerPane } from './components/CleanerPane';
import { HeaderStatus } from './components/HeaderStatus';

export function App() {
  const active = useStore((s) => s.active);
  const setActive = useStore((s) => s.setActive);
  const setWhoami = useStore((s) => s.setWhoami);

  useEffect(() => {
    let mounted = true;
    whoami()
      .then((w) => {
        if (mounted) setWhoami(w);
      })
      .catch((err) => {
        console.warn('whoami failed:', err);
      });
    const t = setInterval(() => {
      whoami()
        .then((w) => mounted && setWhoami(w))
        .catch(() => {});
    }, 30_000);
    return () => {
      mounted = false;
      clearInterval(t);
    };
  }, [setWhoami]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">✨</span>
          <span className="brand-text">cleaners-hub</span>
        </div>
        <nav className="tabs">
          <TabButton current={active} kind="company" onClick={setActive}>
            Companies
          </TabButton>
          <TabButton current={active} kind="name" onClick={setActive}>
            First Names
          </TabButton>
        </nav>
        <HeaderStatus />
      </header>
      <main className="pane">
        {/* Both panes are always mounted so a run on one tab keeps streaming
            while the user looks at the other. */}
        <div style={{ display: active === 'company' ? 'block' : 'none' }}>
          <CleanerPane kind="company" />
        </div>
        <div style={{ display: active === 'name' ? 'block' : 'none' }}>
          <CleanerPane kind="name" />
        </div>
      </main>
    </div>
  );
}

function TabButton({
  current,
  kind,
  onClick,
  children,
}: {
  current: Kind;
  kind: Kind;
  onClick: (k: Kind) => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={`tab ${current === kind ? 'tab--active' : ''}`}
      onClick={() => onClick(kind)}
    >
      {children}
    </button>
  );
}
