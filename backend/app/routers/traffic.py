"""
Traffic Context endpoint — REAL MapMyIndia enrichment for a zone.
Served from data/enriched/traffic_context.json via the in-memory DataStore.
"""

from fastapi import APIRouter
from backend.app.data_loader import store
from backend.app.models import TrafficContext

router = APIRouter()


@router.get("/traffic/{zone_id}", response_model=TrafficContext)
def get_traffic_context(zone_id: str):
    """Real travel-time ratio, road details and nearby POIs for a zone."""
    tc = store.ensure().traffic_raw.get(zone_id, {})
    z = store.zone(zone_id) or {}

    return TrafficContext(
        zone_id=zone_id,
        road_name=tc.get("road_name") or z.get("road_name"),
        road_type=tc.get("road_type") or z.get("road_type"),
        # peak = live ETA, off-peak = free-flow baseline (real Mappls minutes)
        travel_time_peak_min=tc.get("travel_time_eta_min"),
        travel_time_offpeak_min=tc.get("travel_time_baseline_min"),
        travel_time_ratio=tc.get("travel_time_ratio") or z.get("travel_time_ratio"),
        nearby_pois=tc.get("nearby_pois", z.get("nearby_pois", [])),
    )
