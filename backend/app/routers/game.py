"""
Game Theory endpoints: Stackelberg patrol strategy, violator adaptation,
spillover (waterbed) forecast. Served from the in-memory DataStore. No database.
"""

from fastapi import APIRouter, Query
from backend.app.data_loader import store

router = APIRouter()


@router.get("/game/stackelberg_strategy")
def get_stackelberg(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    zone_id: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Stackelberg mixed-strategy patrol probabilities (police = leader)."""
    rows = store.stackelberg(limit)
    if zone_id:
        rows = [r for r in rows if r["grid_cell_id"] == zone_id]
    return rows


@router.get("/game/violator_adaptation")
def get_violator_adaptation(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    zone_id: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Violator expected-utility / adaptation scores (violators = followers)."""
    rows = store.violators(limit)
    if zone_id:
        rows = [r for r in rows if r["grid_cell_id"] == zone_id]
    return rows


@router.get("/game/spillover_forecast")
def get_spillover(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    spillover_type: str = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
):
    """Waterbed/spillover predictions for a default 5-team enforcement."""
    rows = store.spillover_forecast(limit)
    if spillover_type:
        rows = [r for r in rows if r["spillover_type"] == spillover_type]
    return rows


@router.get("/game/summary")
def get_game_summary(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
):
    """Aggregate stats across the game-theory models."""
    sk = store.stackelberg(1000)
    vi = store.violators(1000)
    sp = store.spillover_forecast(1000)
    return {
        "hour": hour,
        "time_bucket": time_bucket,
        "stackelberg": {
            "zones": len(sk),
            "max_patrol_prob": round(max((z["patrol_probability"] for z in sk), default=0), 4),
            "avg_patrol_prob": round(sum(z["patrol_probability"] for z in sk) / len(sk), 6) if sk else 0,
        },
        "violator_adaptation": {
            "avg_violator_risk": round(sum(z["violator_risk_score"] for z in vi) / len(vi), 2) if vi else 0,
            "max_violator_risk": round(max((z["violator_risk_score"] for z in vi), default=0), 2),
            "avg_expected_cost": round(sum(z["expected_cost"] for z in vi) / len(vi), 2) if vi else 0,
        },
        "spillover_zones": len(sp),
    }


@router.get("/game/spillover_arrows")
def get_spillover_arrows():
    """Displacement arrows (top patrolled zone → nearest neighbour)."""
    return store.spillover_arrows()


@router.get("/game/whatif_coverage")
def get_whatif_coverage():
    """Coverage % across team counts (drives the simulation slider's read-out)."""
    return store.whatif_coverage()


@router.get("/game/patrol_allocation")
def get_patrol_allocation(epsilon: float = Query(default=0.10, ge=0.0, le=1.0)):
    """ε-greedy patrol allocation (bias mitigation): 90% exploit + 10% explore.

    Sends ``epsilon`` of patrol effort to under-observed zones so the system can
    discover violations the enforcement record misses. Returns per-zone
    exploit-only ``patrol_probability`` alongside the bias-mitigated
    ``patrol_probability_explore`` (which sums to 1.0), plus an honest-limitations
    note.
    """
    return store.patrol_allocation_with_exploration(epsilon=epsilon)
