/**
 * React Query hooks — caching, deduping, background refetch, and loading/error
 * state for every backend resource. Query keys include the params that affect
 * the result so caches invalidate correctly on hour/layer/station change.
 */
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '@/api/endpoints';
import { zoneLabel } from '@/utils/format';
import type { MapLayer, SimulationRequest } from '@/types/api';

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, staleTime: 30_000, retry: 1 });
}

export function useStations() {
  return useQuery({ queryKey: ['stations'], queryFn: api.stations, staleTime: Infinity });
}

/** H3 id → readable place name, built from the hotspot zone universe. */
export function useZoneNames() {
  return useQuery({
    queryKey: ['zoneIndex'],
    queryFn: () => api.zoneIndex(),
    staleTime: Infinity,
    select: (zones) => {
      const m = new Map<string, string>();
      for (const z of zones) m.set(z.h3_id, zoneLabel(z));
      return m;
    },
  });
}

export function useStationSummary(station: string | null, hour: number) {
  return useQuery({
    queryKey: ['stationSummary', station, hour],
    queryFn: () => api.stationSummary(station!, hour),
    enabled: !!station,
  });
}

export function usePriorityAreas(station: string | null, hour: number) {
  return useQuery({
    queryKey: ['priorityAreas', station, hour],
    queryFn: () => api.priorityAreas(station!, hour),
    enabled: !!station,
  });
}

export function useHeatmap(hour: number, layer: MapLayer, enabled: boolean) {
  return useQuery({
    queryKey: ['heatmap', hour, layer],
    queryFn: () => api.heatmap(hour, layer),
    enabled,
    staleTime: 60_000,
  });
}

export function useTopZones(hour: number, enabled: boolean) {
  return useQuery({
    queryKey: ['topZones', hour],
    queryFn: () => api.topZones(hour),
    enabled,
    staleTime: 60_000,
  });
}

export function useForecastTopZones(hour: number, enabled: boolean) {
  return useQuery({
    queryKey: ['forecastTop', hour],
    queryFn: () => api.forecastTopZones(hour),
    enabled,
  });
}

export function useForecastAccuracy() {
  return useQuery({ queryKey: ['forecastAccuracy'], queryFn: api.forecastAccuracy, staleTime: Infinity });
}

export function useForecastExplanations(enabled: boolean) {
  return useQuery({
    queryKey: ['forecastExplanations'],
    queryFn: () => api.forecastExplanations(),
    enabled,
    staleTime: Infinity,
  });
}

export function useViolators(hour: number, enabled: boolean) {
  return useQuery({
    queryKey: ['violators', hour],
    queryFn: () => api.violators(hour),
    enabled,
  });
}

export function useSpilloverArrows(enabled: boolean) {
  return useQuery({
    queryKey: ['spilloverArrows'],
    queryFn: api.spilloverArrows,
    enabled,
    staleTime: Infinity,
  });
}

export function useAgentReport(enabled: boolean) {
  return useQuery({
    queryKey: ['agentReport'],
    queryFn: () => api.agentReport(),
    enabled,
    staleTime: Infinity,
  });
}

/** The density≠impact proof (Task 13): scatter points + non-circular trust ρ. */
export function useValidationProof(enabled: boolean) {
  return useQuery({
    queryKey: ['validationProof'],
    queryFn: () => api.validationProof(),
    enabled,
    staleTime: Infinity,
  });
}

export function useSimulation() {
  return useMutation({ mutationFn: (req: SimulationRequest) => api.simulate(req) });
}

export function useExplain() {
  return useMutation({ mutationFn: ({ h3_id, hour }: { h3_id: string; hour: number }) => api.explain(h3_id, hour) });
}
