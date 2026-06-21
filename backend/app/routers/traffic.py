"""
Traffic Context endpoint — REAL MapMyIndia / Mappls enrichment for a zone.

Primary source is the in-memory DataStore enrichment (``store.traffic_raw``,
loaded from ``data/enriched/traffic_context.json``) looked up directly by
``zone_id``. WHERE no direct entry exists, the endpoint falls back to the nearest
enriched zone by centroid (lat/lon, within ``MAX_MATCH_KM``, using the zone's
DataStore ``grid_lat``/``grid_lon``) — the enrichment file is H3-keyed while the
zone universe uses a grid-cell scheme, so a nearest-centroid match recovers real
travel-time data the direct lookup would miss. Everything is served from
in-memory/JSON state (no database).
"""

import json
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path

from fastapi import APIRouter
from backend.app.data_loader import store
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
    """Real travel-time ratio, road details and nearby POIs for a zone.

    Primary: the DataStore's direct ``traffic_raw`` enrichment for ``zone_id`` (the
    verified data flow). Fallback: when no direct entry exists, the nearest enriched
    zone by centroid (within ``MAX_MATCH_KM``), matched using the zone's DataStore
    ``grid_lat``/``grid_lon`` — no database.
    """
    tc = store.ensure().traffic_raw.get(zone_id, {})
    z = store.zone(zone_id) or {}

    # Fallback: no direct enrichment for this zone_id → match the nearest enriched
    # zone by centroid (real Mappls data, H3-keyed) using the DataStore centroid.
    if not tc and z.get("grid_lat") is not None and z.get("grid_lon") is not None:
        match = _nearest_enriched(z["grid_lat"], z["grid_lon"])
        if match:
            tc = match

    return TrafficContext(
        zone_id=zone_id,
        road_name=tc.get("road_name") or tc.get("street") or z.get("road_name"),
        road_type=tc.get("road_type") or z.get("road_type"),
        # peak = live ETA, off-peak = free-flow baseline (real Mappls minutes)
        travel_time_peak_min=tc.get("travel_time_eta_min"),
        travel_time_offpeak_min=tc.get("travel_time_baseline_min"),
        travel_time_ratio=tc.get("travel_time_ratio") or z.get("travel_time_ratio"),
        nearby_pois=tc.get("nearby_pois", z.get("nearby_pois", [])),
    )
