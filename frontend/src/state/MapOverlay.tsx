/**
 * Transient map overlays that panels push and the map renders:
 * simulation allocations/spillover and a patrol route target.
 */
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import type { SimulationResult, Zone, PriorityArea } from '@/types/api';

interface MapOverlayValue {
  simResult: SimulationResult | null;
  setSimResult: (r: SimulationResult | null) => void;
  routeTarget: (Zone | PriorityArea) | null;
  setRouteTarget: (z: (Zone | PriorityArea) | null) => void;
}

const Ctx = createContext<MapOverlayValue | null>(null);

export function MapOverlayProvider({ children }: { children: ReactNode }) {
  const [simResult, setSimResult] = useState<SimulationResult | null>(null);
  const [routeTarget, setRouteTarget] = useState<(Zone | PriorityArea) | null>(null);
  const value = useMemo(
    () => ({ simResult, setSimResult, routeTarget, setRouteTarget }),
    [simResult, routeTarget],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useMapOverlay(): MapOverlayValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useMapOverlay must be used within MapOverlayProvider');
  return v;
}
