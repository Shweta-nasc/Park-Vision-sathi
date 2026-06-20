"""
Agent self-validation endpoint.

Serves the Self-Validating Congestion Agent's output: a calibration summary +
per-zone reasoning log produced by comparing model congestion-risk scores against
REAL Mappls travel-time data (ml/agent/validation_agent.py →
data/processed/calibrated_scores.json + agent_log.json).

Also runs live data-integrity checks (tables, score ranges, model accuracy,
cross-table consistency) so the system can demonstrate that it validates itself.
"""

import json
from pathlib import Path

from fastapi import APIRouter
from backend.app.db import query_df, table_exists

router = APIRouter()

_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "processed"
AGENT_LOG_PATH = _DATA_DIR / "agent_log.json"
CALIBRATED_PATH = _DATA_DIR / "calibrated_scores.json"

EXPECTED_TABLES = [
    "violations",
    "risk_scores",
    "hotspot_clusters",
    "game_stackelberg",
    "game_violator_adaptation",
    "game_spillover",
]


def _scalar(sql: str, params: tuple = ()):
    rows = query_df(sql, params)
    if not rows:
        return None
    return next(iter(rows[0].values()))


def _check(name: str, status: str, detail: str, value=None) -> dict:
    return {"check": name, "status": status, "detail": detail, "value": value}


@router.get("/agent/validation-report", tags=["Agent"])
def validation_report():
    """Run integrity + accuracy checks and return a structured report."""
    checks: list[dict] = []

    # ── 1. Required tables present ───────────────────────────────────────────
    missing = [t for t in EXPECTED_TABLES if not table_exists(t)]
    checks.append(_check(
        "tables_present",
        "pass" if not missing else "fail",
        "All expected tables exist" if not missing else f"Missing tables: {missing}",
        value={"expected": len(EXPECTED_TABLES), "missing": missing},
    ))

    # ── 2. Violations populated ──────────────────────────────────────────────
    if table_exists("violations"):
        n_viol = _scalar("SELECT COUNT(*) FROM violations") or 0
        n_stations = _scalar(
            "SELECT COUNT(DISTINCT police_station) FROM violations WHERE police_station IS NOT NULL"
        ) or 0
        checks.append(_check(
            "violations_populated",
            "pass" if n_viol > 0 else "fail",
            f"{n_viol:,} violation records across {n_stations} stations",
            value={"records": n_viol, "stations": n_stations},
        ))

    # ── 3. Risk scores within valid 0–100 range ──────────────────────────────
    if table_exists("risk_scores"):
        bad = _scalar(
            "SELECT COUNT(*) FROM risk_scores WHERE risk_score < 0 OR risk_score > 100"
        ) or 0
        n_zones = _scalar("SELECT COUNT(DISTINCT grid_cell_id) FROM risk_scores") or 0
        checks.append(_check(
            "risk_score_range",
            "pass" if bad == 0 else "fail",
            f"{n_zones} zones scored; {bad} out-of-range values",
            value={"zones": n_zones, "out_of_range": bad},
        ))

    # ── 4. Stackelberg patrol probabilities sum sanity per hour ──────────────
    if table_exists("game_stackelberg"):
        prob_max = _scalar("SELECT MAX(patrol_probability) FROM game_stackelberg")
        prob_min = _scalar("SELECT MIN(patrol_probability) FROM game_stackelberg")
        ok = prob_max is not None and 0 <= prob_min <= prob_max <= 1.0001
        checks.append(_check(
            "patrol_probability_range",
            "pass" if ok else "warn",
            f"patrol_probability in [{prob_min}, {prob_max}]",
            value={"min": prob_min, "max": prob_max},
        ))

    # ── 5. Forecast model accuracy ───────────────────────────────────────────
    if table_exists("forecast_predictions"):
        acc = query_df("""
            SELECT COUNT(*) as n,
                   ROUND(AVG(ABS(actual - predicted)), 4) as mae,
                   ROUND(AVG((actual - predicted)*(actual - predicted)), 4) as mse
            FROM forecast_predictions WHERE actual IS NOT NULL
        """)
        if acc and acc[0]["n"]:
            r = acc[0]
            rmse = round(r["mse"] ** 0.5, 4) if r["mse"] else None
            status = "pass" if (r["mae"] is not None and r["mae"] < 2.0) else "warn"
            checks.append(_check(
                "forecast_accuracy",
                status,
                f"MAE {r['mae']}, RMSE {rmse} over {r['n']:,} validated predictions",
                value={"mae": r["mae"], "rmse": rmse, "n": r["n"]},
            ))
        else:
            checks.append(_check(
                "forecast_accuracy", "warn",
                "Forecast table present but no validated (actual) rows", value=None,
            ))
    else:
        checks.append(_check(
            "forecast_accuracy", "warn",
            "forecast_predictions table not found", value=None,
        ))

    # ── 6. Cross-table zone consistency (game zones ⊆ risk zones) ────────────
    if table_exists("risk_scores") and table_exists("game_stackelberg"):
        orphans = _scalar("""
            SELECT COUNT(DISTINCT s.grid_cell_id)
            FROM game_stackelberg s
            LEFT JOIN risk_scores r ON s.grid_cell_id = r.grid_cell_id
            WHERE r.grid_cell_id IS NULL
        """) or 0
        checks.append(_check(
            "zone_consistency",
            "pass" if orphans == 0 else "warn",
            f"{orphans} patrol zones have no matching risk score",
            value={"orphan_zones": orphans},
        ))

    # ── Roll-up ──────────────────────────────────────────────────────────────
    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    return {
        "overall_status": overall,
        "checks_run": len(checks),
        "passed": statuses.count("pass"),
        "warnings": statuses.count("warn"),
        "failures": statuses.count("fail"),
        "checks": checks,
        "calibration": _load_calibration_summary(),
    }


def _load_calibration_summary() -> dict:
    """Load the Self-Validating Agent's calibration summary (without the full log)."""
    if not AGENT_LOG_PATH.exists():
        return {
            "available": False,
            "detail": "Run ml/agent/validation_agent.py to calibrate scores against Mappls data.",
        }
    try:
        with open(AGENT_LOG_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"available": False, "detail": "Calibration log unreadable."}
    return {
        "available": True,
        "total_zones": data.get("total_zones"),
        "validated": data.get("validated"),
        "accurate": data.get("accurate"),
        "adjusted_up": data.get("adjusted_up"),
        "adjusted_down": data.get("adjusted_down"),
    }


@router.get("/agent/calibration", tags=["Agent"])
def calibration_log(limit: int = 50):
    """Self-Validating Agent reasoning log — per-zone calibration against Mappls traffic.

    Returns the summary plus up to `limit` reasoning lines (validated zones first).
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
    """Per-zone calibrated congestion scores (raw vs Mappls-calibrated)."""
    if not CALIBRATED_PATH.exists():
        return {"available": False, "scores": {}}
    with open(CALIBRATED_PATH) as f:
        scores = json.load(f)
    if validated_only:
        scores = {k: v for k, v in scores.items() if v.get("validated")}
    return {"available": True, "count": len(scores), "scores": scores}
