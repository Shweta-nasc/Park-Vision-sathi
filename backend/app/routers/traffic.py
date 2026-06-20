"""
Traffic Context endpoint – returns travel times, road details, and nearby POIs for a zone.
"""

from fastapi import APIRouter
from backend.app.db import query_df
from backend.app.models import TrafficContext

router = APIRouter()


@router.get("/traffic/{zone_id}", response_model=TrafficContext)
def get_traffic_context(zone_id: str):
    """Get traffic context and travel delay ratio for a given zone."""
    # Query road names/junctions from the violations table as a starting point
    road_info = query_df("""
        SELECT DISTINCT location, junction_name, police_station
        FROM violations
        WHERE grid_cell_id = ? AND (location IS NOT NULL OR junction_name IS NOT NULL)
        LIMIT 1
    """, (zone_id,))

    # We default travel times and calculate travel_time_ratio based on risk_scores
    risk_info = query_df("""
        SELECT AVG(risk_score) as avg_risk, AVG(road_importance) as road_imp
        FROM risk_scores
        WHERE grid_cell_id = ?
    """, (zone_id,))

    avg_risk = risk_info[0]["avg_risk"] if risk_info and risk_info[0]["avg_risk"] else 0.0
    road_imp = risk_info[0]["road_imp"] if risk_info and risk_info[0]["road_imp"] else 1.0

    # Mock POIs based on police station and location
    pois = ["Commercial Complex", "Bus Stop", "Metro Station Corridor"]
    if road_info:
        station = road_info[0]["police_station"]
        if station:
            pois.append(f"{station} Police Station Area")
        road_name = road_info[0]["junction_name"] or road_info[0]["location"] or f"Grid Sector {zone_id}"
    else:
        road_name = f"Grid Sector {zone_id}"

    # Calculate travel times using risk score as a proxy for congestion delay
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
        nearby_pois=pois
    )
