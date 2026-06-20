"""
Heatmap endpoint – returns lat/lon/intensity arrays for Leaflet heatLayer.
"""

from fastapi import APIRouter, Query
from backend.app.db import query_df

router = APIRouter()

TIME_BUCKET_MAP = {
    "night_0_6": (0, 6),
    "morning_6_10": (6, 10),
    "midday_10_16": (10, 16),
    "evening_16_22": (16, 22),
    "night_22_24": (22, 24),
}


@router.get("/heatmap")
def get_heatmap(
    hour: int = Query(default=None, ge=0, le=23, description="Hour of day"),
    time_bucket: str = Query(default=None, description="Time bucket"),
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
    if time_bucket and time_bucket in TIME_BUCKET_MAP:
        lo, hi = TIME_BUCKET_MAP[time_bucket]
        hour_clause = "hour >= ? AND hour < ?"
        params = [lo, hi]
    elif hour is not None:
        hour_clause = "hour = ?"
        params = [hour]
    else:
        hour_clause = "1=1"
        params = []

    if type == "risk":
        data = query_df(f"""
            SELECT grid_lat as lat, grid_lon as lon, AVG(risk_score) as intensity
            FROM risk_scores
            WHERE {hour_clause} AND risk_score > 0
            GROUP BY grid_cell_id
            ORDER BY intensity DESC
        """, tuple(params))

    elif type == "violator":
        data = query_df(f"""
            SELECT grid_lat as lat, grid_lon as lon, AVG(violator_risk_score) as intensity
            FROM game_violator_adaptation
            WHERE {hour_clause} AND violator_risk_score > 0
            GROUP BY grid_cell_id
            ORDER BY intensity DESC
        """, tuple(params))

    elif type == "spillover":
        data = query_df(f"""
            SELECT grid_lat as lat, grid_lon as lon, AVG(adjusted_risk) as intensity
            FROM game_spillover
            WHERE {hour_clause} AND adjusted_risk > 0
            GROUP BY grid_cell_id
            ORDER BY intensity DESC
        """, tuple(params))

    elif type == "raw":
        data = query_df(f"""
            SELECT grid_lat as lat, grid_lon as lon, COUNT(*) as intensity
            FROM violations
            WHERE {hour_clause}
            GROUP BY grid_cell_id
            ORDER BY intensity DESC
        """, tuple(params))

    else:
        return {"error": f"Unknown heatmap type: {type}. Use: risk, violator, spillover, raw"}

    if not data:
        return {"hour": hour, "time_bucket": time_bucket, "heatmap_type": type, "points": [],
                "min_intensity": 0, "max_intensity": 0}

    intensities = [d["intensity"] for d in data]
    return {
        "hour": hour,
        "time_bucket": time_bucket,
        "heatmap_type": type,
        "points": data,
        "min_intensity": min(intensities),
        "max_intensity": max(intensities),
    }


@router.get("/heatmap/patrol_overlay")
def get_patrol_overlay(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None)
):
    """Get patrol probability overlay for map markers (circle sizes)."""
    if time_bucket and time_bucket in TIME_BUCKET_MAP:
        lo, hi = TIME_BUCKET_MAP[time_bucket]
        hour_clause = "hour >= ? AND hour < ?"
        params = [lo, hi]
    elif hour is not None:
        hour_clause = "hour = ?"
        params = [hour]
    else:
        hour_clause = "1=1"
        params = []

    data = query_df(f"""
        SELECT grid_lat as lat, grid_lon as lon,
               AVG(patrol_probability) as probability,
               AVG(risk_score) as risk_score
        FROM game_stackelberg
        WHERE {hour_clause}
        GROUP BY grid_cell_id
        HAVING probability > 0.001
        ORDER BY probability DESC
        LIMIT 50
    """, tuple(params))
    return {"hour": hour, "time_bucket": time_bucket, "patrols": data}
