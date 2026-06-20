"""
Traffic Context endpoint – returns travel times, road details, and nearby POIs for a zone.

Uses REAL MapMyIndia / Mappls enrichment data (data/enriched/traffic_context.json)
when a nearby enriched zone is available, and falls back to a risk-score-derived
estimate otherwise. The enrichment file is keyed by H3 cell id while the database
uses a grid-cell scheme, so zones are matched by nearest centroid (lat/lon).
"""

import json
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path

from fastapi import APIRouter
from backend.app.db import query_df
from backend.app.models import TrafficContext

router = APIRouter()

ENRICHED_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "enriched" / "traffic_context.json"
)

# Match an enriched zone only if it is within this distance of the query zone.
MAX_MATCH_KM = 0.6


def _load_enriched() -> list[dict]:
    """Load enriched MapMyIndia zones once and cache on the function object."""
    if getattr(_load_enriched, "_cache", None) is None:
        try:
            with open(ENRICHED_PATH) as f:
                data = json.load(f)
            _load_enriched._cache = [
                v for v in data.values()
                if v.get("lat") is not None and v.get("lon") is not None
            ]
        except (FileNotFoundError, json.JSONDecodeError):
            _load_enriched._cache = []
    return _load_enriched._cache


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


def _nearest_enriched(lat: float, lon: float) -> dict | None:
    """Return the nearest enriched zone within MAX_MATCH_KM, or None."""
    best, best_d = None, MAX_MATCH_KM
    for zone in _load_enriched():
        d = _haversine_km(lat, lon, zone["lat"], zone["lon"])
        if d < best_d:
            best, best_d = zone, d
    return best


@router.get("/traffic/{zone_id}", response_model=TrafficContext)
def get_traffic_context(zone_id: str):
    """Get traffic context and travel delay ratio for a given zone.

    Prefers real MapMyIndia enrichment (travel time ratio + nearby POIs) matched
    by nearest centroid; falls back to a risk-score-derived estimate.
    """
    # Zone centroid + risk info from the database.
    risk_info = query_df("""
        SELECT AVG(grid_lat) as lat, AVG(grid_lon) as lon,
               AVG(risk_score) as avg_risk, AVG(road_importance) as road_imp
        FROM risk_scores
        WHERE grid_cell_id = ?
    """, (zone_id,))

    lat = risk_info[0]["lat"] if risk_info and risk_info[0]["lat"] else None
    lon = risk_info[0]["lon"] if risk_info and risk_info[0]["lon"] else None
    avg_risk = risk_info[0]["avg_risk"] if risk_info and risk_info[0]["avg_risk"] else 0.0
    road_imp = risk_info[0]["road_imp"] if risk_info and risk_info[0]["road_imp"] else 1.0

    # ── Try real enrichment first ────────────────────────────────────────────
    match = _nearest_enriched(lat, lon) if lat is not None and lon is not None else None
    if match:
        baseline = match.get("travel_time_baseline_min")
        eta = match.get("travel_time_eta_min")
        ratio = match.get("travel_time_ratio")
        road_type = "Arterial Road" if road_imp > 0.5 else "Sub-Arterial Road"
        return TrafficContext(
            zone_id=zone_id,
            road_name=match.get("road_name") or match.get("street"),
            road_type=road_type,
            travel_time_peak_min=round(eta, 1) if eta is not None else None,
            travel_time_offpeak_min=round(baseline, 1) if baseline is not None else None,
            travel_time_ratio=round(ratio, 2) if ratio is not None else None,
            nearby_pois=match.get("nearby_pois", []),
        )

    # ── Fallback: derive an estimate from risk score ─────────────────────────
    road_info = query_df("""
        SELECT DISTINCT location, junction_name, police_station
        FROM violations
        WHERE grid_cell_id = ? AND (location IS NOT NULL OR junction_name IS NOT NULL)
        LIMIT 1
    """, (zone_id,))

    pois = ["Commercial Complex", "Bus Stop", "Metro Station Corridor"]
    if road_info:
        station = road_info[0]["police_station"]
        if station:
            pois.append(f"{station} Police Station Area")
        road_name = road_info[0]["junction_name"] or road_info[0]["location"] or f"Grid Sector {zone_id}"
    else:
        road_name = f"Grid Sector {zone_id}"

    base_travel_time = 5.0 + (road_imp * 3.0)
    delay_factor = 1.0 + (avg_risk / 100.0) * 1.5
    peak_time = base_travel_time * delay_factor
    offpeak_time = base_travel_time

    return TrafficContext(
        zone_id=zone_id,
        road_name=road_name.split(",")[0].strip(),
        road_type="Arterial Road" if road_imp > 0.5 else "Sub-Arterial Road",
        travel_time_peak_min=round(peak_time, 1),
        travel_time_offpeak_min=round(offpeak_time, 1),
        travel_time_ratio=round(delay_factor, 2),
        nearby_pois=pois,
    )
