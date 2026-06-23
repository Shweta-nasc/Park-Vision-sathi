/**
 * Backend → Frontend compatibility layer.
 *
 * The backend speaks `grid_cell_id`/`grid_lat`/`grid_lon` and returns BOTH a
 * `risk_score` (enforcement priority) and a `congestion_impact` (CIS). Adapters
 * translate field names and keep the two scores distinct so components never
 * conflate them.
 */
import type {
  CongestionComponents,
  ForecastPoint,
  ImpactBand,
  PriorityArea,
  RiskLabel,
  SimulationResult,
  SpilloverZone,
  StationSummary,
  TrafficContext,
  ViolatorRecord,
  Zone,
  PatrolAllocation,
} from '@/types/api';

/* ── helpers ─────────────────────────────────────────────────────────── */

/** CIS band thresholds (match the backend's _band). */
export function impactBand(score: number): ImpactBand {
  if (score <= 25) return 'MINIMAL';
  if (score <= 50) return 'MODERATE';
  if (score <= 75) return 'SEVERE';
  return 'CRITICAL';
}

/** Enforcement risk label (match the backend's _risk_label). */
export function riskLabel(label: string | undefined, score: number): RiskLabel {
  const up = (label ?? '').toUpperCase();
  if (up === 'CRITICAL' || up === 'HIGH' || up === 'MEDIUM' || up === 'LOW') return up as RiskLabel;
  if (score >= 80) return 'CRITICAL';
  if (score >= 67) return 'HIGH';
  if (score >= 34) return 'MEDIUM';
  return 'LOW';
}

const num = (v: unknown, d = 0): number => (typeof v === 'number' && !Number.isNaN(v) ? v : d);

/** Fallback lane-hours estimate when the backend omits it. */
export function estimateLaneHours(score: number, heavyRatio = 0): number {
  return +(((score / 100) * 7 + heavyRatio).toFixed(1));
}

/* ── raw backend shapes (loose) ──────────────────────────────────────── */

interface RawZone {
  grid_cell_id: string;
  h3_id?: string;
  hour?: number;
  grid_lat?: number;
  grid_lon?: number;
  risk_score?: number;
  risk_label?: string;
  congestion_impact?: number;
  impact_band?: string;
  calibrated_score?: number;
  violation_count?: number;
  density?: number;
  road_importance?: number;
  peak_weight?: number;
  repeat_offender?: number;
  validation_trust?: number;
  heavy_vehicle_ratio?: number;
  estimated_lane_hours_blocked?: number;
  patrol_probability?: number;
  violator_risk_score?: number;
  expected_cost?: number;
  net_benefit?: number;
  top_junction?: string | null;
  top_violation?: string | null;
  police_station?: string;
  station?: string;
  travel_time_ratio?: number | null;
  agent_status?: string | null;
  agent_reasoning?: string | null;
}

/* ── adapters ────────────────────────────────────────────────────────── */

/** Operational zone object (from /risk, /risk/top_zones, /game/*). */
export function adaptZone(r: RawZone, hourFallback = 0): Zone {
  const risk = num(r.risk_score);
  const cis = num(r.congestion_impact);
  const heavy = num(r.heavy_vehicle_ratio);
  return {
    h3_id: r.grid_cell_id ?? r.h3_id ?? '',
    lat: num(r.grid_lat),
    lon: num(r.grid_lon),
    hour: num(r.hour, hourFallback),
    risk_score: risk,
    risk_label: riskLabel(r.risk_label, risk),
    congestion_impact: cis,
    impact_band: (r.impact_band as ImpactBand) ?? impactBand(cis),
    calibrated_score: r.calibrated_score,
    violation_count: num(r.violation_count),
    density: num(r.density),
    road_importance: num(r.road_importance),
    peak_weight: num(r.peak_weight, 1),
    repeat_offender: num(r.repeat_offender),
    validation_trust: num(r.validation_trust),
    heavy_vehicle_ratio: heavy,
    estimated_lane_hours_blocked: num(r.estimated_lane_hours_blocked, estimateLaneHours(cis, heavy)),
    mappls_ratio: r.travel_time_ratio ?? null,
    patrol_probability: r.patrol_probability,
    violator_risk_score: r.violator_risk_score,
    expected_cost: r.expected_cost,
    net_benefit: r.net_benefit,
    station: r.police_station ?? r.station,
    junction: r.top_junction ?? null,
    top_violation: r.top_violation ?? null,
    agent_status: r.agent_status ?? null,
    agent_reasoning: r.agent_reasoning ?? null,
  };
}

/**
 * /risk/{zone_id} returns a CongestionBreakdown (a different shape from the
 * operational zone). This maps it into a Zone enrichment so the detail panel
 * can render the REAL CIS components, lane-hours, and calibration.
 */
