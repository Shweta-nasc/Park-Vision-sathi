"""
ParkVisionSaathi – Pydantic Response Models
Shared data models for API responses.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional


class RiskScoreResponse(BaseModel):
    grid_cell_id: str
    hour: int
    grid_lat: float
    grid_lon: float
    risk_score: float = Field(ge=0, le=100)
    risk_label: str
    violation_count: int
    density: float
    road_importance: float
    peak_weight: float
    repeat_offender: float
    validation_trust: float
    heavy_vehicle_ratio: float


class HotspotResponse(BaseModel):
    cluster_id: int
    time_bucket: str
    centroid_lat: float
    centroid_lon: float
    member_count: int
    bbox_min_lat: float
    bbox_min_lon: float
    bbox_max_lat: float
    bbox_max_lon: float
    top_junction: Optional[str] = None


class ForecastResponse(BaseModel):
    grid_cell_id: str
    date: str
    hour: int
    actual: Optional[float] = None
    predicted: float


class StackelbergResponse(BaseModel):
    grid_cell_id: str
    hour: int
    grid_lat: float
    grid_lon: float
    risk_score: float
    baseline_weight: float
    adjusted_weight: float
    patrol_probability: float


class ViolatorAdaptationResponse(BaseModel):
    grid_cell_id: str
    hour: int
    grid_lat: float
    grid_lon: float
    time_saved: float
    search_time: float
    benefit: float
    expected_cost: float
    net_benefit: float
    violator_risk_score: float


class SpilloverResponse(BaseModel):
    grid_cell_id: str
    hour: int
    grid_lat: float
    grid_lon: float
    original_risk: float
    adjusted_risk: float
    spillover_type: str
    risk_change_pct: float


class HeatmapPoint(BaseModel):
    lat: float
    lon: float
    intensity: float


class HeatmapResponse(BaseModel):
    hour: int
    heatmap_type: str
    points: list[HeatmapPoint]
    min_intensity: float
    max_intensity: float


class SimulationRequest(BaseModel):
    num_teams: int = Field(ge=1, le=20, default=3)
    hour: int = Field(ge=0, le=23, default=9)
    strategy: str = Field(default="stackelberg")  # stackelberg or blotto


class TeamAssignment(BaseModel):
    team_id: int
    grid_cell_id: str
    grid_lat: float
    grid_lon: float
    risk_score: float
    patrol_probability: float
    priority_rank: int


class SpilloverZone(BaseModel):
    grid_cell_id: str
    grid_lat: float
    grid_lon: float
    original_risk: float
    adjusted_risk: float
    risk_change_pct: float
    spillover_type: str


class SimulationResponse(BaseModel):
    num_teams: int
    hour: int
    strategy: str
    assignments: list[TeamAssignment]
    uncovered_high_risk: list[dict]
    coverage_pct: float
    total_risk_covered: float
    spillover_zones: list[SpilloverZone] = []


class TrafficContext(BaseModel):
    zone_id: str
    road_name: Optional[str] = None
    road_type: Optional[str] = None
    travel_time_peak_min: Optional[float] = None
    travel_time_offpeak_min: Optional[float] = None
    travel_time_ratio: Optional[float] = None
    nearby_pois: list[str] = []


class ExplainRequest(BaseModel):
    zone_id: str
    hour: int


class ExplainResponse(BaseModel):
    zone_id: str
    explanation: str
    is_cached: bool
    source: str



# ─────────────────────────────────────────────────────────────────────────────
# Congestion Impact Score (CIS) contract models
# ─────────────────────────────────────────────────────────────────────────────
#
# The typed contract for the "QUANTIFY" pillar. CIS is a deterministic 0-100
# proxy for traffic-flow degradation, computed per H3 zone and time bucket by the
# pure scoring core in ml/congestion/impact_score.py. These models are the
# serialized boundary to the frontend, the self-validating agent, and the
# heatmap/hotspot endpoints. This module stays import-light (pydantic + typing
# only) so the scoring core can import these models with no circular dependency.


# Tolerance for the weights-echo partition-of-unity check (Requirement 6.3).
# Mirrors the canonical ``ml.congestion.impact_score.WEIGHT_SUM_TOLERANCE`` value
# but is redeclared here so this module stays import-light and free of any ``ml``
# dependency (the scoring core imports *this* module, not the reverse).
WEIGHT_SUM_TOLERANCE = 1e-9


class ComponentBreakdown(BaseModel):
    """The five weighted CIS components plus the reported severity diagnostic.

    Each value is normalized to [0, 1]. ``severity`` is surfaced for transparency
    but is deliberately excluded from the weighted CIS sum, keeping the component
    weights a clean partition of unity.
    """

    lane_blockage: float = Field(ge=0.0, le=1.0)
    intersection_impact: float = Field(ge=0.0, le=1.0)
    traffic_degradation: float = Field(ge=0.0, le=1.0)
    access_blockage: float = Field(ge=0.0, le=1.0)
    vehicle_size: float = Field(ge=0.0, le=1.0)
    severity: float = Field(ge=0.0, le=1.0)  # reported diagnostic, NOT weighted


class CongestionBreakdown(BaseModel):
    """Full per-zone, per-time-bucket Congestion Impact breakdown.

    The canonical CIS contract returned by ``/risk/{zone_id}`` and produced by
    ``ml.congestion.impact_score.score_zone``. ``lat``/``lon`` are Optional
    because the scoring core operates on a ``ZoneAggregate`` that carries no
    coordinates; the offline artifact builder attaches the H3-centroid
    coordinates later.
    """

    zone_id: str                      # H3 res-9 id (== h3_id)
    h3_id: str
    time_bucket: str                  # all_day | night | morning_peak | midday | afternoon
    lat: Optional[float] = None       # H3 centroid; filled by the artifact builder
    lon: Optional[float] = None       # H3 centroid; filled by the artifact builder
    congestion_impact: float = Field(ge=0.0, le=100.0)
    impact_band: str                  # MINIMAL | MODERATE | SEVERE | CRITICAL
    components: ComponentBreakdown
    weights: dict[str, float]         # echoes canonical weights (sum == 1.0) for transparency
    estimated_lane_hours_blocked: float = Field(ge=0.0)
    total_records: int = Field(ge=0)
    top_violations: list[str] = []
    station: Optional[str] = None
    junction: Optional[str] = None
    # MapMyIndia validation (the one externally-measured signal).
    mappls_travel_time_ratio: Optional[float] = None
    is_traffic_degradation_defaulted: bool = False   # True when ratio missing -> 0.5
    # Self-validating agent output (optional; filled when a calibration exists).
    calibrated_impact: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    # Time-regime label (Task 12): "calibrated" when this bucket is the one whose
    # ratios were measured/fitted (the served headline "peak window"), else
    # "uncalibrated". Optional/additive — defaults to None for v1 breakdowns.
    time_regime: Optional[str] = None

    @field_validator("weights")
    @classmethod
    def _weights_form_partition_of_unity(
        cls, value: dict[str, float]
    ) -> dict[str, float]:
        """Validate that the echoed component weights sum to 1.0 (Requirement 6.3).

        Requirement 6.3 states the System SHALL validate that the echoed weights
        sum to 1.0 within a tolerance of 1e-9, "permitting any weight distribution
        that satisfies this sum". This therefore checks ONLY the sum — not the
        specific keys, count, or individual values — so any partition of unity is
        accepted. The canonical echo produced by
        ``ml.congestion.impact_score.score_zone`` (a copy of ``WEIGHTS``) satisfies
        this by construction, as does the per-zone breakdown served by the backend.
        A ``weights`` dict whose values do not sum to 1.0 (including an empty dict,
        which sums to 0) is rejected with a ``ValidationError``.
        """
        total = sum(value.values())
        if abs(total - 1.0) >= WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                "weights echo must sum to 1.0 within "
                f"{WEIGHT_SUM_TOLERANCE:g} (got sum={total!r} from {value!r})"
            )
        return value


class HotspotItem(BaseModel):
    """One ranked congestion hotspot (descending CIS) for the hotspot list."""

    rank: int = Field(ge=1)
    zone_id: str
    h3_id: str
    lat: float
    lon: float
    congestion_impact: float = Field(ge=0.0, le=100.0)
    impact_band: str
    violation_count: int = Field(ge=0)
    station: Optional[str] = None
    top_violation: Optional[str] = None
    estimated_lane_hours_blocked: float = Field(ge=0.0)


class CongestionHeatmapPoint(BaseModel):
    """One heatmap point.

    ``intensity`` carries CIS for the risk layer and the violation count for the
    raw layer, so the two-layer toggle is backed by genuinely different values.
    """

    lat: float
    lon: float
    h3_id: str
    intensity: float = Field(ge=0.0)
    impact_band: Optional[str] = None


class CongestionHeatmapResponse(BaseModel):
    """A full heatmap layer payload for the two-layer (risk vs raw) toggle."""

    layer: str           # "risk" (CIS) | "raw" (violation density) | "spillover"
    time_bucket: str
    points: list[CongestionHeatmapPoint]
    min_intensity: float
    max_intensity: float
