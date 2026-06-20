"""
Self-Validating Agent endpoint (planner EXECUTION_PLANNER L1451).

Serves the agent's calibration of congestion scores against real MapMyIndia
travel-time data: a run summary plus the per-zone reasoning log.
"""

from fastapi import APIRouter
from backend.app.data_loader import store

router = APIRouter()


@router.get("/agent/validation-report")
def validation_report():
    """Self-validating agent: calibration summary + per-zone reasoning."""
    return store.agent_report()
