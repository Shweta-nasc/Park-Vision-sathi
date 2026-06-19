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
- Added ``violation_rate`` feature: violation_count / rolling_mean_7d (ratio
  of current count to recent average — captures sudden spikes).
- Added ``is_data_rich_hour`` flag: 1 if hour in 0–15 (temporal cliff guard).
- Added ``month_sin`` / ``month_cos`` cyclical month encoding.
- apply() calls updated to suppress FutureWarning (include_groups=False already present).
- All NaN rolling_std_7d (first window) filled with 0.0 before saving.
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
    grp = df.groupby("grid_cell_id")["violation_count"]
    df["rolling_mean_7d"]  = grp.transform(
        lambda s: s.rolling(168,  min_periods=1).mean())
    df["rolling_mean_14d"] = grp.transform(
        lambda s: s.rolling(336,  min_periods=1).mean())
    df["rolling_std_7d"]   = grp.transform(
        lambda s: s.rolling(168,  min_periods=1).std())
    df["rolling_std_7d"]   = df["rolling_std_7d"].fillna(0.0)

    # NEW: violation_rate = current / rolling_mean_7d (spike detector)
    df["violation_rate"] = np.where(
        df["rolling_mean_7d"] > 0,
        df["violation_count"] / df["rolling_mean_7d"],
        1.0,
    )
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
