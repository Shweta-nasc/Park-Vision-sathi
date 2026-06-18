"""
risk_score.py – Composite risk-score computation for ParkVisionSaathi.

Workflow
--------
1. Load violations from SQLite (data/parkvision.db).
2. Aggregate per (grid_cell_id, hour):
   - violation density (normalised 0-1 within each hour)
   - peak-hour weight (1.5 for rush hours 8-10 & 17-19, else 1.0)
   - repeat-offender weight (vehicles with >1 violation in last 7 days)
   - mean validation_trust per cell-hour
   - mean vehicle_severity (heavy-vehicle ratio) per cell-hour
   - road importance proxy (junction present → 0.8, else 0.4)
3. Combine into a weighted risk score (0-100) and label LOW / MEDIUM / HIGH.
4. Save to ``risk_scores`` table with an index on (grid_cell_id, hour).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
W_DENSITY = 0.35
W_ROAD_IMP = 0.15
W_PEAK = 0.15
W_REPEAT = 0.20
W_TRUST = 0.15
SUM_WEIGHTS = W_DENSITY + W_ROAD_IMP + W_PEAK + W_REPEAT + W_TRUST

# Peak hours
PEAK_HOURS = {8, 9, 10, 17, 18, 19}

# Road importance proxy
ROAD_IMP_JUNCTION = 0.8
ROAD_IMP_NO_JUNCTION = 0.4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_violations(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load columns required for risk scoring."""
    query = """
        SELECT
            grid_cell_id,
            grid_lat,
            grid_lon,
            hour,
            junction_name,
            vehicle_severity,
            validation_trust,
            date
        FROM violations
        WHERE grid_cell_id IS NOT NULL
          AND hour IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    print(f"  Loaded {len(df):,} violations for risk scoring.")
    return df


def _compute_repeat_offender(df: pd.DataFrame, conn: sqlite3.Connection) -> pd.DataFrame:
    """Compute repeat-offender ratio per (grid_cell_id, hour).

    A "repeat offender" is approximated as a violation from a location
    that has more than one violation within a 7-day window. Since we don't
    have a unique vehicle identifier, we approximate by counting violations
    per (grid_cell_id, date) and flagging dates with >1 violation per cell.
    The ratio is (repeat-violation-count / total-count) per cell-hour.
    """
    # We use the date column to compute 7-day rolling counts per grid cell.
    # For simplicity we compute an overall repeat ratio per cell.
    repeat_query = """
        WITH cell_date_counts AS (
            SELECT
                grid_cell_id,
                hour,
                date,
                COUNT(*) AS daily_count
            FROM violations
            WHERE grid_cell_id IS NOT NULL AND hour IS NOT NULL AND date IS NOT NULL
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
    repeat_df = pd.read_sql_query(repeat_query, conn)
    return repeat_df


def _compute_risk_scores(df: pd.DataFrame, repeat_df: pd.DataFrame) -> pd.DataFrame:
    """Build per-cell-hour risk scores."""
    # ---- Base aggregations per (grid_cell_id, hour) -----------------------
    agg = (
        df.groupby(["grid_cell_id", "hour"])
        .agg(
            grid_lat=("grid_lat", "first"),
            grid_lon=("grid_lon", "first"),
            violation_count=("grid_cell_id", "size"),
            validation_trust=("validation_trust", "mean"),
            heavy_vehicle_ratio=("vehicle_severity", "mean"),
            has_junction=(
                "junction_name",
                lambda s: int((s.fillna("No Junction") != "No Junction").any()),
            ),
        )
        .reset_index()
    )

    # ---- Density (normalised 0-1 within each hour) -----------------------
    max_per_hour = agg.groupby("hour")["violation_count"].transform("max")
    agg["density"] = np.where(
        max_per_hour > 0, agg["violation_count"] / max_per_hour, 0.0
    )

    # ---- Road importance --------------------------------------------------
    agg["road_importance"] = np.where(
        agg["has_junction"] == 1, ROAD_IMP_JUNCTION, ROAD_IMP_NO_JUNCTION
    )

    # ---- Peak hour weight -------------------------------------------------
    agg["peak_weight"] = agg["hour"].apply(
        lambda h: 1.5 if h in PEAK_HOURS else 1.0
    )
    # Normalise to 0-1 range for scoring (1.0 → 0.667, 1.5 → 1.0)
    agg["peak_norm"] = (agg["peak_weight"] - 1.0) / 0.5  # 0.0 or 1.0

    # ---- Repeat offender --------------------------------------------------
    agg = agg.merge(repeat_df, on=["grid_cell_id", "hour"], how="left")
    agg["repeat_offender"] = agg["repeat_ratio"].fillna(0.0)
    agg.drop(columns=["repeat_ratio"], inplace=True)

    # ---- Fill NaN numeric cols -------------------------------------------
    agg["validation_trust"] = agg["validation_trust"].fillna(0.5)
    agg["heavy_vehicle_ratio"] = agg["heavy_vehicle_ratio"].fillna(0.5)

    # ---- Composite score --------------------------------------------------
    raw_score = (
        W_DENSITY * agg["density"]
        + W_ROAD_IMP * agg["road_importance"]
        + W_PEAK * agg["peak_norm"]
        + W_REPEAT * agg["repeat_offender"]
        + W_TRUST * agg["validation_trust"]
    ) / SUM_WEIGHTS

    # Scale to 0-100 and clip
    agg["risk_score"] = np.clip(raw_score * 100, 0, 100).round(2)

    # ---- Label ------------------------------------------------------------
    agg["risk_label"] = pd.cut(
        agg["risk_score"],
        bins=[-0.01, 33, 66, 100.01],
        labels=["LOW", "MEDIUM", "HIGH"],
    )

    # Select final columns
    result = agg[
        [
            "grid_cell_id",
            "hour",
            "grid_lat",
            "grid_lon",
            "risk_score",
            "risk_label",
            "violation_count",
            "density",
            "road_importance",
            "peak_weight",
            "repeat_offender",
            "validation_trust",
            "heavy_vehicle_ratio",
        ]
    ].copy()

    return result


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_risk_scoring(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Execute the full risk-score pipeline and persist results.

    Returns
    -------
    pd.DataFrame
        The ``risk_scores`` table written to SQLite.
    """
    print("=" * 60)
    print("Risk Score Computation")
    print("=" * 60)

    conn = sqlite3.connect(str(db_path))
    try:
        df = _load_violations(conn)
        repeat_df = _compute_repeat_offender(df, conn)
        print(f"  Computed repeat-offender ratios for {len(repeat_df):,} cell-hour combos.")

        risk_df = _compute_risk_scores(df, repeat_df)

        # ---- Persist -------------------------------------------------------
        risk_df.to_sql("risk_scores", conn, if_exists="replace", index=False)
        print(f"\n  ✓ Saved {len(risk_df):,} rows to 'risk_scores'.")

        # ---- Create index ---------------------------------------------------
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_risk_cell_hour "
            "ON risk_scores (grid_cell_id, hour)"
        )
        conn.commit()
        print("  ✓ Created index idx_risk_cell_hour on (grid_cell_id, hour).")

        return risk_df
    finally:
        conn.close()


def _print_summary(risk_df: pd.DataFrame) -> None:
    """Print distribution and top-10 highest risk cells."""
    if risk_df.empty:
        print("  No risk scores to summarise.")
        return

    print("\n" + "=" * 60)
    print("Summary Statistics")
    print("=" * 60)

    # Distribution
    dist = risk_df["risk_label"].value_counts().sort_index()
    total = len(risk_df)
    print("\n  Risk-label distribution:")
    for label, cnt in dist.items():
        pct = cnt / total * 100
        print(f"    {label:8s}  {cnt:>7,}  ({pct:5.1f}%)")

    # Score stats
    print(f"\n  Score range : {risk_df['risk_score'].min():.2f} – {risk_df['risk_score'].max():.2f}")
    print(f"  Score mean  : {risk_df['risk_score'].mean():.2f}")
    print(f"  Score median: {risk_df['risk_score'].median():.2f}")

    # Top 10
    top10 = risk_df.nlargest(10, "risk_score")
    print("\n  Top-10 highest risk cells:")
    print(f"  {'grid_cell_id':>20s}  {'hour':>4s}  {'score':>6s}  {'label':>6s}  {'violations':>10s}")
    print("  " + "-" * 55)
    for _, row in top10.iterrows():
        print(
            f"  {row['grid_cell_id']:>20s}  {int(row['hour']):4d}  "
            f"{row['risk_score']:6.2f}  {row['risk_label']:>6s}  "
            f"{int(row['violation_count']):10,}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)

    result = run_risk_scoring()
    _print_summary(result)
    print("\nDone.")
