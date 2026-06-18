"""
Feature engineering for time-series violation count forecasting.

Loads violations from SQLite, aggregates to grid_cell_id × date × hour,
and engineers temporal, cyclical, lag, rolling, and zone-metadata features.

Output:
    - SQLite table 'forecast_features' in data/parkvision.db
    - CSV file data/forecast_features.csv
"""

import sqlite3
import math
from pathlib import Path

import numpy as np
import pandas as pd

# ── paths ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"
CSV_PATH = PROJECT_ROOT / "data" / "forecast_features.csv"


# ── helpers ──────────────────────────────────────────────────────────────
def load_violations(db_path: Path) -> pd.DataFrame:
    """Load the violations table from SQLite into a DataFrame."""
    conn = sqlite3.connect(str(db_path))
    query = """
        SELECT grid_cell_id, date, hour, day_of_week, month, is_weekend,
               is_peak, vehicle_severity, validation_trust, junction_name
        FROM violations
        WHERE grid_cell_id IS NOT NULL
          AND date IS NOT NULL
          AND hour IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    print(f"[load] Raw violations loaded: {len(df):,} rows")
    return df


def aggregate_counts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate violations → count per (grid_cell_id, date, hour).

    Also carries forward the modal/mean zone-level metadata needed later.
    """
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
    # Ensure date is string for consistent sorting, then sort chronologically
    agg["date"] = agg["date"].astype(str)
    agg = agg.sort_values(["grid_cell_id", "date", "hour"]).reset_index(drop=True)
    print(f"[agg]  Aggregated time series: {len(agg):,} rows  |  "
          f"{agg['grid_cell_id'].nunique()} unique cells")
    return agg


def filter_cells(agg: pd.DataFrame, min_obs: int = 30) -> pd.DataFrame:
    """Keep only grid cells with more than *min_obs* observations."""
    counts = agg.groupby("grid_cell_id")["violation_count"].count()
    valid_cells = counts[counts > min_obs].index
    filtered = agg[agg["grid_cell_id"].isin(valid_cells)].copy()
    print(f"[filt] Cells with >{min_obs} obs: {len(valid_cells)} "
          f"({len(filtered):,} rows kept)")
    return filtered


def add_cyclical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add sin/cos encodings for hour and day_of_week."""
    df["sin_hour"] = np.sin(2 * math.pi * df["hour"] / 24)
    df["cos_hour"] = np.cos(2 * math.pi * df["hour"] / 24)
    df["sin_dow"] = np.sin(2 * math.pi * df["day_of_week"] / 7)
    df["cos_dow"] = np.cos(2 * math.pi * df["day_of_week"] / 7)
    return df


def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-cell lag features on violation_count:
        lag_1   – previous time-step
        lag_24  – same hour yesterday
        lag_168 – same hour one week ago
    """
    for lag in [1, 24, 168]:
        df[f"lag_{lag}"] = (
            df.groupby("grid_cell_id")["violation_count"]
            .shift(lag)
        )
    return df


def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-cell rolling statistics (window sizes in #rows, chronologically sorted):
        rolling_mean_7d   – 7-day  (168 hourly slots)
        rolling_mean_14d  – 14-day (336 hourly slots)
        rolling_std_7d    – 7-day rolling standard deviation
    
    Uses min_periods=1 to maximise coverage; downstream training
    drops rows with NaN lags anyway.
    """
    grp = df.groupby("grid_cell_id")["violation_count"]

    df["rolling_mean_7d"] = grp.transform(
        lambda s: s.rolling(window=168, min_periods=1).mean()
    )
    df["rolling_mean_14d"] = grp.transform(
        lambda s: s.rolling(window=336, min_periods=1).mean()
    )
    df["rolling_std_7d"] = grp.transform(
        lambda s: s.rolling(window=168, min_periods=1).std()
    )
    return df


def compute_zone_metadata(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-cell static metadata from the raw violations:
        mean_vehicle_severity   – average severity in that cell
        mean_validation_trust   – average trust score
        heavy_vehicle_ratio     – fraction of violations with severity >= 0.6
        junction_flag           – 1 if most violations occur at a named junction
    """
    meta = raw_df.groupby("grid_cell_id").agg(
        mean_vehicle_severity=("vehicle_severity", "mean"),
        mean_validation_trust=("validation_trust", "mean"),
    ).reset_index()

    # heavy_vehicle_ratio
    heavy = (
        raw_df.groupby("grid_cell_id")
        .apply(
            lambda g: (g["vehicle_severity"] >= 0.6).sum() / len(g),
            include_groups=False,
        )
        .rename("heavy_vehicle_ratio")
        .reset_index()
    )

    # junction_flag: 1 if the majority of violations have a non-null junction
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
    print(f"[meta] Zone metadata computed for {len(meta)} cells")
    return meta


def build_feature_matrix(db_path: Path = DB_PATH) -> pd.DataFrame:
    """
    End-to-end pipeline: load → aggregate → filter → engineer → merge.

    Returns the complete feature matrix as a DataFrame.
    """
    raw = load_violations(db_path)

    # 1. Aggregate to time-series grain
    agg = aggregate_counts(raw)

    # 2. Keep only cells with enough data
    agg = filter_cells(agg, min_obs=30)

    # 3. Time features (already present from agg, ensure int)
    for col in ["hour", "day_of_week", "month", "is_weekend", "is_peak"]:
        agg[col] = pd.to_numeric(agg[col], errors="coerce").fillna(0).astype(int)

    # 4. Cyclical features
    agg = add_cyclical_features(agg)

    # 5. Lag features (requires chronological sort — already done)
    agg = add_lag_features(agg)

    # 6. Rolling statistics
    agg = add_rolling_features(agg)

    # 7. Zone metadata (computed from raw, merged in)
    meta = compute_zone_metadata(raw)
    agg = agg.merge(meta, on="grid_cell_id", how="left")

    print(f"[done] Feature matrix shape: {agg.shape}")
    return agg


def save_features(df: pd.DataFrame, db_path: Path = DB_PATH,
                  csv_path: Path = CSV_PATH) -> None:
    """Persist the feature matrix to SQLite and CSV."""
    # SQLite
    conn = sqlite3.connect(str(db_path))
    df.to_sql("forecast_features", conn, if_exists="replace", index=False)
    conn.close()
    print(f"[save] Written {len(df):,} rows → SQLite table 'forecast_features'")

    # CSV
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    print(f"[save] Written {len(df):,} rows → {csv_path}")


# ── main ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("ParkVisionSaathi – Feature Engineering for Forecasting")
    print("=" * 60)

    features = build_feature_matrix()
    save_features(features)

    # Quick validation
    print("\n── Sample rows ──")
    print(features.head(3).to_string(index=False))

    print("\n── Column dtypes ──")
    print(features.dtypes.to_string())

    print("\n── Null counts ──")
    print(features.isnull().sum().to_string())

    print("\n✅ Feature engineering complete.")
