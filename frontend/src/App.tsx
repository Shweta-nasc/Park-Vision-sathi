import { useEffect } from 'react';
import { useAppState } from '@/state/AppState';
import { MapOverlayProvider } from '@/state/MapOverlay';
import { useStations } from '@/hooks/queries';
import { NavRail } from './components/NavRail';
import { TopHeader } from './components/TopHeader';
import { MapView } from './components/MapView';
import { RightPanel } from './components/RightPanel';
import { ErrorBoundary } from './components/ErrorBoundary';

export default function App() {
  const { station, setStation, panelOpen, setPanelOpen } = useAppState();
  const { data: stations, isLoading, isError } = useStations();

  /* Auto-select the first station as soon as the list arrives */
  useEffect(() => {
    if (!station && stations && stations.length > 0) {
      setStation(stations[0]);
    }
  }, [station, stations, setStation]);

  /* Show a brief loading screen while the station list is being fetched */
  if (!station) {
    return (
      <div className="station-screen">
        <div className="station-screen-bg" />
        <div className="station-screen-content" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16 }}>
          <div className="brand-block">
            <div className="brand-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 22s-8-4.5-8-11.8A8 8 0 0 1 12 2a8 8 0 0 1 8 8.2c0 7.3-8 11.8-8 11.8z" />
                <circle cx="12" cy="10" r="3" />
              </svg>
            </div>
            <h1 className="brand-title">ParkVisionSaathi</h1>
            <p className="brand-subtitle">Patrol Operations Dashboard</p>
          </div>
          {isLoading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
              <div className="loading-spinner" />
              <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading station data…</span>
            </div>
          )}
          {isError && (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 24 }}>
              <p style={{ fontSize: 14, marginBottom: 8 }}>Could not load stations</p>
              <p style={{ fontSize: 12 }}>Check that the API is running on port 8000</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <MapOverlayProvider>
      <div className={`app-shell ${panelOpen ? 'panel-visible' : ''}`}>
        <NavRail panelOpen={panelOpen} onTogglePanel={setPanelOpen} />
        <TopHeader />
        <main className="center-workspace">
          <ErrorBoundary>
            <MapView />
          </ErrorBoundary>
        </main>
        {panelOpen && (
          <RightPanel onClose={() => setPanelOpen(false)} />
        )}
      </div>
    </MapOverlayProvider>
  );
}

