/**
 * Typed endpoint functions. Each maps a backend route to a planner-aligned
 * model via the adapters. This is the single place that knows backend paths.
 */
import { http } from './client';
import {
  adaptForecast,
  adaptPriorityArea,
  adaptSimulation,
  adaptStationSummary,
  adaptTraffic,
  adaptViolator,
  adaptZone,
} from './adapters';
import type {
  ForecastPoint,
  HeatmapPoint,
  HeatmapResponse,
  MapLayer,
  PatrolAllocation,
  PriorityArea,
  SimulationRequest,
  SimulationResult,
  SpilloverArrow,
  StationSummary,
  StationSummaryItem,
  TrafficContext,
  ViolatorRecord,
  Zone,
} from '@/types/api';

/** Map planner layer name → backend heatmap `type` param. */
const LAYER_TO_BACKEND: Record<MapLayer, string> = {
  violation_density: 'raw',
  congestion_risk: 'risk',
  spillover: 'spillover',
};

export const api = {
  health: () => http.get<{ status: string }>('/health'),

  stations: () => http.get<StationSummaryItem[]>('/stations'),

  stationSummary: (station: string, hour: number): Promise<StationSummary> =>
    http
      .get<any>(`/stations/${encodeURIComponent(station)}/summary`, { hour })
      .then(adaptStationSummary),

  priorityAreas: (station: string, hour: number, limit = 12): Promise<PriorityArea[]> =>
    http
      .get<any[]>(`/stations/${encodeURIComponent(station)}/priority_areas`, { hour, limit })
      .then((rows) => rows.map((r) => adaptPriorityArea(r, hour))),

  heatmap: async (hour: number, layer: MapLayer): Promise<HeatmapResponse> => {
    const raw = await http.get<any>('/heatmap', { hour, type: LAYER_TO_BACKEND[layer] });
    const points: HeatmapPoint[] = (raw.points ?? []).map((p: any) => ({
      lat: p.lat,
      lon: p.lon,
      intensity: p.intensity,
    }));
    return {
      hour: raw.hour ?? hour,
      layer,
      points,
      min_intensity: raw.min_intensity ?? 0,
      max_intensity: raw.max_intensity ?? 0,
    };
  },

  topZones: (hour: number, n = 15): Promise<Zone[]> =>
    http.get<any[]>('/risk/top_zones', { hour, n }).then((rows) => rows.map((r) => adaptZone(r, hour))),

  zoneDetail: (h3_id: string, hour: number): Promise<Zone | null> =>
    http.get<any>(`/risk/${encodeURIComponent(h3_id)}`, { hour }).then((r) => {
      if (!r || r.error) return null;
      return adaptZone(r, hour);
    }),

  forecastTopZones: (hour: number, n = 12): Promise<ForecastPoint[]> =>
    http.get<any>('/forecast/top_risk_zones', { hour, n }).then((rows) =>
      Array.isArray(rows) ? rows.map(adaptForecast) : [],
    ),

  forecastAccuracy: () =>
    http.get<any[]>('/forecast/accuracy').then((r) => (Array.isArray(r) ? r[0] : null)),

  stackelberg: (hour: number, limit = 50): Promise<PatrolAllocation[]> =>
    http.get<any[]>('/game/stackelberg_strategy', { hour, limit }).then((rows) =>
      rows.map((r, i) => ({
        team_id: i + 1,
        h3_id: r.grid_cell_id,
        lat: r.grid_lat,
        lon: r.grid_lon,
        priority_rank: i + 1,
        patrol_probability: r.patrol_probability ?? 0,
        congestion_impact: r.risk_score ?? 0,
      })),
    ),

  violators: (hour: number, limit = 20): Promise<ViolatorRecord[]> =>
    http.get<any[]>('/game/violator_adaptation', { hour, limit }).then((rows) => rows.map(adaptViolator)),

  spilloverArrows: (): Promise<SpilloverArrow[]> =>
    http.get<any>('/game/spillover_arrows').then((d) => d?.arrows ?? []),

  simulate: (req: SimulationRequest): Promise<SimulationResult> =>
    http.post<any>('/simulate', { strategy: 'stackelberg', ...req }).then(adaptSimulation),

  explain: (h3_id: string, hour: number) =>
    http.post<any>('/explain', { zone_id: h3_id, hour }).then((r) => ({
      h3_id: r.zone_id,
      explanation: r.explanation,
      is_cached: !!r.is_cached,
      source: r.source ?? 'fallback',
    })),

  traffic: (h3_id: string): Promise<TrafficContext> =>
    http.get<any>(`/traffic/${encodeURIComponent(h3_id)}`).then(adaptTraffic),
};
