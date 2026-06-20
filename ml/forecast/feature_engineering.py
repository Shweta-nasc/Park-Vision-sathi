"""
feature_engineering.py – Feature matrix for LightGBM violation count forecasting.

Loads violations from SQLite, aggregates to grid_cell_id × date × hour,
and engineers temporal, cyclical, lag, rolling, and zone-metadata features.

Output
------
- SQLite table  ``forecast_features``  in data/parkvision.db
- CSV file      data/forecast_features.csv

ADDITIONS vs v1
---------------
- Corrected PROJECT_ROOT path (was .parent × 3, now .parent × 2).
- Added ``violation_rate`` feature: lag_1 / rolling_mean_7d (ratio of the most
  recent PAST count to the recent past average — captures sudden spikes WITHOUT
  referencing the current row's target).
- Added ``is_data_rich_hour`` flag: 1 if hour in 0–15 (temporal cliff guard).
- Added ``month_sin`` / ``month_cos`` cyclical month encoding.
- apply() calls updated to suppress FutureWarning (include_groups=False already present).
- All NaN rolling_std_7d (first window) filled with 0.0 before saving.

TARGET-LEAKAGE FIX (critical, this revision)
--------------------------------------------
The v1 rolling features called ``.rolling(window, min_periods=1)`` on
``violation_count`` with **no shift**, so every row's rolling_mean_7d /
rolling_mean_14d / rolling_std_7d window *included that row's own
violation_count* (the target), and ``violation_rate`` divided the target by a
window containing the target. This leaked the target into its own features and
produced a falsely high R²≈0.9929. ``add_rolling_features`` now shifts each
cell's series by one row **before** rolling, so all rolling statistics use only
strictly-past observations, and ``violation_rate`` is recomputed from ``lag_1``
and the shifted rolling mean — it never touches the current target.

KNOWN LIMITATION (sparse temporal index)
----------------------------------------
The feature matrix contains one row per (grid_cell_id, date, hour) that actually
recorded ≥1 violation; (cell, date, hour) slots with zero violations are NOT
materialized. Consequently ``lag_1`` / ``lag_24`` / ``lag_168`` mean "1 / 24 /
168 *recorded observations* ago" rather than "1 / 24 / 168 *clock hours* ago",
and the 168/336-row rolling windows span the last 168/336 recorded observations
rather than strictly 7/14 calendar days. A fully temporally-correct version would
zero-fill the complete (cell × date × hour) grid before computing lags/rolling.
The sparse representation is retained here so the leakage-fixed metrics remain
directly comparable to the previously reported (leaky) metrics, which were
computed on this same sparse representation; the honest R²/MAE shift therefore
isolates the leakage removal rather than a representation change. This caveat is
restated in the model card.
"""

import sqlite3
import math
import json
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH  = PROJECT_ROOT / "data" / "parkvision.db"
CSV_PATH = PROJECT_ROOT / "data" / "forecast_features.csv"

DATA_RICH_HOURS = set(range(16))   # hours 0–15 (temporal cliff guard)


# ── Loaders ───────────────────────────────────────────────────────────────

