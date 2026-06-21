"""
Self-Validating Agent endpoints (planner EXECUTION_PLANNER L1451).

Serves the Self-Validating Congestion Agent's output: a calibration summary +
per-zone reasoning log produced by comparing model congestion scores against REAL
MapMyIndia travel-time data (ml/agent/validation_agent.py →
data/processed/calibrated_scores.json + agent_log.json).

  GET /agent/validation-report -> DataStore-backed summary + per-zone calibration
                                  (in-memory, no DB — the verified data flow).
  GET /agent/calibration       -> reasoning log: summary + up to `limit` lines
                                  (consumed by the frontend agent panel).
  GET /agent/calibrated_scores -> per-zone raw vs Mappls-calibrated scores.

The /agent/calibration and /agent/calibrated_scores endpoints read the committed
JSON artifacts directly so the frontend agent panel can render them; everything
stays offline and database-free.
"""

import json
from pathlib import Path

from fastapi import APIRouter
from backend.app.data_loader import store

router = APIRouter()

_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "processed"
AGENT_LOG_PATH = _DATA_DIR / "agent_log.json"
CALIBRATED_PATH = _DATA_DIR / "calibrated_scores.json"


@router.get("/agent/validation-report", tags=["Agent"])
def validation_report():
    """Self-validating agent: calibration summary + per-zone reasoning (DataStore)."""
    return store.agent_report()


@router.get("/agent/calibration", tags=["Agent"])
def calibration_log(limit: int = 50):
    """Self-Validating Agent reasoning log — per-zone calibration against Mappls traffic.

    Returns the summary plus up to `limit` reasoning lines (validated zones first).
    Reads ``data/processed/agent_log.json`` directly (offline, no DB).
    """
    if not AGENT_LOG_PATH.exists():
        return {
            "available": False,
            "detail": "Calibration not yet run. Execute ml/agent/validation_agent.py.",
            "summary": None,
            "log": [],
        }
    with open(AGENT_LOG_PATH) as f:
        data = json.load(f)
    log = data.get("log", [])
    return {
        "available": True,
        "summary": {k: v for k, v in data.items() if k != "log"},
        "log": log[:limit],
    }


@router.get("/agent/calibrated_scores", tags=["Agent"])
def calibrated_scores(validated_only: bool = False):
    """Per-zone calibrated congestion scores (raw vs Mappls-calibrated).

    Reads ``data/processed/calibrated_scores.json`` directly (offline, no DB).
    """
    if not CALIBRATED_PATH.exists():
        return {"available": False, "scores": {}}
    with open(CALIBRATED_PATH) as f:
        scores = json.load(f)
    if validated_only:
        scores = {k: v for k, v in scores.items() if v.get("validated")}
    return {"available": True, "count": len(scores), "scores": scores}
