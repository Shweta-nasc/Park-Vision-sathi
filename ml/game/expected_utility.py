"""
expected_utility.py – Violator Expected Utility & Adaptation Model
===================================================================

Models the ATTACKER (violator) side of the Stackelberg game.

ADDITIONS vs v1
---------------
- Corrected PROJECT_ROOT path (was .parent × 3, now .parent × 2).
- ``adaptation_response`` column (NEW): categorical label for how the
  rational violator responds —
    'park_illegally'   if violator_risk_score >= 60 (high net benefit)
    'search_legal'     if score < 40 (low net benefit; risk not worth it)
    'uncertain'        otherwise
  This is used by the spillover simulation to decide which zones become
  displaced destinations.
- Merged output also exported to ``data/violator_utility.json`` for
  the frontend "violator heatmap" overlay.
"""

from pathlib import Path
import json
import sqlite3
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH      = PROJECT_ROOT / "data" / "parkvision.db"
JSON_OUT     = PROJECT_ROOT / "data" / "violator_utility.json"

FINE_AMOUNT       = 500   # ₹500
TIME_VALUE_PER_MIN = 20   # ₹20/min
MAX_TIME_SAVED    = 22.5
SIGMOID_SCALE     = 100


def load_stackelberg(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT grid_cell_id, hour, grid_lat, grid_lon, patrol_probability "
        "FROM game_stackelberg", conn
    )


def load_risk_scores(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT grid_cell_id, hour, road_importance, peak_weight "
        "FROM risk_scores", conn
    )


def compute_violator_utility(stack_df: pd.DataFrame,
                              risk_df: pd.DataFrame) -> pd.DataFrame:
    merged = stack_df.merge(risk_df, on=["grid_cell_id", "hour"], how="left")
    merged["road_importance"] = merged["road_importance"].fillna(0.5)
    merged["peak_weight"]     = merged["peak_weight"].fillna(1.0)

    merged["time_saved"]   = (merged["road_importance"] * merged["peak_weight"] * 15
                               ).clip(upper=MAX_TIME_SAVED)
    merged["search_time"]  = 5 + (1 - merged["road_importance"]) * 10
    merged["benefit"]      = merged["time_saved"] - merged["search_time"]
    merged["expected_cost"]= merged["patrol_probability"] * FINE_AMOUNT
    merged["net_benefit"]  = merged["benefit"] * TIME_VALUE_PER_MIN - merged["expected_cost"]

    merged["violator_risk_score"] = (
        100 / (1 + np.exp(-merged["net_benefit"] / SIGMOID_SCALE))
    )

    # ── Adaptation response (NEW) ──────────────────────────────────────────
    merged["adaptation_response"] = pd.cut(
        merged["violator_risk_score"],
        bins=[-0.01, 40, 60, 100.01],
        labels=["search_legal", "uncertain", "park_illegally"],
    )

    return merged[[
        "grid_cell_id", "hour", "grid_lat", "grid_lon",
        "time_saved", "search_time", "benefit",
        "expected_cost", "net_benefit",
        "violator_risk_score", "adaptation_response",
    ]].copy()


def export_json(df: pd.DataFrame, out_path: Path = JSON_OUT) -> None:
    """Export violator utility per hour for frontend overlay."""
    output: dict = {}
    for hour, grp in df.groupby("hour"):
        output[str(int(hour))] = [
            {
                "lat":   round(row["grid_lat"], 6),
                "lon":   round(row["grid_lon"], 6),
                "vrs":   round(float(row["violator_risk_score"]), 2),
                "resp":  str(row["adaptation_response"]),
            }
            for _, row in grp.iterrows()
        ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    print(f"[eu] JSON → {out_path}  ({out_path.stat().st_size // 1024} KB)")


def save_results(df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    df.to_sql("game_violator_adaptation", conn, if_exists="replace", index=False)
    print(f"[eu] Saved {len(df):,} rows → game_violator_adaptation")


def print_summary(df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("VIOLATOR UTILITY SUMMARY")
    print("=" * 70)
    print(f"  VRS  min={df['violator_risk_score'].min():.2f}  "
          f"mean={df['violator_risk_score'].mean():.2f}  "
          f"max={df['violator_risk_score'].max():.2f}")
    print("\n  Adaptation response distribution:")
    for label, cnt in df["adaptation_response"].value_counts().items():
        pct = cnt / len(df) * 100
        print(f"    {label:<20} {cnt:>8,}  ({pct:.1f}%)")


def run() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        stack_df = load_stackelberg(conn)
        risk_df  = load_risk_scores(conn)
        result   = compute_violator_utility(stack_df, risk_df)
        save_results(result, conn)
        conn.commit()
        export_json(result)
        print_summary(result)

        assert result["violator_risk_score"].between(0, 100).all()
        print("\n  ✓ All VRS in [0, 100]")
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    run()
