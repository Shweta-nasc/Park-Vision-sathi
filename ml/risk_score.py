"""
risk_score.py – Composite risk-score computation for ParkVisionSaathi.

Workflow
--------
1. Load violations from SQLite.
2. Aggregate per (grid_cell_id, hour) across 5 components.
3. Combine into weighted risk score (0–100), label LOW/MEDIUM/HIGH/CRITICAL.
4. Save to ``risk_scores`` table with index.

ADDITIONS vs v1
---------------
- vehicle_severity (heavy-vehicle ratio) now has its OWN weight W_VEHICLE=0.10
  (previously only stored, not used in scoring).
- Weights rebalanced: sum still = 1.0.
- ``risk_tier`` column: 0/1/2/3 (numeric) for easier frontend heatmap colour mapping.
- ``risk_tier_label`` column: LOW/MEDIUM/HIGH/CRITICAL.
- CRITICAL tier added: score > 80.
- Per-hour JSON export: ``data/risk_scores_by_hour.json`` for frontend heatmap slider.
- Risk score clipped to [0, 100] with proper normalisation (SUM_WEIGHTS denominator).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"
JSON_OUT = PROJECT_ROOT / "data" / "risk_scores_by_hour.json"

# ── Weights (must sum to 1.0) ─────────────────────────────────────────────
W_DENSITY  = 0.30   # violation density (normalised within hour)
W_ROAD_IMP = 0.15   # road importance proxy (junction present?)
W_PEAK     = 0.15   # peak-hour multiplier
W_REPEAT   = 0.20   # repeat-offender ratio
W_TRUST    = 0.10   # validation trust score
W_VEHICLE  = 0.10   # heavy-vehicle ratio (NEW)
assert abs(W_DENSITY + W_ROAD_IMP + W_PEAK + W_REPEAT + W_TRUST + W_VEHICLE - 1.0) < 1e-9, \
    "Weights must sum to 1.0"

PEAK_HOURS = {8, 9, 10, 17, 18, 19}
ROAD_IMP_JUNCTION    = 0.8
ROAD_IMP_NO_JUNCTION = 0.4

# Risk tiers (score ranges)
TIER_BINS   = [-0.01, 33, 60, 80, 100.01]
TIER_LABELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
TIER_INT    = {l: i for i, l in enumerate(TIER_LABELS)}


# ── Helpers ───────────────────────────────────────────────────────────────

def _load_violations(conn: sqlite3.Connection) -> pd.DataFrame:
    query = """
        SELECT grid_cell_id, grid_lat, grid_lon,
               hour, junction_name,
               vehicle_severity, validation_trust, date
        FROM violations
        WHERE grid_cell_id IS NOT NULL AND hour IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    print(f"  Loaded {len(df):,} violations for risk scoring.")
    return df


def _compute_repeat_offender(conn: sqlite3.Connection) -> pd.DataFrame:
    """Compute repeat-offender ratio per (grid_cell_id, hour) via SQL."""
    query = """
        WITH cell_date_counts AS (
            SELECT grid_cell_id, hour, date, COUNT(*) AS daily_count
            FROM violations
            WHERE grid_cell_id IS NOT NULL
              AND hour IS NOT NULL
              AND date IS NOT NULL
            GROUP BY grid_cell_id, hour, date
        )
        SELECT
            grid_cell_id,
            hour,
            SUM(CASE WHEN daily_count > 1 THEN daily_count ELSE 0 END) * 1.0
                / SUM(daily_count) AS repeat_ratio
        FROM cell_date_counts
        GROUP BY grid_cell_id, hour
    """
    return pd.read_sql_query(query, conn)


def _compute_risk_scores(df: pd.DataFrame, repeat_df: pd.DataFrame) -> pd.DataFrame:
    # ── Aggregate ─────────────────────────────────────────────────────────
    agg = (
        df.groupby(["grid_cell_id", "hour"])
        .agg(
            grid_lat=("grid_lat", "first"),
            grid_lon=("grid_lon", "first"),
            violation_count=("grid_cell_id", "size"),
            validation_trust=("validation_trust", "mean"),
            heavy_vehicle_ratio=("vehicle_severity", "mean"),   # mean severity proxy
            has_junction=(
                "junction_name",
                lambda s: int((s.fillna("No Junction") != "No Junction").any()),
            ),
        )
        .reset_index()
    )

    # ── Violation density (0–1, normalised within hour) ───────────────────
    max_per_hour = agg.groupby("hour")["violation_count"].transform("max")
    agg["density"] = np.where(max_per_hour > 0,
                               agg["violation_count"] / max_per_hour, 0.0)

    # ── Road importance ───────────────────────────────────────────────────
    agg["road_importance"] = np.where(agg["has_junction"] == 1,
                                       ROAD_IMP_JUNCTION, ROAD_IMP_NO_JUNCTION)

    # ── Peak hour (0–1) ───────────────────────────────────────────────────
    agg["peak_weight"] = agg["hour"].apply(lambda h: 1.5 if h in PEAK_HOURS else 1.0)
    agg["peak_norm"]   = (agg["peak_weight"] - 1.0) / 0.5   # {0.0, 1.0}

    # ── Repeat offender ───────────────────────────────────────────────────
    agg = agg.merge(repeat_df, on=["grid_cell_id", "hour"], how="left")
    agg["repeat_offender"] = agg["repeat_ratio"].fillna(0.0)
    agg.drop(columns=["repeat_ratio"], inplace=True)

    # ── Fill NaN ──────────────────────────────────────────────────────────
    agg["validation_trust"]    = agg["validation_trust"].fillna(0.5)
    agg["heavy_vehicle_ratio"] = agg["heavy_vehicle_ratio"].fillna(0.5)

    # ── Composite score ───────────────────────────────────────────────────
    raw_score = (
        W_DENSITY  * agg["density"]
        + W_ROAD_IMP * agg["road_importance"]
        + W_PEAK     * agg["peak_norm"]
        + W_REPEAT   * agg["repeat_offender"]
        + W_TRUST    * agg["validation_trust"]
        + W_VEHICLE  * agg["heavy_vehicle_ratio"]   # NEW
    )  # weights already sum to 1, so raw_score is in [0,1]

    agg["risk_score"] = np.clip(raw_score * 100, 0, 100).round(2)

    # ── Tier labels ───────────────────────────────────────────────────────
    agg["risk_tier_label"] = pd.cut(
        agg["risk_score"],
        bins=TIER_BINS,
        labels=TIER_LABELS,
    )
    agg["risk_tier"] = agg["risk_tier_label"].map(TIER_INT)

    # Keep risk_label as alias (backward compat)
    agg["risk_label"] = agg["risk_tier_label"]

    return agg[[
        "grid_cell_id", "hour", "grid_lat", "grid_lon",
        "risk_score", "risk_label", "risk_tier", "risk_tier_label",
        "violation_count", "density", "road_importance", "peak_weight",
        "repeat_offender", "validation_trust", "heavy_vehicle_ratio",
    ]].copy()


