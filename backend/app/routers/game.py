"""
Game Theory endpoints: Stackelberg, Violator Adaptation, Spillover.
"""

from fastapi import APIRouter, Query
from backend.app.db import query_df

router = APIRouter()


@router.get("/game/stackelberg_strategy")
def get_stackelberg(
    hour: int = Query(ge=0, le=23, description="Hour of day"),
    zone_id: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get Stackelberg mixed-strategy patrol probabilities."""
    sql = "SELECT * FROM game_stackelberg WHERE hour = ?"
    params = [hour]

    if zone_id:
        sql += " AND grid_cell_id = ?"
        params.append(zone_id)

    sql += " ORDER BY patrol_probability DESC LIMIT ?"
    params.append(limit)
    return query_df(sql, tuple(params))


@router.get("/game/violator_adaptation")
def get_violator_adaptation(
    hour: int = Query(ge=0, le=23, description="Hour of day"),
    zone_id: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get violator expected utility and adaptation risk scores."""
    sql = "SELECT * FROM game_violator_adaptation WHERE hour = ?"
    params = [hour]

    if zone_id:
        sql += " AND grid_cell_id = ?"
        params.append(zone_id)

    sql += " ORDER BY violator_risk_score DESC LIMIT ?"
    params.append(limit)
    return query_df(sql, tuple(params))


@router.get("/game/spillover_forecast")
def get_spillover(
    hour: int = Query(ge=0, le=23, description="Hour of day"),
    spillover_type: str = Query(default=None, description="Filter: patrolled, neighbor_1, neighbor_2, unaffected"),
    limit: int = Query(default=200, ge=1, le=2000),
):
    """Get waterbed/spillover effect predictions."""
    sql = "SELECT * FROM game_spillover WHERE hour = ?"
    params = [hour]

    if spillover_type:
        sql += " AND spillover_type = ?"
        params.append(spillover_type)

    sql += " ORDER BY risk_change_pct DESC LIMIT ?"
    params.append(limit)
    return query_df(sql, tuple(params))


@router.get("/game/summary")
def get_game_summary(hour: int = Query(ge=0, le=23)):
    """Get summary of game theory outputs for a given hour."""
    stackelberg = query_df("""
        SELECT COUNT(*) as zones,
               ROUND(MAX(patrol_probability), 4) as max_patrol_prob,
               ROUND(AVG(patrol_probability), 6) as avg_patrol_prob
        FROM game_stackelberg WHERE hour = ?
    """, (hour,))

    violator = query_df("""
        SELECT ROUND(AVG(violator_risk_score), 2) as avg_violator_risk,
               ROUND(MAX(violator_risk_score), 2) as max_violator_risk,
               ROUND(AVG(expected_cost), 2) as avg_expected_cost
        FROM game_violator_adaptation WHERE hour = ?
    """, (hour,))

    spillover = query_df("""
        SELECT spillover_type,
               COUNT(*) as count,
               ROUND(AVG(risk_change_pct), 2) as avg_risk_change_pct
        FROM game_spillover WHERE hour = ?
        GROUP BY spillover_type
    """, (hour,))

    return {
        "hour": hour,
        "stackelberg": stackelberg[0] if stackelberg else {},
        "violator_adaptation": violator[0] if violator else {},
        "spillover_by_type": spillover,
    }
