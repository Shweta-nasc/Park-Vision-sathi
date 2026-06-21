"""
Explain endpoint — natural-language zone explanation for field officers.

Resolves BOTH zone universes the API serves:
  • the legacy hotspot zones (in-memory `store.zone`), and
  • the 2,527 real Congestion Impact Score (CIS) zones (`store.congestion_breakdown`).

Tiered and offline-safe (planner design — survives a dead internet connection):
  1. cache        → pre-generated explanation (data/processed/explanations_cache.json)
  2. live Gemini  → ONLY when GEMINI_API_KEY is set; lazy-imported, any failure is
                    swallowed and we fall through. Disabled/absent by default so the
                    demo never depends on quota or the network.
  3. fallback     → a grounded template built ONLY from the zone's real fields
                    (no hallucination, no network).
"""

import logging
import os

from fastapi import APIRouter

from backend.app.data_loader import store
from backend.app.models import ExplainRequest, ExplainResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_zone(zone_id: str) -> dict | None:
    """Normalize a legacy hotspot zone OR a real CIS zone into one explain shape.

    Returns ``None`` only when the id is in neither universe.
    """
    z = store.zone(zone_id)  # legacy hotspot zone (15)
    if z:
        return {
            "zone_id": z.get("grid_cell_id", zone_id),
            "station": z.get("station"),
            "road_name": z.get("road_name"),
            "congestion_impact": z.get("congestion_impact") or z.get("risk_score"),
            "impact_band": z.get("impact_band"),
            "violation_count": z.get("violation_count"),
            "top_violation": z.get("top_violation"),
            "estimated_lane_hours_blocked": z.get("estimated_lane_hours_blocked"),
            "travel_time_ratio": z.get("travel_time_ratio"),
            "calibrated_score": z.get("calibrated_score"),
            "nearby_pois": z.get("nearby_pois", []),
        }

    b = store.congestion_breakdown(zone_id)  # real CIS zone (2,527)
    if b:
        top = b.get("top_violations") or []
        return {
            "zone_id": b.get("zone_id", zone_id),
            "station": b.get("station"),
            "road_name": None,
            "congestion_impact": b.get("congestion_impact"),
            "impact_band": b.get("impact_band"),
            "violation_count": b.get("total_records"),
            "top_violation": top[0] if top else None,
            "estimated_lane_hours_blocked": b.get("estimated_lane_hours_blocked"),
            "travel_time_ratio": b.get("mappls_travel_time_ratio"),
            "calibrated_score": b.get("calibrated_impact"),
            "nearby_pois": [],
        }
    return None


def _grounded_fallback(z: dict, hour: int) -> str:
    """A factual explanation built only from the zone's real data (no LLM, no net)."""
    score = z.get("congestion_impact") or 0.0
    ratio = z.get("travel_time_ratio")
    ratio_txt = (
        f"MapMyIndia measures a {ratio:.2f}x travel-time ratio here"
        if ratio else "MapMyIndia travel-time data is unavailable for this zone"
    )
    calibrated = z.get("calibrated_score")
    calibrated_txt = (
        f"; the self-validating agent calibrates the score to {calibrated:.0f}/100 against that live reading"
        if isinstance(calibrated, (int, float)) else ""
    )
    road = z.get("road_name") or "this corridor"
    lane_hours = z.get("estimated_lane_hours_blocked") or 0
    return (
        f"Zone {z['zone_id']} on {road} ({z.get('station') or 'Unknown'} PS) scores "
        f"{score:.0f}/100 on the Congestion Impact Index — {z.get('impact_band') or 'N/A'} band — "
        f"at {hour:02d}:00 IST. It recorded {int(z.get('violation_count') or 0):,} violations "
        f"(top type: {z.get('top_violation') or 'N/A'}) and an estimated {lane_hours} lane-hours "
        f"blocked per day. {ratio_txt}{calibrated_txt}. "
        f"Recommended: targeted enforcement during the morning peak around this zone."
    )


def _live_gemini(z: dict, hour: int) -> str | None:
    """Optional live Gemini tier — only attempted when GEMINI_API_KEY is set.

    Lazy-imports the client so the dependency is never required for the API to
    boot or serve, and swallows every error so a quota/network failure silently
    falls through to the grounded fallback (offline-safe).
    """
    if not os.getenv("GEMINI_API_KEY"):
        return None
    try:
        from ml.llm.gemini_client import GeminiClient
        traffic = {
            "travel_time_ratio": z.get("travel_time_ratio") or 1.0,
            "road_name": z.get("road_name"),
            "nearby_pois": z.get("nearby_pois", []),
        }
        result = GeminiClient().explain_zone(z, traffic, hour=hour)
        if result and result.get("source") == "gemini" and result.get("explanation"):
            return result["explanation"]
    except Exception as e:  # pragma: no cover - defensive, demo must never break
        logger.warning("Live Gemini explain failed for %s: %s", z.get("zone_id"), e)
    return None


@router.post("/explain", response_model=ExplainResponse)
def explain_zone(req: ExplainRequest):
    """Cached explanation → optional live Gemini → grounded fallback."""
    cached = store.ensure().explanations.get(req.zone_id)
    if cached and cached.get("explanation"):
        return ExplainResponse(
            zone_id=req.zone_id,
            explanation=cached["explanation"],
            is_cached=True,
            source=cached.get("source", "cache"),
        )

    z = _resolve_zone(req.zone_id)
    if not z:
        return ExplainResponse(
            zone_id=req.zone_id,
            explanation=f"No congestion data is available for zone {req.zone_id} at {req.hour:02d}:00 IST.",
            is_cached=False,
            source="fallback",
        )

    live = _live_gemini(z, req.hour)
    if live:
        return ExplainResponse(
            zone_id=req.zone_id, explanation=live, is_cached=False, source="gemini",
        )

    return ExplainResponse(
        zone_id=req.zone_id,
        explanation=_grounded_fallback(z, req.hour),
        is_cached=False,
        source="fallback",
    )
