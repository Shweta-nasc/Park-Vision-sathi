"""
validation_agent.py – Self-Validating Congestion Agent for ParkVisionSaathi.

Agentic validation loop: compares the model's congestion-risk scores against
REAL MapMyIndia / Mappls travel-time data, identifies discrepancies, and
calibrates each zone's score with a human-readable reasoning line.

Inputs (both real, already present):
  - risk_scores   (SQLite table)               → model congestion-risk per zone
  - data/enriched/traffic_context.json (Mappls) → real travel_time_ratio per zone

Outputs:
  - data/processed/calibrated_scores.json  {grid_cell_id: {raw, calibrated, ...}}
  - data/processed/agent_log.json          {summary, log[]}

NOTE (ownership): the EXECUTION_PLANNER assigns this self-validating agent to
Person 2 (ML). It is built here because BOTH of its inputs were already complete
and real — Person 2 should review/own it going forward. No model retraining is
involved; this is a deterministic calibration over existing artifacts.
"""

from __future__ import annotations

import json
import sqlite3
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"
MAPPLS_JSON = PROJECT_ROOT / "data" / "enriched" / "traffic_context.json"
OUT_DIR = PROJECT_ROOT / "data" / "processed"
CALIBRATED_JSON = OUT_DIR / "calibrated_scores.json"
AGENT_LOG_JSON = OUT_DIR / "agent_log.json"

# Trust weight for Mappls data when calibrating the model score.
ALPHA = 0.3
# Only calibrate a zone if a Mappls-enriched zone lies within this distance.
MAX_MATCH_KM = 0.8


# ── Geo helper ──────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


# ── Loaders ───────────────────────────────────────────────────────────────

def load_zone_scores(conn: sqlite3.Connection) -> pd.DataFrame:
    """Aggregate risk score to one row per zone (mean across hours)."""
    return pd.read_sql_query(
        """
        SELECT grid_cell_id,
               AVG(risk_score) AS raw_score,
               AVG(grid_lat)   AS lat,
               AVG(grid_lon)   AS lon
        FROM risk_scores
        GROUP BY grid_cell_id
        """,
        conn,
    )


def load_mappls_zones() -> list[dict]:
    if not MAPPLS_JSON.exists():
        return []
    with open(MAPPLS_JSON) as f:
        data = json.load(f)
    return [
        z for z in data.values()
        if z.get("lat") is not None and z.get("lon") is not None
        and z.get("travel_time_ratio") is not None
    ]


def _nearest_mappls(lat: float, lon: float, mappls: list[dict]) -> dict | None:
    best, best_d = None, MAX_MATCH_KM
    for z in mappls:
        d = _haversine_km(lat, lon, z["lat"], z["lon"])
        if d < best_d:
            best, best_d = z, d
    return best


# ── Calibration core ─────────────────────────────────────────────────────

def validate_and_calibrate(zones: pd.DataFrame, mappls: list[dict]) -> tuple[dict, list]:
    calibrated: dict[str, dict] = {}
    agent_log: list[dict] = []

    for _, row in zones.iterrows():
        zone_id = row["grid_cell_id"]
        raw = float(row["raw_score"])
        match = _nearest_mappls(row["lat"], row["lon"], mappls) if mappls else None

        if not match:
            calibrated[zone_id] = {
                "raw_score": round(raw, 2),
                "calibrated_score": round(raw, 2),
                "validated": False,
                "reasoning": "No nearby Mappls traffic data — using model prediction only.",
            }
            continue

        actual_ratio = float(match["travel_time_ratio"])
        expected_ratio = 1.0 + (raw / 100.0) * 2.0
        discrepancy = actual_ratio - expected_ratio
        adjustment = ALPHA * (discrepancy / max(expected_ratio, 1.0))
        calibrated_score = max(0.0, min(100.0, raw * (1 + adjustment)))

        if discrepancy > 0.3:
            reasoning = (
                f"Adjusted UP {raw:.0f}->{calibrated_score:.0f}: Mappls shows "
                f"{actual_ratio:.2f}x travel time near {match.get('road_name', 'this road')}, "
                f"worse than predicted — parking impact UNDERESTIMATED."
            )
        elif discrepancy < -0.3:
            reasoning = (
                f"Adjusted DOWN {raw:.0f}->{calibrated_score:.0f}: Mappls shows only "
                f"{actual_ratio:.2f}x near {match.get('road_name', 'this road')} despite high "
                f"violations — wide road may absorb the parking impact."
            )
        else:
            reasoning = (
                f"Validated: model score {raw:.0f} matches Mappls "
                f"({actual_ratio:.2f}x travel time near {match.get('road_name', 'this road')})."
            )

        calibrated[zone_id] = {
            "raw_score": round(raw, 2),
            "calibrated_score": round(calibrated_score, 2),
            "validated": True,
            "mappls_ratio": round(actual_ratio, 3),
            "matched_road": match.get("road_name"),
            "adjustment": round(adjustment, 4),
            "reasoning": reasoning,
        }
        agent_log.append({"zone_id": zone_id, "reasoning": reasoning})

    return calibrated, agent_log


def build_summary(calibrated: dict, agent_log: list) -> dict:
    validated = [v for v in calibrated.values() if v["validated"]]
    return {
        "total_zones": len(calibrated),
        "validated": len(validated),
        "accurate": sum(1 for v in validated if abs(v.get("adjustment", 0)) <= 0.05),
        "adjusted_up": sum(1 for v in validated if v.get("adjustment", 0) > 0.05),
        "adjusted_down": sum(1 for v in validated if v.get("adjustment", 0) < -0.05),
        "log": agent_log,
    }


# ── Main ────────────────────────────────────────────────────────────────────

def run() -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        zones = load_zone_scores(conn)
    finally:
        conn.close()

    mappls = load_mappls_zones()
    print(f"[agent] Loaded {len(zones):,} zones and {len(mappls)} Mappls-enriched zones.")

    calibrated, agent_log = validate_and_calibrate(zones, mappls)
    summary = build_summary(calibrated, agent_log)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CALIBRATED_JSON, "w") as f:
        json.dump(calibrated, f, separators=(",", ":"))
    with open(AGENT_LOG_JSON, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[agent] Calibrated scores → {CALIBRATED_JSON}")
    print(f"[agent] Agent log         → {AGENT_LOG_JSON}")
    print(f"[agent] {summary['validated']} validated "
          f"({summary['accurate']} accurate, {summary['adjusted_up']} up, "
          f"{summary['adjusted_down']} down) of {summary['total_zones']} zones.")
    return summary


if __name__ == "__main__":
    run()
