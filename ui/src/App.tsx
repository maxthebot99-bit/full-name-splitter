import { useEffect } from 'react';
import { useStore, viewState } from './store';
import { boot } from './lib/actions';
import { N2Shell } from './components/chrome/N2Shell';
import { N2Topbar } from './components/chrome/N2Topbar';
import { N2Footer } from './components/chrome/N2Footer';
import { N2Sidebar } from './components/chrome/N2Sidebar';
import { N2Workspace } from './components/workspace/N2Workspace';
import { N2CostModal } from './components/chrome/N2CostModal';
import { N2HistoryDrawer } from './components/chrome/N2HistoryDrawer';
import { N2SettingsModal } from './components/chrome/N2SettingsModal';

export function App() {
  const slice = useStore((s) => s[s.active]);
  const view = viewState(slice);

  useEffect(() => {
    boot();
  }, []);

  return (
    <N2Shell>
      <N2Topbar view={view} />
      <div
        style={{
          display: 'grid',
          // Sidebar shrinks down to 280px before the workspace eats into it;
          // workspace gets `min-width: 0` so its inner overflow:auto kicks
          // in instead of pushing the parent grid wider than the viewport.
          gridTemplateColumns: 'minmax(260px, 360px) minmax(0, 1fr)',
          overflow: 'hidden',
        }}
      >
        <N2Sidebar view={view} />
        <N2Workspace view={view} />
      </div>
      <N2Footer view={view} />
      <N2CostModal />
      <N2HistoryDrawer />
      <N2SettingsModal />
    </N2Shell>
  );
}
