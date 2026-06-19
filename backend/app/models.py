"""
ParkVisionSaathi – Pydantic Response Models
Shared data models for API responses.
"""

from pydantic import BaseModel, Field
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