interface RawBreakdown {
  zone_id?: string;
  h3_id?: string;
  lat?: number;
  lon?: number;
  congestion_impact?: number;
  impact_band?: string;
  components?: CongestionComponents;
  weights?: Record<string, number>;
  estimated_lane_hours_blocked?: number;
  total_records?: number;
  top_violations?: string[];
  station?: string;
  junction?: string | null;
  mappls_travel_time_ratio?: number | null;
  calibrated_impact?: number | null;
  time_regime?: string | null;
}

export function adaptBreakdown(r: RawBreakdown): Partial<Zone> {
  const cis = num(r.congestion_impact);
  return {
    h3_id: r.h3_id ?? r.zone_id,
    lat: r.lat,
    lon: r.lon,
    congestion_impact: cis,
    impact_band: (r.impact_band as ImpactBand) ?? impactBand(cis),
    components: r.components,
    weights: r.weights ?? undefined,
    estimated_lane_hours_blocked: num(r.estimated_lane_hours_blocked),
    violation_count: num(r.total_records),
    top_violations: r.top_violations ?? [],
    station: r.station,
    junction: r.junction ?? null,
    mappls_ratio: r.mappls_travel_time_ratio ?? null,
    calibrated_score: r.calibrated_impact ?? undefined,
    time_regime: r.time_regime ?? null,
  };
}

export function adaptStationSummary(r: any): StationSummary {
  return {
    station: r.station,
    hour: num(r.hour),
    total_zones: num(r.total_zones),
    total_violations: num(r.total_violations),
    high_risk_zones: num(r.high_risk_zones),
  };
}

export function adaptPriorityArea(
  r: RawZone & { force_needed?: number; priority?: string; distance_km?: number; eta_minutes?: number },
  hourFallback = 0,
): PriorityArea {
  const base = adaptZone(r, hourFallback);
  const pr = (r.priority as PriorityArea['priority']) ?? 'Low';
  return {
    ...base,
    force_needed: num(r.force_needed, 1),
    priority: pr === 'High' || pr === 'Medium' || pr === 'Low' ? pr : 'Low',
    distance_km: num(r.distance_km),
    eta_minutes: num(r.eta_minutes),
    top_junction: r.top_junction ?? null,
  };
}

/** /forecast/top_risk_zones | /forecast/zones */
export function adaptForecast(r: any): ForecastPoint {
  const cnt = num(r.predicted_count);
  return {
    h3_id: r.h3_id ?? r.zone_id ?? '',
    lat: num(r.lat),
    lon: num(r.lon),
    predicted_count: cnt,
    predicted_risk: num(r.predicted_risk),
    predicted_band: (r.predicted_band as ImpactBand) ?? impactBand(num(r.predicted_risk)),
    confidence_lower: r.confidence_lower,
    confidence_upper: r.confidence_upper,
    is_proxy: !!r.is_proxy,
  };
}

/** /game/violator_adaptation returns full zone objects. */
export function adaptViolator(r: any): ViolatorRecord {
  return {
    h3_id: r.grid_cell_id ?? r.h3_id,
    hour: num(r.hour),
    lat: num(r.grid_lat),
    lon: num(r.grid_lon),
    violator_risk_score: num(r.violator_risk_score),
    expected_cost: num(r.expected_cost),
    net_benefit: num(r.net_benefit),
  };
}

export function adaptTraffic(r: any): TrafficContext {
  return {
    h3_id: r.zone_id,
    road_name: r.road_name,
    road_type: r.road_type,
    travel_time_peak_min: r.travel_time_peak_min,
    travel_time_offpeak_min: r.travel_time_offpeak_min,
    travel_time_ratio: r.travel_time_ratio,
    nearby_pois: r.nearby_pois ?? [],
  };
}

export function adaptSimulation(r: any): SimulationResult {
  return {
    num_teams: num(r.num_teams),
    hour: num(r.hour),
    strategy: r.strategy ?? 'stackelberg',
    allocations: (r.assignments ?? []).map(
      (a: any): PatrolAllocation => ({
        team_id: num(a.team_id),
        h3_id: a.grid_cell_id,
        lat: num(a.grid_lat),
        lon: num(a.grid_lon),
        priority_rank: num(a.priority_rank),
        patrol_probability: num(a.patrol_probability),
        congestion_impact: num(a.risk_score),
      }),
    ),
    uncovered_zones: (r.uncovered_high_risk ?? []).map((u: any) => ({
      h3_id: u.grid_cell_id,
      lat: num(u.grid_lat),
      lon: num(u.grid_lon),
      congestion_impact: num(u.risk_score),
    })),
    covered_impact_pct: num(r.coverage_pct),
    total_impact_covered: num(r.total_risk_covered),
    spillover_zones: (r.spillover_zones ?? []).map(
      (s: any): SpilloverZone => ({
        h3_id: s.grid_cell_id,
        lat: num(s.grid_lat),
        lon: num(s.grid_lon),
        original_impact: num(s.original_risk),
        adjusted_impact: num(s.adjusted_risk),
        change_pct: num(s.risk_change_pct),
        spillover_type: s.spillover_type ?? '',
      }),
    ),
  };
}
