"""
Station endpoints – station list and per-station priority areas.
"""

from fastapi import APIRouter, Query, Path
from backend.app.db import query_df

router = APIRouter()


@router.get("/stations")
def list_stations():
    """List all police stations with summary stats."""
    data = query_df("""
        SELECT
            police_station as name,
            COUNT(DISTINCT grid_cell_id) as zone_count,
            COUNT(*) as total_violations,
            ROUND(AVG(latitude), 4) as lat,
            ROUND(AVG(longitude), 4) as lon
        FROM violations
        WHERE police_station IS NOT NULL
        GROUP BY police_station
        ORDER BY total_violations DESC
    """)
    return data


@router.get("/stations/{station}/priority_areas")
def get_station_priority_areas(
    station: str = Path(description="Police station name"),
    hour: int = Query(default=9, ge=0, le=23),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Get priority areas (grid cells) under a station, ranked by risk score."""
    data = query_df("""
        SELECT
            r.grid_cell_id,
            r.hour,
            r.grid_lat,
            r.grid_lon,
            r.risk_score,
            r.risk_label,
            r.violation_count,
            r.density,
            r.road_importance,
            r.peak_weight,
            r.repeat_offender,
            r.heavy_vehicle_ratio,
            COALESCE(s.patrol_probability, 0) as patrol_probability,
            COALESCE(va.violator_risk_score, 0) as violator_risk_score,
            v.junction_name as top_junction,
            v.police_station
        FROM risk_scores r
        JOIN (
            SELECT DISTINCT grid_cell_id, police_station,
                   junction_name
            FROM violations
            WHERE police_station = ?
        ) v ON r.grid_cell_id = v.grid_cell_id
        LEFT JOIN game_stackelberg s
            ON r.grid_cell_id = s.grid_cell_id AND r.hour = s.hour
        LEFT JOIN game_violator_adaptation va
            ON r.grid_cell_id = va.grid_cell_id AND r.hour = va.hour
        WHERE r.hour = ?
        GROUP BY r.grid_cell_id
        ORDER BY r.risk_score DESC
        LIMIT ?
    """, (station, hour, limit))

    # Add estimated force needed and distance from station centroid
    station_info = query_df("""
        SELECT ROUND(AVG(latitude), 4) as lat, ROUND(AVG(longitude), 4) as lon
        FROM violations WHERE police_station = ?
    """, (station,))

    base_lat = station_info[0]["lat"] if station_info else 12.97
    base_lon = station_info[0]["lon"] if station_info else 77.59

    for area in data:
        # Estimate force needed: 1 for LOW, 2 for MEDIUM, 3 for HIGH
        risk = area.get("risk_score", 0)
        if risk >= 67:
            area["force_needed"] = 3
            area["priority"] = "High"
        elif risk >= 34:
            area["force_needed"] = 2
            area["priority"] = "Medium"
        else:
            area["force_needed"] = 1
            area["priority"] = "Low"

        # Estimate distance from station (approximate km)
        dlat = abs(area["grid_lat"] - base_lat)
        dlon = abs(area["grid_lon"] - base_lon)
        area["distance_km"] = round(((dlat * 111) ** 2 + (dlon * 111 * 0.87) ** 2) ** 0.5, 1)
        area["eta_minutes"] = max(3, round(area["distance_km"] * 4))  # ~15 km/h avg city

    return data


@router.get("/stations/{station}/summary")
def get_station_summary(
    station: str = Path(description="Police station name"),
    hour: int = Query(default=9, ge=0, le=23),
):
    """Get summary for a specific station at a given hour."""
    areas = query_df("""
        SELECT r.risk_label, COUNT(*) as count, SUM(r.violation_count) as violations
        FROM risk_scores r
        JOIN (
            SELECT DISTINCT grid_cell_id FROM violations WHERE police_station = ?
        ) v ON r.grid_cell_id = v.grid_cell_id
        WHERE r.hour = ?
        GROUP BY r.risk_label
    """, (station, hour))

    total_zones = sum(a["count"] for a in areas)
    total_violations = sum(a["violations"] for a in areas)
    high_count = next((a["count"] for a in areas if a["risk_label"] == "HIGH"), 0)

    return {
        "station": station,
        "hour": hour,
        "total_zones": total_zones,
        "total_violations": total_violations,
        "high_risk_zones": high_count,
        "breakdown": areas,
    }
