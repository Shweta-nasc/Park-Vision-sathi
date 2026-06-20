"""
Heatmap endpoint — lat/lon/intensity points for the map layers.

Layers (frontend maps these to the `type` param):
  raw       → violation density  (where violations happen)
  risk      → congestion impact   (where violations choke traffic)
  spillover → agent-calibrated impact

Served from the in-memory DataStore (real H3 zones). No database.
"""

from fastapi import APIRouter, Query
from backend.app.data_loader import store

router = APIRouter()


@router.get("/heatmap")
def get_heatmap(
    hour: int = Query(default=None, ge=0, le=23, description="Hour of day (informational)"),
    time_bucket: str = Query(default=None, description="Time bucket (informational)"),
    type: str = Query(default="risk", description="risk | raw | spillover"),
):
    """Heatmap points for Leaflet/Mappls heat layers."""
    layer = type if type in {"risk", "raw", "spillover"} else "risk"
    points = store.heatmap_points(layer)
    intensities = [p["intensity"] for p in points]
    return {
        "hour": hour,
        "time_bucket": time_bucket,
        "heatmap_type": type,
        "points": points,
        "min_intensity": min(intensities) if intensities else 0,
        "max_intensity": max(intensities) if intensities else 0,
    }


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