def _export_json_for_frontend(risk_df: pd.DataFrame, out_path: Path) -> None:
    """
    Export per-hour risk data as JSON for the React heatmap slider.

    Format:
    {
      "data_rich_hours": [0,1,...,15],
      "hours": {
        "8": [{"lat":..., "lon":..., "risk":..., "tier":...}, ...],
        ...
      }
    }
    Only hours 0–15 exported by default (temporal cliff guard).
    """
    DATA_RICH_HOURS = list(range(16))   # 0–15 inclusive
    output: dict = {
        "data_rich_hours": DATA_RICH_HOURS,
        "hours": {}
    }

    for hour in DATA_RICH_HOURS:
        subset = risk_df[risk_df["hour"] == hour]
        if subset.empty:
            continue
        records = [
            {
                "lat":  round(row["grid_lat"], 6),
                "lon":  round(row["grid_lon"], 6),
                "risk": float(row["risk_score"]),
                "tier": int(row["risk_tier"]),
                "cell": row["grid_cell_id"],
            }
            for _, row in subset.iterrows()
        ]
        output["hours"][str(hour)] = records

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    print(f"\n  ✓ Frontend JSON exported → {out_path}  "
          f"({out_path.stat().st_size // 1024} KB)")


# ── Main pipeline ─────────────────────────────────────────────────────────

def run_risk_scoring(db_path: Path = DB_PATH) -> pd.DataFrame:
    print("=" * 60)
    print("Risk Score Computation  (ParkVisionSaathi)")
    print("=" * 60)

    conn = sqlite3.connect(str(db_path))
    try:
        df = _load_violations(conn)
        repeat_df = _compute_repeat_offender(conn)
        print(f"  Computed repeat-offender ratios for {len(repeat_df):,} cell-hour combos.")

        risk_df = _compute_risk_scores(df, repeat_df)

        # ── Persist ───────────────────────────────────────────────────────
        risk_df.to_sql("risk_scores", conn, if_exists="replace", index=False)
        print(f"\n  ✓ Saved {len(risk_df):,} rows → risk_scores")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_risk_cell_hour "
            "ON risk_scores (grid_cell_id, hour)"
        )
        conn.commit()
        print("  ✓ Index created: idx_risk_cell_hour")

        # ── JSON export for heatmap ───────────────────────────────────────
        _export_json_for_frontend(risk_df, JSON_OUT)

        return risk_df
    finally:
        conn.close()


def _print_summary(risk_df: pd.DataFrame) -> None:
    if risk_df.empty:
        return
    print("\n" + "=" * 60)
    print("Summary Statistics")
    print("=" * 60)

    dist = risk_df["risk_tier_label"].value_counts().reindex(TIER_LABELS, fill_value=0)
    total = len(risk_df)
    print("\n  Tier distribution:")
    for label, cnt in dist.items():
        pct = cnt / total * 100
        bar = "█" * int(pct / 2)
        print(f"    {label:10s} {cnt:>8,}  ({pct:5.1f}%)  {bar}")

    print(f"\n  Score: min={risk_df['risk_score'].min():.2f}  "
          f"mean={risk_df['risk_score'].mean():.2f}  "
          f"max={risk_df['risk_score'].max():.2f}")

    print("\n  Top-10 highest risk cells:")
    cols = ["grid_cell_id", "hour", "risk_score", "risk_tier_label", "violation_count"]
    print(risk_df.nlargest(10, "risk_score")[cols].to_string(index=False))


# ── Entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        print("Run:  python scripts/seed_db.py  first.")
        sys.exit(1)

    result = run_risk_scoring()
    _print_summary(result)
    print("\nDone.")
