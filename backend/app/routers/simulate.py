"""
Simulation endpoint – Colonel Blotto patrol team allocation.
"""

from fastapi import APIRouter
from backend.app.db import query_df
from backend.app.models import SimulationRequest, SimulationResponse, TeamAssignment, SpilloverZone

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

    # Get spillover data for assigned zones
    assigned_ids = [a.grid_cell_id for a in assignments]
    if assigned_ids:
        placeholders = ",".join(["?" for _ in assigned_ids])
        spillover_data = query_df(f"""
            SELECT grid_cell_id, grid_lat, grid_lon,
                   original_risk, adjusted_risk,
                   risk_change_pct, spillover_type
            FROM game_spillover
            WHERE hour = ?
              AND spillover_type IN ('neighbor_1', 'neighbor_2')
              AND grid_cell_id NOT IN ({placeholders})
              AND ABS(risk_change_pct) > 3
            ORDER BY risk_change_pct DESC
            LIMIT 30
        """, (req.hour, *assigned_ids))
    else:
        spillover_data = []

    # Map database records to SpilloverZone objects
    spillover_zones = [
        SpilloverZone(
            grid_cell_id=row["grid_cell_id"],
            grid_lat=row["grid_lat"],
            grid_lon=row["grid_lon"],
            original_risk=row["original_risk"],
            adjusted_risk=row["adjusted_risk"],
            risk_change_pct=row["risk_change_pct"],
            spillover_type=row["spillover_type"]
        )
        for row in spillover_data
    ]

    return SimulationResponse(
        num_teams=req.num_teams,
        hour=req.hour,
        strategy=req.strategy,
        assignments=assignments,
        uncovered_high_risk=uncovered[:20],  # top 20 uncovered
        coverage_pct=coverage_pct,
        total_risk_covered=round(covered_risk, 2),
        spillover_zones=spillover_zones,
    )

