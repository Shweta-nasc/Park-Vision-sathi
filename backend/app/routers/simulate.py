"""
Simulation endpoint – Colonel Blotto patrol team allocation.
"""

from fastapi import APIRouter
from backend.app.db import query_df
from backend.app.models import SimulationRequest, SimulationResponse, TeamAssignment

router = APIRouter()


@router.post("/simulate", response_model=SimulationResponse)
def run_simulation(req: SimulationRequest):
    """
    Allocate patrol teams to zones using Stackelberg probabilities.
    Uses a greedy allocation: assign teams to highest-probability zones,
    then merge nearby zones into team routes.
    """
    # Get Stackelberg strategy for this hour
    zones = query_df("""
        SELECT s.grid_cell_id, s.hour, s.grid_lat, s.grid_lon,
               s.risk_score, s.patrol_probability
        FROM game_stackelberg s
        WHERE s.hour = ?
        ORDER BY s.patrol_probability DESC
    """, (req.hour,))

    if not zones:
        return SimulationResponse(
            num_teams=req.num_teams, hour=req.hour, strategy=req.strategy,
            assignments=[], uncovered_high_risk=[], coverage_pct=0, total_risk_covered=0,
        )

    total_risk = sum(z["risk_score"] for z in zones)
    assignments = []
    assigned_cells = set()

    # Greedy allocation: assign each team to the highest-priority unassigned zone
    for team_id in range(1, req.num_teams + 1):
        for z in zones:
            if z["grid_cell_id"] not in assigned_cells:
                assignments.append(TeamAssignment(
                    team_id=team_id,
                    grid_cell_id=z["grid_cell_id"],
                    grid_lat=z["grid_lat"],
                    grid_lon=z["grid_lon"],
                    risk_score=z["risk_score"],
                    patrol_probability=z["patrol_probability"],
                    priority_rank=len(assignments) + 1,
                ))
                assigned_cells.add(z["grid_cell_id"])
                break

    # Identify uncovered HIGH risk zones
    uncovered = [
        {"grid_cell_id": z["grid_cell_id"], "grid_lat": z["grid_lat"],
         "grid_lon": z["grid_lon"], "risk_score": z["risk_score"]}
        for z in zones
        if z["grid_cell_id"] not in assigned_cells and z["risk_score"] >= 67
    ]

    covered_risk = sum(a.risk_score for a in assignments)
    coverage_pct = round(covered_risk / total_risk * 100, 2) if total_risk > 0 else 0

    return SimulationResponse(
        num_teams=req.num_teams,
        hour=req.hour,
        strategy=req.strategy,
        assignments=assignments,
        uncovered_high_risk=uncovered[:20],  # top 20 uncovered
        coverage_pct=coverage_pct,
        total_risk_covered=round(covered_risk, 2),
    )
