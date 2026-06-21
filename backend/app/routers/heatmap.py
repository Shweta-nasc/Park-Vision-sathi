"""
Heatmap endpoint — typed point layers for the two-layer map toggle.

Layers (frontend maps these to the `type` param):
  risk      → congestion impact   (where violations choke traffic) — intensity = CIS
  raw       → violation density   (where violations happen)        — intensity = count
  spillover → agent-calibrated impact

The `risk` and `raw` layers are served straight from the canonical CIS artifact
via the DataStore accessors (`congestion_points` / `violation_density_points`),
so the toggle is backed by genuinely different values — CIS vs raw count — the
"density != impact" thesis (Req 8.3, 8.4, 10.2). Because that artifact is
materialized offline, both layers return empty points (min/max 0.0) until it
exists — designed graceful, offline-safe behavior (no fabricated data).

The `spillover` layer is preserved as-is: it is the agent-calibrated layer drawn
from the legacy hotspot-derived zone universe (`heatmap_points("spillover")`,
intensity = `calibrated_score`), which is NOT keyed to the CIS artifact — so it
keeps its current source and is merely adapted into the response shape.

All layers return a typed `CongestionHeatmapResponse`. Served from the in-memory
DataStore (real H3 zones). No database.
"""

from fastapi import APIRouter, Query
from backend.app.data_loader import store
from backend.app.models import CongestionHeatmapPoint, CongestionHeatmapResponse

router = APIRouter()


@router.get("/heatmap", response_model=CongestionHeatmapResponse)
def get_heatmap(
    type: str = Query(default="risk", description="risk | raw | spillover"),
    time_bucket: str = Query(
        default="all_day",
        description="all_day | night | morning_peak | midday | afternoon",
    ),
    hour: int = Query(default=None, ge=0, le=23, description="Hour of day (informational)"),
):
    """Heatmap layer for the two-layer (Congestion Risk vs Violation Density) toggle.

    `type=risk` serves CIS intensities, `type=raw` serves violation-count
    intensities (both from the CIS artifact, with an `all_day` fallback for an
    unknown `time_bucket`), and `type=spillover` serves the agent-calibrated layer
    from its existing source. An unknown `type` falls back to `risk`. `min_intensity`
    / `max_intensity` are computed from the returned points and are 0.0 when empty.
    """
    layer = type if type in {"risk", "raw", "spillover"} else "risk"
    if layer == "raw":
        raw_points = store.violation_density_points(time_bucket)
    elif layer == "spillover":
        # Preserved legacy source: agent-calibrated layer from the hotspot-derived
        # zone universe (NOT the CIS artifact); adapted into the typed shape.
        raw_points = store.heatmap_points("spillover")
    else:  # risk → Congestion Impact Score
        raw_points = store.congestion_points(time_bucket)

    points = [CongestionHeatmapPoint.model_validate(p) for p in raw_points]
    intensities = [p.intensity for p in points]
    return CongestionHeatmapResponse(
        layer=layer,
        time_bucket=time_bucket,
        points=points,
        min_intensity=min(intensities) if intensities else 0.0,
        max_intensity=max(intensities) if intensities else 0.0,
    )


@router.get("/heatmap/patrol_overlay")
def get_patrol_overlay(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
):
    """Patrol-probability overlay for map markers (circle sizing)."""
    zones = store.top_zones(50)
    patrols = [
        {"lat": z["grid_lat"], "lon": z["grid_lon"],
         "probability": z["patrol_probability"], "risk_score": z["risk_score"]}
        for z in zones if z["patrol_probability"] > 0.001
    ]
    return {"hour": hour, "time_bucket": time_bucket, "patrols": patrols}
