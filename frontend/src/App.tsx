import { useEffect, useState } from 'react';
import { useAppState } from '@/state/AppState';
import { MapOverlayProvider } from '@/state/MapOverlay';
import { useStations } from '@/hooks/queries';
import { NavRail } from './components/NavRail';
import { TopHeader } from './components/TopHeader';
import { MapView } from './components/MapView';
import { RightPanel } from './components/RightPanel';
import { LayerToggle } from './components/LayerToggle';
import { MapLegend } from './components/MapLegend';
import { PriorityDock } from './components/PriorityStrip';
import { StationSelect } from './components/StationSelect';
import { ErrorBoundary } from './components/ErrorBoundary';

export default function App() {
  const { station, setStation, panelOpen, setPanelOpen } = useAppState();
  const { data: stations } = useStations();
  const [switching, setSwitching] = useState(false);

  /* Auto-select the first station as soon as the list arrives */
  useEffect(() => {
    if (!station && stations && stations.length > 0) setStation(stations[0]);
  }, [station, stations, setStation]);

  /* Initial full-screen station picker (also handles loading/error states). */
  if (!station) return <StationSelect />;

  return (
    <MapOverlayProvider>
      <div className={`app-shell ${panelOpen ? 'panel-visible' : ''}`}>
        {/* Full-bleed map base */}
        <div className="map-stage">
          <ErrorBoundary>
            <MapView />
          </ErrorBoundary>
        </div>

        {/* Floating control-center chrome */}
        <TopHeader onSwitchStation={() => setSwitching(true)} />
        <NavRail panelOpen={panelOpen} onTogglePanel={setPanelOpen} />
        <div className="layer-dock">
          <LayerToggle />
        </div>
        <MapLegend />
        <PriorityDock />

        {panelOpen && <RightPanel onClose={() => setPanelOpen(false)} />}

        {/* Re-openable station switcher modal */}
        {switching && <StationSelect onClose={() => setSwitching(false)} />}
      </div>
    </MapOverlayProvider>
  );
}
