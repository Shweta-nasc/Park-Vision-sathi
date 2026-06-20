"""
Simulation endpoint — patrol-team allocation with coverage + waterbed spillover.
Served from the in-memory DataStore. No database.
"""

from fastapi import APIRouter
from backend.app.data_loader import store
from backend.app.models import (SimulationRequest, SimulationResponse,
                                TeamAssignment, SpilloverZone)

router = APIRouter()


@router.post("/simulate", response_model=SimulationResponse)
def run_simulation(req: SimulationRequest):
    """Allocate `num_teams` to the highest-impact zones; report coverage + spillover."""
    sim = store.simulate(req.num_teams, req.hour, req.strategy)

    return SimulationResponse(
        num_teams=sim["num_teams"],
        hour=sim["hour"],
        strategy=sim["strategy"],
        assignments=[TeamAssignment(**a) for a in sim["assignments"]],
        uncovered_high_risk=sim["uncovered_high_risk"],
        coverage_pct=sim["coverage_pct"],
        total_risk_covered=sim["total_risk_covered"],
        spillover_zones=[SpilloverZone(**s) for s in sim["spillover_zones"]],
    )
