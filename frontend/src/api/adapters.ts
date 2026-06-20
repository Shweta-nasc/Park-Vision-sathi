/**
 * Backend → Frontend compatibility layer.
 *
 * The backend speaks `grid_cell_id` / `risk_score`. The planner (and the rest
 * of this app) speaks `h3_id` / `congestion_impact`. Every raw payload from the
 * backend passes through an adapter here, so naming differences never leak into
 * components.
 */
import type {
  ForecastPoint,
  ImpactBand,
  PatrolAllocation,
  PriorityArea,
  RiskLabel,
  SimulationResult,
  SpilloverZone,
  StationSummary,
  StationSummaryItem,
  TrafficContext,
  ViolatorRecord,
  Zone,
} from '@/types/api';

/* ── helpers ─────────────────────────────────────────────────────────── */

export function impactBand(score: number): ImpactBand {
  if (score <= 25) return 'MINIMAL';
  if (score <= 50) return 'MODERATE';
  if (score <= 75) return 'SEVERE';
  return 'CRITICAL';
}

function normalizeRiskLabel(label: string | undefined, score: number): RiskLabel {
  const up = (label ?? '').toUpperCase();
  if (up === 'CRITICAL' || up === 'HIGH' || up === 'MEDIUM' || up === 'LOW') return up as RiskLabel;
  if (score >= 80) return 'CRITICAL';
  if (score >= 67) return 'HIGH';
  if (score >= 34) return 'MEDIUM';
  return 'LOW';
}

const num = (v: unknown, d = 0): number => (typeof v === 'number' && !Number.isNaN(v) ? v : d);

/**
 * Proxy estimate for lane-hours blocked when the backend doesn't provide it.
 * Derived from congestion impact (0-100) scaled to a plausible 0-8 lane-hours/day.
 */
export function estimateLaneHours(score: number, heavyRatio = 0): number {
  return +(((score / 100) * 7 + heavyRatio * 1) ).toFixed(1);
}

/* ── raw backend shapes (loose) ──────────────────────────────────────── */

interface RawZone {
  grid_cell_id: string;
  hour?: number;
  grid_lat?: number;
  grid_lon?: number;
  risk_score?: number;
  risk_label?: string;
  violation_count?: number;
  density?: number;
  road_importance?: number;
  peak_weight?: number;
  repeat_offender?: number;
  validation_trust?: number;
  heavy_vehicle_ratio?: number;
  patrol_probability?: number;
  violator_risk_score?: number;
  expected_cost?: number;
  net_benefit?: number;
  top_junction?: string | null;
  police_station?: string;
}

/* ── adapters ────────────────────────────────────────────────────────── */

export function adaptZone(r: RawZone, hourFallback = 0): Zone {
  const score = num(r.risk_score);
  const heavy = num(r.heavy_vehicle_ratio);
  return {
    h3_id: r.grid_cell_id,
    lat: num(r.grid_lat),
    lon: num(r.grid_lon),
    hour: num(r.hour, hourFallback),
    congestion_impact: score,
    impact_band: impactBand(score),
    risk_label: normalizeRiskLabel(r.risk_label, score),
    violation_count: num(r.violation_count),
    density: num(r.density),
    road_importance: num(r.road_importance),
    peak_weight: num(r.peak_weight, 1),
    repeat_offender: num(r.repeat_offender),
    validation_trust: num(r.validation_trust),
    heavy_vehicle_ratio: heavy,
    estimated_lane_hours_blocked: estimateLaneHours(score, heavy),
    patrol_probability: r.patrol_probability,
    violator_risk_score: r.violator_risk_score,
    expected_cost: r.expected_cost,
    net_benefit: r.net_benefit,
    station: r.police_station,
    junction: r.top_junction ?? null,
  };
}

export function adaptStations(rows: StationSummaryItem[]): StationSummaryItem[] {
  return rows ?? [];
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

export function adaptPriorityArea(r: RawZone & {
  force_needed?: number;
  priority?: string;
  distance_km?: number;
  eta_minutes?: number;
}, hourFallback = 0): PriorityArea {
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

export function adaptForecast(r: any): ForecastPoint {
  return {
    h3_id: r.grid_cell_id,
    hour: num(r.hour),
    predicted_count: num(r.predicted ?? r.avg_predicted),
    max_predicted: r.max_predicted,
    confidence_lower: r.confidence_lower,
    confidence_upper: r.confidence_upper,
  };
}

export function adaptViolator(r: any): ViolatorRecord {
  return {
    h3_id: r.grid_cell_id,
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
