"""
Risk & Hotspot endpoints.
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
    hour: int = Query(default=None, ge=0, le=23, description="Hour of day"),
    time_bucket: str = Query(default=None, description="Filter by time bucket"),
    zone_id: str = Query(default=None, description="Specific grid cell ID"),
    risk_label: str = Query(default=None, description="Filter by LOW/MEDIUM/HIGH"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get risk scores for grid cells at a given hour or time bucket."""
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

    sql = f"SELECT * FROM risk_scores WHERE {hour_clause}"

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
def get_risk_summary(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    type: str = Query(default="risk", description="risk or spillover"),
):
    """Get summary statistics for risk scores or spillover-adjusted risk at a given hour or time bucket."""
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

    if type == "spillover":
        # Group and classify adjusted_risk
        sql = f"""
            SELECT
                CASE 
                    WHEN adjusted_risk >= 67 THEN 'HIGH'
                    WHEN adjusted_risk >= 33 THEN 'MEDIUM'
                    ELSE 'LOW'
                END as risk_label,
                COUNT(*) as zone_count,
                ROUND(AVG(adjusted_risk), 2) as avg_score,
                ROUND(MIN(adjusted_risk), 2) as min_score,
                ROUND(MAX(adjusted_risk), 2) as max_score,
                SUM(original_risk) as total_violations
            FROM game_spillover
            WHERE {hour_clause}
            GROUP BY risk_label
            ORDER BY avg_score DESC
        """
    else:
        sql = f"""
            SELECT
                risk_label,
                COUNT(*) as zone_count,
                ROUND(AVG(risk_score), 2) as avg_score,
                ROUND(MIN(risk_score), 2) as min_score,
                ROUND(MAX(risk_score), 2) as max_score,
                SUM(violation_count) as total_violations
            FROM risk_scores
            WHERE {hour_clause}
            GROUP BY risk_label
            ORDER BY avg_score DESC
        """
    return query_df(sql, tuple(params))


@router.get("/risk/top_zones")
def get_top_risk_zones(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    n: int = Query(default=10, ge=1, le=50),
):
    """Get the top N highest-risk zones for a given hour or time bucket."""
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

    sql = f"""
        SELECT grid_cell_id, MIN(hour) as hour, AVG(grid_lat) as grid_lat, AVG(grid_lon) as grid_lon,
               AVG(risk_score) as risk_score, MAX(risk_label) as risk_label,
               SUM(violation_count) as violation_count, AVG(density) as density,
               AVG(road_importance) as road_importance, AVG(peak_weight) as peak_weight,
               AVG(repeat_offender) as repeat_offender, AVG(validation_trust) as validation_trust,
               AVG(heavy_vehicle_ratio) as heavy_vehicle_ratio
        FROM risk_scores
        WHERE {hour_clause}
        GROUP BY grid_cell_id
        ORDER BY risk_score DESC
        LIMIT ?
    """
    params.append(n)
    return query_df(sql, tuple(params))


@router.get("/risk/overview")
def get_overview(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
):
    """Dashboard overview stats for a given hour or time bucket."""
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

    risk_summary = query_df(f"""
        SELECT risk_label, COUNT(*) as count, 
               ROUND(AVG(risk_score), 1) as avg_score,
               SUM(violation_count) as total_violations
        FROM risk_scores WHERE {hour_clause}
        GROUP BY risk_label
    """, tuple(params))
    
    top_zone = query_df(f"""
        SELECT grid_cell_id, AVG(risk_score) as avg_risk, SUM(violation_count) as total_violations
        FROM risk_scores WHERE {hour_clause}
        GROUP BY grid_cell_id
        ORDER BY avg_risk DESC LIMIT 1
    """, tuple(params))
    
    total_zones = query_df(f"""
        SELECT COUNT(DISTINCT grid_cell_id) as count FROM risk_scores WHERE {hour_clause}
    """, tuple(params))
    
    return {
        "hour": hour,
        "time_bucket": time_bucket,
        "risk_distribution": risk_summary,
        "top_zone": top_zone[0] if top_zone else None,
        "total_zones": total_zones[0]["count"] if total_zones else 0,
    }


@router.get("/risk/{zone_id}")
def get_zone_risk_detail(
    zone_id: str,
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
):
    """Get detailed risk breakdown for a specific zone at a given hour or time bucket."""
    if time_bucket and time_bucket in TIME_BUCKET_MAP:
        lo, hi = TIME_BUCKET_MAP[time_bucket]
        hour_clause = "r.hour >= ? AND r.hour < ?"
        params = [lo, hi, zone_id]
    elif hour is not None:
        hour_clause = "r.hour = ?"
        params = [hour, zone_id]
    else:
        hour_clause = "1=1"
        params = [zone_id]

    sql = f"""
        SELECT r.grid_cell_id, MIN(r.hour) as hour, AVG(r.grid_lat) as grid_lat, AVG(r.grid_lon) as grid_lon,
               AVG(r.risk_score) as risk_score, MAX(r.risk_label) as risk_label,
               SUM(r.violation_count) as violation_count, AVG(r.density) as density,
               AVG(r.road_importance) as road_importance, AVG(r.peak_weight) as peak_weight,
               AVG(r.repeat_offender) as repeat_offender, AVG(r.validation_trust) as validation_trust,
               AVG(r.heavy_vehicle_ratio) as heavy_vehicle_ratio,
               AVG(s.patrol_probability) as patrol_probability,
               AVG(s.baseline_weight) as baseline_weight,
               AVG(s.adjusted_weight) as adjusted_weight,
               AVG(v.violator_risk_score) as violator_risk_score,
               AVG(v.expected_cost) as expected_cost,
               AVG(v.net_benefit) as net_benefit,
               AVG(sp.adjusted_risk) as spillover_adjusted_risk,
               MAX(sp.spillover_type) as spillover_type,
               AVG(sp.risk_change_pct) as spillover_change_pct
        FROM risk_scores r
        LEFT JOIN game_stackelberg s 
            ON r.grid_cell_id = s.grid_cell_id AND r.hour = s.hour
        LEFT JOIN game_violator_adaptation v 
            ON r.grid_cell_id = v.grid_cell_id AND r.hour = v.hour
        LEFT JOIN game_spillover sp 
            ON r.grid_cell_id = sp.grid_cell_id AND r.hour = sp.hour
        WHERE {hour_clause} AND r.grid_cell_id = ?
        GROUP BY r.grid_cell_id
    """
    data = query_df(sql, tuple(params))
    
    if not data:
        return {"error": f"No data for zone {zone_id}"}
    return data[0]
