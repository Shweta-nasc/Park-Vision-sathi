/**
 * Lightweight global state via Context. Holds cross-cutting UI state
 * (selected station, hour, active map layer, selected zone, right-panel tab).
 * Server data lives in React Query, not here.
 */
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import type { MapLayer, PriorityArea, StationSummaryItem, Zone } from '@/types/api';

export type PanelTab = 'details' | 'sim' | 'forecast' | 'game' | 'chat';

interface AppStateValue {
  station: StationSummaryItem | null;
  setStation: (s: StationSummaryItem | null) => void;
  hour: number;
  setHour: (h: number) => void;
  layer: MapLayer;
  setLayer: (l: MapLayer) => void;
  selectedZone: (Zone | PriorityArea) | null;
  setSelectedZone: (z: (Zone | PriorityArea) | null) => void;
  panel: PanelTab;
  setPanel: (p: PanelTab) => void;
}

const Ctx = createContext<AppStateValue | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [station, setStation] = useState<StationSummaryItem | null>(null);
  const [hour, setHour] = useState(9);
  const [layer, setLayer] = useState<MapLayer>('violation_density');
  const [selectedZone, setSelectedZone] = useState<(Zone | PriorityArea) | null>(null);
  const [panel, setPanel] = useState<PanelTab>('details');

  const value = useMemo<AppStateValue>(
    () => ({ station, setStation, hour, setHour, layer, setLayer, selectedZone, setSelectedZone, panel, setPanel }),
    [station, hour, layer, selectedZone, panel],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppState(): AppStateValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAppState must be used within AppStateProvider');
  return v;
}
