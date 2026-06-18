"""
Risk & Hotspot endpoints.
"""

from fastapi import APIRouter, Query
from backend.app.db import query_df

router = APIRouter()


@router.get("/hotspots")
def get_hotspots(
    hour: int = Query(default=None, ge=0, le=23, description="Filter by hour"),
    time_bucket: str = Query(default=None, description="Filter by time bucket"),
    min_members: int = Query(default=5, description="Minimum cluster size"),
):
    """Get DBSCAN hotspot clusters, optionally filtered by hour or time bucket."""
    sql = "SELECT * FROM hotspot_clusters WHERE member_count >= ?"
    params = [min_members]

    if time_bucket:
        sql += " AND time_bucket = ?"
        params.append(time_bucket)
    elif hour is not None:
        # Map hour to time bucket
        if hour < 6:
            bucket = "night_0_6"
        elif hour < 10:
            bucket = "morning_6_10"
        elif hour < 16:
            bucket = "midday_10_16"
        elif hour < 22:
            bucket = "evening_16_22"
        else:
            bucket = "night_22_24"
        sql += " AND time_bucket = ?"
        params.append(bucket)

    sql += " ORDER BY member_count DESC"
    return query_df(sql, tuple(params))


@router.get("/risk")
def get_risk_scores(
    hour: int = Query(ge=0, le=23, description="Hour of day"),
    zone_id: str = Query(default=None, description="Specific grid cell ID"),
    risk_label: str = Query(default=None, description="Filter by LOW/MEDIUM/HIGH"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get risk scores for grid cells at a given hour."""
    sql = "SELECT * FROM risk_scores WHERE hour = ?"
    params = [hour]

    if zone_id:
        sql += " AND grid_cell_id = ?"
        params.append(zone_id)
    if risk_label:
        sql += " AND risk_label = ?"
        params.append(risk_label.upper())

    sql += " ORDER BY risk_score DESC LIMIT ?"
    params.append(limit)
    return query_df(sql, tuple(params))


@router.get("/risk/summary")
def get_risk_summary(hour: int = Query(ge=0, le=23)):
    """Get summary statistics for risk scores at a given hour."""
    sql = """
        SELECT
            risk_label,
            COUNT(*) as zone_count,
            ROUND(AVG(risk_score), 2) as avg_score,
            ROUND(MIN(risk_score), 2) as min_score,
            ROUND(MAX(risk_score), 2) as max_score,
            SUM(violation_count) as total_violations
        FROM risk_scores
        WHERE hour = ?
        GROUP BY risk_label
        ORDER BY avg_score DESC
    """
    return query_df(sql, (hour,))


@router.get("/risk/top_zones")
def get_top_risk_zones(
    hour: int = Query(ge=0, le=23),
    n: int = Query(default=10, ge=1, le=50),
):
    """Get the top N highest-risk zones for a given hour."""
    sql = """
        SELECT grid_cell_id, hour, grid_lat, grid_lon, risk_score, risk_label,
               violation_count, density, road_importance, peak_weight,
               repeat_offender, validation_trust, heavy_vehicle_ratio
        FROM risk_scores
        WHERE hour = ?
        ORDER BY risk_score DESC
        LIMIT ?
    """
    return query_df(sql, (hour, n))
