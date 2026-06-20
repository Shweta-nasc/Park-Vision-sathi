"""
Explain endpoint – returns dynamic explanation text for a zone's congestion risk.
"""

from fastapi import APIRouter
from backend.app.db import query_df
from backend.app.models import ExplainRequest, ExplainResponse

router = APIRouter()


@router.post("/explain", response_model=ExplainResponse)
def explain_zone(req: ExplainRequest):
    """Get dynamic, data-driven explanations of congestion risk for a zone."""
    # Fetch risk details for this zone to generate a realistic explanation
    zone_data = query_df("""
        SELECT risk_score, risk_label, violation_count, road_importance, repeat_offender, heavy_vehicle_ratio
        FROM risk_scores
        WHERE grid_cell_id = ? AND hour = ?
    """, (req.zone_id, req.hour))

    if zone_data:
        z = zone_data[0]
        score = z["risk_score"]
        label = z["risk_label"]
        violations = z["violation_count"]
        importance = z["road_importance"]
        repeat = z["repeat_offender"]
        heavy = z["heavy_vehicle_ratio"]

        explanation = (
            f"Zone {req.zone_id} is classified as a {label} congestion risk area (Score: {score:.1f}/100) at hour {req.hour:02d}:00. "
            f"There are currently {violations} active parking violations recorded in this sector. "
            f"The congestion risk is driven by a high road importance weight of {importance:.2f} (key transit channel) "
            f"and a repeat offender index of {repeat:.2f}. "
        )
        if heavy > 0.15:
            explanation += f"Additionally, heavy vehicle obstruction (ratio: {heavy:.1%}) contributes significantly to the bottleneck."
        else:
            explanation += "The layout and frequency of double parking violations block active vehicle lanes."
    else:
        # Fallback check on raw violations count
        violations_data = query_df("""
            SELECT COUNT(*) as cnt
            FROM violations
            WHERE grid_cell_id = ?
        """, (req.zone_id,))
        if violations_data and violations_data[0]["cnt"] > 0:
            cnt = violations_data[0]["cnt"]
            explanation = (
                f"Zone {req.zone_id} has {cnt} historically recorded violations. "
                f"No active risk score calculations are registered for hour {req.hour:02d}:00, but historical density indicates regular parking congestion."
            )
        else:
            explanation = f"No active or historical traffic violation/risk data is available for Zone {req.zone_id} at hour {req.hour:02d}:00."

    return ExplainResponse(
        zone_id=req.zone_id,
        explanation=explanation,
        is_cached=True,
        source="cache"
    )
