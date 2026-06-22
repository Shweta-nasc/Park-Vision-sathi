/**
 * Typed endpoint functions — the single place that knows backend paths.
 * Every route here is verified against API_DOCS.md / the live backend.
 */
import { http } from './client';
import {
  adaptBreakdown,
  adaptForecast,
  adaptPriorityArea,
  adaptSimulation,
  adaptStationSummary,
  adaptTraffic,
  adaptViolator,
  adaptZone,
} from './adapters';
import type {
  AgentReport,
  ForecastAccuracy,
  ForecastExplanations,
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

/** Planner layer name → backend heatmap `type` param. */
const LAYER_TO_BACKEND: Record<MapLayer, string> = {
  violation_density: 'raw',
  congestion_risk: 'risk',
  spillover: 'spillover',
};

export const api = {
  health: () => http.get<{ status: string; zones_loaded?: number }>('/health'),

  stations: () => http.get<StationSummaryItem[]>('/stations'),

  stationSummary: (station: string, hour: number): Promise<StationSummary> =>
    http.get<any>(`/stations/${encodeURIComponent(station)}/summary`, { hour }).then(adaptStationSummary),

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

  /** Whole hotspot universe (zone objects carry station/junction) — used to
   *  resolve H3 ids to readable place names across panels. */
  zoneIndex: (): Promise<Zone[]> =>
    http.get<any[]>('/risk', { limit: 200 }).then((rows) => rows.map((r) => adaptZone(r))),

  /** /risk/{id} → CIS breakdown (partial Zone enrichment). */
  zoneDetail: (h3_id: string, hour: number): Promise<Partial<Zone> | null> =>
    http.get<any>(`/risk/${encodeURIComponent(h3_id)}`, { hour }).then((r) => {
      if (!r || r.error || r.detail) return null;
      return adaptBreakdown(r);
    }),

  forecastTopZones: (hour: number, n = 12): Promise<ForecastPoint[]> =>
    http
      .get<any>('/forecast/top_risk_zones', { hour, n })
      .then((rows) => (Array.isArray(rows) ? rows.map(adaptForecast) : [])),

  forecastAccuracy: (): Promise<ForecastAccuracy> => http.get<ForecastAccuracy>('/forecast/accuracy'),

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

  /** /agent/validation-report → { summary, zones[], calibration_run }. */
  agentReport: (): Promise<AgentReport> =>
    http
      .get<any>('/agent/validation-report')
      .then((r) => ({
        available: !!(r && r.summary),
        summary: r?.summary ?? null,
        zones: Array.isArray(r?.zones) ? r.zones : [],
        calibration_run: r?.calibration_run ?? null,
      }))
      .catch(() => ({ available: false, summary: null, zones: [], calibration_run: null })),

  /** /forecast/explanations → per-zone SHAP top contributors (Task 9). */
  forecastExplanations: (): Promise<ForecastExplanations> =>
    http
      .get<any>('/forecast/explanations')
      .then((r) => ({
        available: !!(r && r.available),
        feature_names: Array.isArray(r?.feature_names) ? r.feature_names : undefined,
        top_k: r?.top_k,
        note: r?.note,
        zones: Array.isArray(r?.zones) ? r.zones : [],
      }))
      .catch(() => ({ available: false, zones: [] })),
};
