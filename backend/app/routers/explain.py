"""
Explain endpoint — natural-language zone explanation for field officers.

Three-tier, cache-first (planner design), and offline-safe:
  1. cache    → pre-generated Gemini explanation (data/processed/explanations_cache.json)
  2. fallback → a grounded template built ONLY from the zone's real fields
                (no hallucination, no network, survives a dead internet connection)

A live Gemini tier can be slotted in between via ml/llm/gemini_client; it is
intentionally not called here so the demo never depends on quota or the network.
"""

from fastapi import APIRouter
from backend.app.data_loader import store
from backend.app.models import ExplainRequest, ExplainResponse

router = APIRouter()


def _grounded_fallback(z: dict, hour: int) -> str:
    """Build a factual explanation from the zone's real data only."""
    ratio = z.get("travel_time_ratio")
    ratio_txt = (
        f"MapMyIndia measures a {ratio:.2f}x travel-time ratio here"
        if ratio else "MapMyIndia travel-time data is unavailable for this zone"
    )
    return (
        f"Zone {z['grid_cell_id']} on {z.get('road_name', 'this corridor')} "
        f"({z.get('station', 'Unknown')} PS) scores {z['risk_score']:.0f}/100 on the "
        f"Congestion Impact Index — {z['impact_band']} band — at {hour:02d}:00 IST. "
        f"It recorded {z['violation_count']:,} violations (top type: {z.get('top_violation', 'N/A')}) "
        f"and an estimated {z.get('estimated_lane_hours_blocked', 0)} lane-hours blocked per day. "
        f"{ratio_txt}; the self-validating agent calibrates the score to "
        f"{z.get('calibrated_score', z['risk_score'])}/100 against that live reading. "
        f"Recommended: targeted enforcement during the morning peak around this zone."
    )


@router.post("/explain", response_model=ExplainResponse)
def explain_zone(req: ExplainRequest):
    """Return the cached explanation for a zone, else a grounded fallback."""
    cached = store.ensure().explanations.get(req.zone_id)
    if cached and cached.get("explanation"):
        return ExplainResponse(
            zone_id=req.zone_id,
            explanation=cached["explanation"],
            is_cached=True,
            source=cached.get("source", "cache"),
        )

    z = store.zone(req.zone_id)
    if z:
        return ExplainResponse(
            zone_id=req.zone_id,
            explanation=_grounded_fallback(z, req.hour),
            is_cached=False,
            source="fallback",
        )

    return ExplainResponse(
        zone_id=req.zone_id,
        explanation=f"No congestion data is available for zone {req.zone_id} at {req.hour:02d}:00 IST.",
        is_cached=False,
        source="fallback",
    )
