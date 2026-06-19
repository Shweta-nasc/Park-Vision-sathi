"""
Game Theory endpoints: Stackelberg, Violator Adaptation, Spillover.
"""

from pathlib import Path
from fastapi import APIRouter, Query
from backend.app.db import query_df

router = APIRouter()

TIME_BUCKET_MAP = {
    "night_0_6": (0, 6),
    "morning_6_10": (6, 10),
    "midday_10_16": (10, 16),
    "evening_16_22": (16, 22),
    "night_22_24": (22, 24),
}


@router.get("/game/stackelberg_strategy")
def get_stackelberg(
    hour: int = Query(default=None, ge=0, le=23, description="Hour of day"),
    time_bucket: str = Query(default=None),
    zone_id: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get Stackelberg mixed-strategy patrol probabilities."""
    if time_bucket and time_bucket in TIME_BUCKET_MAP:
        lo, hi = TIME_BUCKET_MAP[time_bucket]
        hour_clause = "hour >= ? AND hour < ?"
        params = [lo, hi]
    elif hour is not None:
        hour_clause = "hour = ?"
        params = [hour]
    else:
        hour_clause = "1=1"
        params = []

    sql = f"SELECT * FROM game_stackelberg WHERE {hour_clause}"

    if zone_id:
        sql += " AND grid_cell_id = ?"
        params.append(zone_id)

    sql += " ORDER BY patrol_probability DESC LIMIT ?"
    params.append(limit)
    return query_df(sql, tuple(params))


@router.get("/game/violator_adaptation")
def get_violator_adaptation(
    hour: int = Query(default=None, ge=0, le=23, description="Hour of day"),
    time_bucket: str = Query(default=None),
    zone_id: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get violator expected utility and adaptation risk scores."""
    if time_bucket and time_bucket in TIME_BUCKET_MAP:
        lo, hi = TIME_BUCKET_MAP[time_bucket]
        hour_clause = "hour >= ? AND hour < ?"
        params = [lo, hi]
    elif hour is not None:
        hour_clause = "hour = ?"
        params = [hour]
    else:
        hour_clause = "1=1"
        params = []

    sql = f"SELECT * FROM game_violator_adaptation WHERE {hour_clause}"

    if zone_id:
        sql += " AND grid_cell_id = ?"
        params.append(zone_id)

    sql += " ORDER BY violator_risk_score DESC LIMIT ?"
    params.append(limit)
    return query_df(sql, tuple(params))


@router.get("/game/spillover_forecast")
def get_spillover(
    hour: int = Query(default=None, ge=0, le=23, description="Hour of day"),
    time_bucket: str = Query(default=None),
    spillover_type: str = Query(default=None, description="Filter: patrolled, neighbor_1, neighbor_2, unaffected"),
    limit: int = Query(default=200, ge=1, le=2000),
):
    """Get waterbed/spillover effect predictions."""
    if time_bucket and time_bucket in TIME_BUCKET_MAP:
        lo, hi = TIME_BUCKET_MAP[time_bucket]
        hour_clause = "hour >= ? AND hour < ?"
        params = [lo, hi]
    elif hour is not None:
        hour_clause = "hour = ?"
        params = [hour]
    else:
        hour_clause = "1=1"
        params = []

    sql = f"SELECT * FROM game_spillover WHERE {hour_clause}"

    if spillover_type:
        sql += " AND spillover_type = ?"
        params.append(spillover_type)

    sql += " ORDER BY risk_change_pct DESC LIMIT ?"
    params.append(limit)
    return query_df(sql, tuple(params))


@router.get("/game/summary")
def get_game_summary(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
):
    """Get summary of game theory outputs for a given hour or time bucket."""
    if time_bucket and time_bucket in TIME_BUCKET_MAP:
        lo, hi = TIME_BUCKET_MAP[time_bucket]
        hour_clause = "hour >= ? AND hour < ?"
        params = [lo, hi]
    elif hour is not None:
        hour_clause = "hour = ?"
        params = [hour]
    else:
        hour_clause = "1=1"
        params = []

    stackelberg = query_df(f"""
        SELECT COUNT(DISTINCT grid_cell_id) as zones,
               ROUND(MAX(patrol_probability), 4) as max_patrol_prob,
               ROUND(AVG(patrol_probability), 6) as avg_patrol_prob
        FROM game_stackelberg WHERE {hour_clause}
    """, tuple(params))

    violator = query_df(f"""
        SELECT ROUND(AVG(violator_risk_score), 2) as avg_violator_risk,
               ROUND(MAX(violator_risk_score), 2) as max_violator_risk,
               ROUND(AVG(expected_cost), 2) as avg_expected_cost
        FROM game_violator_adaptation WHERE {hour_clause}
    """, tuple(params))

    spillover = query_df(f"""
        SELECT spillover_type,
               COUNT(*) as count,
               ROUND(AVG(risk_change_pct), 2) as avg_risk_change_pct
        FROM game_spillover WHERE {hour_clause}
        GROUP BY spillover_type
    """, tuple(params))

    return {
        "hour": hour,
        "time_bucket": time_bucket,
        "stackelberg": stackelberg[0] if stackelberg else {},
        "violator_adaptation": violator[0] if violator else {},
        "spillover_by_type": spillover,
    }


@router.get("/game/spillover_arrows")
def get_spillover_arrows():
    """Get the pre-computed displacement arrows JSON."""
    import json
    path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "spillover_arrows.json"
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {"arrows": []}


@router.get("/game/whatif_coverage")
def get_whatif_coverage():
    """Get the pre-computed What-If coverage JSON."""
    import json
    path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "whatif_coverage.json"
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