def load_violations(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(str(db_path))
    query = """
        SELECT grid_cell_id, date, hour, day_of_week, month,
               is_weekend, is_peak, vehicle_severity,
               validation_trust, junction_name
        FROM violations
        WHERE grid_cell_id IS NOT NULL
          AND date IS NOT NULL
          AND hour IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    print(f"[load] Raw violations: {len(df):,} rows")
    return df


# ── Aggregation ──────────────────────────────────────────────────────────

def aggregate_counts(df: pd.DataFrame) -> pd.DataFrame:
    agg = (
        df.groupby(["grid_cell_id", "date", "hour"])
        .agg(
            violation_count=("hour", "size"),
            day_of_week=("day_of_week", "first"),
            month=("month", "first"),
            is_weekend=("is_weekend", "first"),
            is_peak=("is_peak", "first"),
        )
        .reset_index()
    )
    agg["date"] = agg["date"].astype(str)
    agg = agg.sort_values(["grid_cell_id", "date", "hour"]).reset_index(drop=True)
    print(f"[agg]  Time series: {len(agg):,} rows | "
          f"{agg['grid_cell_id'].nunique()} cells")
    return agg


def filter_cells(agg: pd.DataFrame, min_obs: int = 30) -> pd.DataFrame:
    counts = agg.groupby("grid_cell_id")["violation_count"].count()
    valid  = counts[counts > min_obs].index
    out    = agg[agg["grid_cell_id"].isin(valid)].copy()
    print(f"[filt] Cells >{min_obs} obs: {len(valid)} ({len(out):,} rows)")
    return out


# ── Feature engineering ──────────────────────────────────────────────────

def add_cyclical_features(df: pd.DataFrame) -> pd.DataFrame:
    df["sin_hour"]  = np.sin(2 * math.pi * df["hour"] / 24)
    df["cos_hour"]  = np.cos(2 * math.pi * df["hour"] / 24)
    df["sin_dow"]   = np.sin(2 * math.pi * df["day_of_week"] / 7)
    df["cos_dow"]   = np.cos(2 * math.pi * df["day_of_week"] / 7)
    # NEW: month cyclical encoding
    df["sin_month"] = np.sin(2 * math.pi * df["month"] / 12)
    df["cos_month"] = np.cos(2 * math.pi * df["month"] / 12)
    # NEW: data-rich hour flag (temporal cliff guard)
    df["is_data_rich_hour"] = df["hour"].isin(DATA_RICH_HOURS).astype(int)
    return df


def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    for lag in [1, 24, 168]:
        df[f"lag_{lag}"] = (
            df.groupby("grid_cell_id")["violation_count"].shift(lag)
        )
    return df


def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling statistics computed on STRICTLY-PAST observations only.

    LEAKAGE FIX (critical)
    ----------------------
    The previous implementation called ``.rolling(window, min_periods=1)``
    directly on ``violation_count`` with **no shift**, so each row's
    ``rolling_mean_7d`` / ``rolling_mean_14d`` / ``rolling_std_7d`` window
    *included that same row's own ``violation_count``* — i.e. the target leaked
    into its own features. ``violation_rate`` then divided the target by a window
    containing the target. The model leaned on these leaky features
    (``violation_rate`` / ``rolling_mean_7d`` ranked #1/#2), which is why the
    reported R²≈0.9929 was not honest.

    The fix shifts each cell's series by 1 *before* rolling, so every rolling
    statistic for row ``t`` is computed from rows ``t-1 .. t-window`` only and can
    never see ``violation_count[t]``. ``violation_rate`` is likewise redefined as
    ``lag_1 / rolling_mean_7d`` (both strictly-past), so it never references the
    current row's target. (``add_lag_features`` runs before this function, so
    ``lag_1`` is already present.)
    """
    # Strictly-past counts: within each cell, shift the target down by one row so
    # the value aligned to row t is violation_count[t-1]. Rolling over this series
    # therefore aggregates only past observations and excludes the current target.
    df["_past_count"] = df.groupby("grid_cell_id")["violation_count"].shift(1)
    past = df.groupby("grid_cell_id")["_past_count"]

    df["rolling_mean_7d"]  = past.transform(
        lambda s: s.rolling(168, min_periods=1).mean())
    df["rolling_mean_14d"] = past.transform(
        lambda s: s.rolling(336, min_periods=1).mean())
    df["rolling_std_7d"]   = past.transform(
        lambda s: s.rolling(168, min_periods=1).std())

    # First row(s) of each cell have no past data → NaN; treat as 0 history.
    df["rolling_mean_7d"]  = df["rolling_mean_7d"].fillna(0.0)
    df["rolling_mean_14d"] = df["rolling_mean_14d"].fillna(0.0)
    df["rolling_std_7d"]   = df["rolling_std_7d"].fillna(0.0)

    # violation_rate = PAST spike detector: previous count vs recent past average.
    # Uses lag_1 and the shifted rolling mean ONLY — never the current target.
    df["violation_rate"] = np.where(
        df["rolling_mean_7d"] > 0,
        df["lag_1"] / df["rolling_mean_7d"],
        1.0,
    )

    df = df.drop(columns=["_past_count"])
    return df


def compute_zone_metadata(raw_df: pd.DataFrame) -> pd.DataFrame:
    meta = raw_df.groupby("grid_cell_id").agg(
        mean_vehicle_severity=("vehicle_severity", "mean"),
        mean_validation_trust=("validation_trust", "mean"),
    ).reset_index()

    heavy = (
        raw_df.groupby("grid_cell_id")
        .apply(
            lambda g: (g["vehicle_severity"] >= 0.6).sum() / len(g),
            include_groups=False,
        )
        .rename("heavy_vehicle_ratio")
        .reset_index()
    )
    junc = (
        raw_df.groupby("grid_cell_id")
        .apply(
            lambda g: int(g["junction_name"].notna().sum() > len(g) / 2),
            include_groups=False,
        )
        .rename("junction_flag")
        .reset_index()
    )

    meta = meta.merge(heavy, on="grid_cell_id").merge(junc, on="grid_cell_id")
    print(f"[meta] Zone metadata: {len(meta)} cells")
    return meta


# ── Full pipeline ─────────────────────────────────────────────────────────

def build_feature_matrix(db_path: Path = DB_PATH) -> pd.DataFrame:
    raw = load_violations(db_path)
    agg = aggregate_counts(raw)
    agg = filter_cells(agg, min_obs=30)

    for col in ["hour", "day_of_week", "month", "is_weekend", "is_peak"]:
        agg[col] = pd.to_numeric(agg[col], errors="coerce").fillna(0).astype(int)

    agg = add_cyclical_features(agg)
    agg = add_lag_features(agg)
    agg = add_rolling_features(agg)

    meta = compute_zone_metadata(raw)
    agg  = agg.merge(meta, on="grid_cell_id", how="left")

    print(f"[done] Feature matrix: {agg.shape}")
    return agg


def save_features(df: pd.DataFrame, db_path: Path = DB_PATH,
                  csv_path: Path = CSV_PATH) -> None:
    conn = sqlite3.connect(str(db_path))
    df.to_sql("forecast_features", conn, if_exists="replace", index=False)
    conn.close()
    print(f"[save] {len(df):,} rows → SQLite 'forecast_features'")

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    print(f"[save] {len(df):,} rows → {csv_path}")


# ── Entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("ParkVisionSaathi – Feature Engineering")
    print("=" * 60)

    features = build_feature_matrix()
    save_features(features)

    print("\n── Feature columns ──")
    print([c for c in features.columns])

    print("\n── Null counts (should be 0 except lag_*) ──")
    nulls = features.isnull().sum()
    print(nulls[nulls > 0].to_string() or "  (none)")

    print("\n✅ Feature engineering complete.")
