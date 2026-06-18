"""
Heatmap endpoint – returns lat/lon/intensity arrays for Leaflet heatLayer.
"""

from fastapi import APIRouter, Query
from backend.app.db import query_df

router = APIRouter()


@router.get("/heatmap")
def get_heatmap(
    hour: int = Query(ge=0, le=23, description="Hour of day"),
    type: str = Query(default="risk", description="risk, violator, spillover, or raw"),
):
    """
    Get heatmap data points for Leaflet visualization.

    Types:
    - risk: Risk score heatmap (from risk_scores table)
    - violator: Violator adaptation risk (from game_violator_adaptation)
    - spillover: Spillover-adjusted risk (from game_spillover)
    - raw: Raw violation density
    """
    if type == "risk":
        data = query_df("""
            SELECT grid_lat as lat, grid_lon as lon, risk_score as intensity
            FROM risk_scores
            WHERE hour = ? AND risk_score > 0
            ORDER BY risk_score DESC
        """, (hour,))

    elif type == "violator":
        data = query_df("""
            SELECT grid_lat as lat, grid_lon as lon, violator_risk_score as intensity
            FROM game_violator_adaptation
            WHERE hour = ? AND violator_risk_score > 0
            ORDER BY violator_risk_score DESC
        """, (hour,))

    elif type == "spillover":
        data = query_df("""
            SELECT grid_lat as lat, grid_lon as lon, adjusted_risk as intensity
            FROM game_spillover
            WHERE hour = ? AND adjusted_risk > 0
            ORDER BY adjusted_risk DESC
        """, (hour,))

    elif type == "raw":
        data = query_df("""
            SELECT grid_lat as lat, grid_lon as lon, COUNT(*) as intensity
            FROM violations
            WHERE hour = ?
            GROUP BY grid_cell_id
            ORDER BY intensity DESC
        """, (hour,))

    else:
        return {"error": f"Unknown heatmap type: {type}. Use: risk, violator, spillover, raw"}

    if not data:
        return {"hour": hour, "heatmap_type": type, "points": [],
                "min_intensity": 0, "max_intensity": 0}

    intensities = [d["intensity"] for d in data]
    return {
        "hour": hour,
        "heatmap_type": type,
        "points": data,
        "min_intensity": min(intensities),
        "max_intensity": max(intensities),
    }


@router.get("/heatmap/patrol_overlay")
def get_patrol_overlay(hour: int = Query(ge=0, le=23)):
    """Get patrol probability overlay for map markers (circle sizes)."""
    data = query_df("""
        SELECT grid_lat as lat, grid_lon as lon,
               patrol_probability as probability,
               risk_score
        FROM game_stackelberg
        WHERE hour = ? AND patrol_probability > 0.001
        ORDER BY patrol_probability DESC
        LIMIT 50
    """, (hour,))
    return {"hour": hour, "patrols": data}
