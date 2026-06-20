/**
 * Planner-aligned frontend domain models.
 *
 * The execution planner is the SOURCE OF TRUTH. It uses `h3_id` and
 * `congestion_impact`. The current backend uses `grid_cell_id` and
 * `risk_score`. The adapters in `api/adapters.ts` translate raw backend
 * payloads into these models so the rest of the app speaks the planner's
 * vocabulary regardless of backend naming.
 */

export type ImpactBand = 'MINIMAL' | 'MODERATE' | 'SEVERE' | 'CRITICAL';
export type RiskLabel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type MapLayer = 'violation_density' | 'congestion_risk' | 'spillover';

/** A single zone with its congestion-impact profile. */
export interface Zone {
  h3_id: string; // planner name (maps from backend grid_cell_id)
  lat: number;
  lon: number;
  hour: number;
  congestion_impact: number; // planner name (maps from backend risk_score)
  impact_band: ImpactBand;
  risk_label: RiskLabel;
  violation_count: number;
  // Component breakdown
  density: number;
  road_importance: number;
  peak_weight: number;
  repeat_offender: number;
  validation_trust: number;
  heavy_vehicle_ratio: number;
  estimated_lane_hours_blocked: number;
  // Game-theory enrichment (optional, from joins)
  patrol_probability?: number;
  violator_risk_score?: number;
  expected_cost?: number;
  net_benefit?: number;
  // Station context
  station?: string;
  junction?: string | null;
}

export interface HeatmapPoint {
  lat: number;
  lon: number;
  intensity: number;
}

export interface HeatmapResponse {
  hour: number | null;
  layer: MapLayer;
  points: HeatmapPoint[];
  min_intensity: number;
  max_intensity: number;
}

export interface StationSummaryItem {
  name: string;
  zone_count: number;
  total_violations: number;
  lat: number;
  lon: number;
}

export interface PriorityArea extends Zone {
  force_needed: number;
  priority: 'High' | 'Medium' | 'Low';
  distance_km: number;
  eta_minutes: number;
  top_junction?: string | null;
}

export interface StationSummary {
  station: string;
  hour: number;
  total_zones: number;
  total_violations: number;
  high_risk_zones: number;
}

export interface ForecastPoint {
  h3_id: string;
  hour: number;
  predicted_count: number;
  max_predicted?: number;
  confidence_lower?: number;
  confidence_upper?: number;
}

export interface PatrolAllocation {
  team_id: number;
  h3_id: string;
  lat: number;
  lon: number;
  priority_rank: number;
  patrol_probability: number;
  congestion_impact: number;
}

export interface SpilloverZone {
  h3_id: string;
  lat: number;
  lon: number;
  original_impact: number;
  adjusted_impact: number;
  change_pct: number;
  spillover_type: string;
}

export interface SimulationRequest {
  num_teams: number;
  hour: number;
  strategy?: string;
}

export interface SimulationResult {
  num_teams: number;
  hour: number;
  strategy: string;
  allocations: PatrolAllocation[];
  uncovered_zones: { h3_id: string; lat: number; lon: number; congestion_impact: number }[];
  covered_impact_pct: number;
  total_impact_covered: number;
  spillover_zones: SpilloverZone[];
}

export interface ViolatorRecord {
  h3_id: string;
  hour: number;
  lat: number;
  lon: number;
  violator_risk_score: number;
  expected_cost: number;
  net_benefit: number;
}

export interface TrafficContext {
  h3_id: string;
  road_name?: string | null;
  road_type?: string | null;
  travel_time_peak_min?: number | null;
  travel_time_offpeak_min?: number | null;
  travel_time_ratio?: number | null;
  nearby_pois: string[];
}

export interface ExplainResult {
  h3_id: string;
  explanation: string;
  is_cached: boolean;
  source: string;
}

export interface SpilloverArrow {
  from_lat: number;
  from_lon: number;
  to_lat: number;
  to_lon: number;
  hour: number;
  magnitude: number;
}

export interface AgentCalibrationEntry {
  zone_id: string;
  reasoning: string;
}

export interface AgentCalibration {
  available: boolean;
  detail?: string;
  summary: {
    total_zones: number;
    validated: number;
    accurate: number;
    adjusted_up: number;
    adjusted_down: number;
  } | null;
  log: AgentCalibrationEntry[];
}
