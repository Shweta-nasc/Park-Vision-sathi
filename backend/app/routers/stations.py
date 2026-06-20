"""
Station endpoints — station list, per-station priority areas and summary.
Served from the in-memory DataStore (real H3 zones). No database.
"""

from fastapi import APIRouter, Query, Path
from backend.app.data_loader import store

router = APIRouter()


@router.get("/stations")
def list_stations():
    """All police stations present in the hotspot data, with summary stats."""
    return store.stations()


def _priority(score: float):
    if score >= 67:
        return 3, "High"
    if score >= 34:
        return 2, "Medium"
    return 1, "Low"


@router.get("/stations/{station}/priority_areas")
def get_station_priority_areas(
    station: str = Path(description="Police station name"),
    hour: int = Query(default=9, ge=0, le=23),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Zones under a station, ranked by congestion impact, with force + ETA."""
    zones = store.station_zones(station)
    # Station centroid for distance/ETA estimate.
    if zones:
        base_lat = sum(z["grid_lat"] for z in zones) / len(zones)
        base_lon = sum(z["grid_lon"] for z in zones) / len(zones)
    else:
        base_lat, base_lon = 12.97, 77.59

    out = []
    for z in zones[:limit]:
        area = dict(z)
        force, priority = _priority(z["risk_score"])
        area["force_needed"] = force
        area["priority"] = priority
        dlat = abs(z["grid_lat"] - base_lat)
        dlon = abs(z["grid_lon"] - base_lon)
        area["distance_km"] = round(((dlat * 111) ** 2 + (dlon * 111 * 0.87) ** 2) ** 0.5, 1)
        area["eta_minutes"] = max(3, round(area["distance_km"] * 4))  # ~15 km/h city avg
        out.append(area)
    return out


@router.get("/stations/{station}/summary")
def get_station_summary(
    station: str = Path(description="Police station name"),
    hour: int = Query(default=9, ge=0, le=23),
):
    """Summary for a station: zone count, violations, high-risk count."""
    zones = store.station_zones(station)
    breakdown: dict[str, dict] = {}
    for z in zones:
        b = breakdown.setdefault(z["risk_label"], {"risk_label": z["risk_label"], "count": 0, "violations": 0})
        b["count"] += 1
        b["violations"] += z["violation_count"]
    return {
        "station": station,
        "hour": hour,
        "total_zones": len(zones),
        "total_violations": sum(z["violation_count"] for z in zones),
        "high_risk_zones": sum(1 for z in zones if z["risk_score"] >= 67),
        "breakdown": list(breakdown.values()),
    }
