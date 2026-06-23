/**
 * Frontend domain models, aligned to the REAL backend contract (see API_DOCS.md).
 *
 * Two distinct scores are carried side by side — never aliased:
 *   • `risk_score`         — enforcement priority ("where violations happen").
 *   • `congestion_impact`  — Congestion Impact Score / CIS ("where traffic is choked").
 * A zone can be CRITICAL on one and MINIMAL on the other; that contrast is the
 * product's core thesis and powers the two-layer heatmap toggle.
 *
 * The backend uses `grid_cell_id`/`grid_lat`/`grid_lon`; adapters translate those
 * into `h3_id`/`lat`/`lon` so components speak one vocabulary.
 */

export type ImpactBand = 'MINIMAL' | 'MODERATE' | 'SEVERE' | 'CRITICAL';
export type RiskLabel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type MapLayer = 'violation_density' | 'congestion_risk' | 'spillover';

/** The five weighted CIS sub-components (each 0–1) + reported severity. */
export interface CongestionComponents {
  lane_blockage: number;
  intersection_impact: number;
  traffic_degradation: number;
  access_blockage: number;
  vehicle_size: number;
  severity: number;
}

/** A single zone with both its enforcement-priority and congestion-impact profile. */
export interface Zone {
  h3_id: string;
  lat: number;
  lon: number;
  hour: number;
  /** Enforcement priority 0–100 (backend risk_score). Drives markers & game theory. */
  risk_score: number;
  risk_label: RiskLabel;
  /** Congestion Impact Score 0–100 (CIS). Distinct from risk_score. */
  congestion_impact: number;
  impact_band: ImpactBand;
  /** Agent-calibrated CIS (vs real travel time), when available. */
  calibrated_score?: number;
  /** Served regime for this breakdown's bucket: 'calibrated' | 'uncalibrated' (Task 12). */
  time_regime?: string | null;
  violation_count: number;
  // Component breakdown (real where the CIS artifact provides it)
  density: number;
  road_importance: number;
  peak_weight: number;
  repeat_offender: number;
  validation_trust: number;
  heavy_vehicle_ratio: number;
  estimated_lane_hours_blocked: number;
  /** Real CIS component breakdown (only present after a /risk/{id} fetch). */
  components?: CongestionComponents;
  /** Live CIS component weights (calibrated v2), present on /risk/{id} breakdowns. */
  weights?: Record<string, number> | null;
  top_violations?: string[];
  mappls_ratio?: number | null;
  // Game-theory enrichment (present on /risk list, /game/* responses)
  patrol_probability?: number;
  violator_risk_score?: number;
  expected_cost?: number;
  net_benefit?: number;
  // Station context
  station?: string;
  junction?: string | null;
  top_violation?: string | null;
  agent_status?: string | null;
  agent_reasoning?: string | null;
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

/** Next-day forecast for one H3 zone (PREDICT pillar). */
export interface ForecastPoint {
  h3_id: string;
  lat: number;
  lon: number;
  predicted_count: number;
  predicted_risk: number;
  predicted_band: ImpactBand;
  confidence_lower?: number;
  confidence_upper?: number;
  is_proxy: boolean;
}

/** Real held-out accuracy of the forecast model. */
export interface ForecastAccuracy {
  model: string;
  is_proxy: boolean;
  precision_at_10?: number;
  mae?: number;
  rmse?: number;
  n_test_days?: number;
  generated_for?: string;
  summary?: string;
  spatial_unit?: string;
  target?: string;
}

export interface ForecastContributor {
  feature: string;
  value: number;
  contribution: number;
}

export interface ForecastExplanationZone {
  zone_id?: string;
  h3_id?: string;
  base_value: number;
  predicted_count?: number | null;
  top_contributors: ForecastContributor[];
}

export interface ForecastExplanations {
  available: boolean;
  feature_names?: string[];
  top_k?: number;
  note?: string;
  zones: ForecastExplanationZone[];
}

export interface PatrolAllocation {
  team_id: number;
  h3_id: string;
  lat: number;
  lon: number;
  priority_rank: number;
  patrol_probability: number;
  /** carries the zone's risk_score (enforcement priority). */
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

/** Waterbed displacement arrow (from a patrolled zone to its spill neighbour). */
export interface SpilloverArrow {
  from_zone?: string;
  to_zone?: string;
  from_lat: number;
  from_lon: number;
  to_lat: number;
  to_lon: number;
  weight: number;
}

export interface AgentZone {
  zone_id: string;
  station?: string;
  raw_score: number;
  calibrated_score: number;
  impact_band?: ImpactBand;
  status: string; // validated_accurate | adjusted_up | adjusted_down
  mappls_ratio?: number;
  reasoning: string;
}

export interface CalibrationRun {
  available: boolean;
  weights_old?: Record<string, number> | null;
  weights_new?: Record<string, number> | null;
  weights_method?: string | null;
  spearman_old?: number | null;
  spearman_new?: number | null;
  n_zones_measured?: number | null;
  n_exploration?: number | null;
  lozo_metrics?: {
    model?: string | null;
    lozo_r2?: number | null;
    lozo_spearman?: number | null;
  } | null;
}

export interface AgentReport {
  available: boolean;
  summary: {
    total_zones: number;
    calibrated: number;
    validated: number;
    accurate: number;
    adjusted_up: number;
    adjusted_down: number;
    mean_abs_adjustment_pct?: number;
  } | null;
  zones: AgentZone[];
  /** Task 6: the agent's offline before/after weight + trust block. */
  calibration_run?: CalibrationRun | null;
}

/** Bootstrap confidence interval for a Spearman ρ (Task 11). */
export interface SpearmanCI {
  rho?: number | null;
  lo?: number | null;
  hi?: number | null;
  p_approx?: number | null;
  n?: number | null;
  n_boot?: number | null;
}

/** One zone in the density≠impact scatter (Task 13). */
export interface ProofPoint {
  h3_id: string;
  /** Full CIS 0–100. */
  cis: number;
  /** Honest CIS predictor (4 non-traffic components, 0–1), null when components absent. */
  cis_honest: number | null;
  /** Raw violation count (the "density" view). */
  count: number;
  /** Measured MapMyIndia travel-time ratio (the ground truth y-axis). */
  measured_ratio: number;
  is_exploration: boolean;
  split: string; // 'train' | 'test'
}

/**
 * The CIS validation "density ≠ impact" proof (Task 13). Held-out test-split
 * Spearman correlations of three predictors vs the measured congestion ratio:
 * the honest non-circular CIS, the raw-count baseline, and the circular full-CIS
 * upper bound — each with a bootstrap CI. `available` is false while the live
 * MapMyIndia run is still pending (graceful empty state).
 */
export interface ValidationProof {
  available: boolean;
  n_measured?: number | null;
  n_proof?: number | null;
  n_exploration?: number | null;
  spearman_cis_honest?: number | null;
  spearman_cis_honest_ci?: SpearmanCI | null;
  spearman_count?: number | null;
  spearman_count_ci?: SpearmanCI | null;
  spearman_cis_full?: number | null;
  spearman_cis_full_ci?: SpearmanCI | null;
  cis_full_note?: string | null;
  baseline_beaten?: boolean | null;
  calibration_strength?: 'strong' | 'weak' | 'aborted' | null;
  honest_weights?: Record<string, number> | null;
  honest_excludes?: string | null;
  split_seed?: number | null;
  time_bucket?: string | null;
  generated_at?: string | null;
  points: ProofPoint[];
}

/** One vertex of a drivable route polyline (Route now feature). */
export interface RoutePoint {
  lat: number;
  lon: number;
}

/**
 * Drivable route geometry from /route (cache-first, offline-safe). `geometry` is
 * a road-following polyline when a cached/live Mappls path exists, else null —
 * in which case the map falls back to a straight dashed line. `source` reports
 * where the geometry came from.
 */
export interface RouteResponse {
  geometry: RoutePoint[] | null;
  source: 'cache' | 'mappls' | 'none';
}

/**
 * Calibration coherence info (Task 12), from /risk/calibration (or /health).
 * Tells the UI which time bucket is the calibrated headline "measured window".
 */
export interface CalibrationInfo {
  calibrated: boolean;
  cis_version?: string;
  headline_bucket?: string;
  calibrated_bucket?: string | null;
  weights?: Record<string, number> | null;
  spearman_test?: number | null;
  n_measured?: number | null;
}
