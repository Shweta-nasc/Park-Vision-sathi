"""
regularize_grid.py — Phase 1: dense hourly time-grid zero-filling.

The leakage-fixed forecast pipeline (``ml/forecast``) historically operated on a
SPARSE representation: one row per ``(grid_cell_id, date, hour)`` that recorded
≥1 violation. On that representation ``lag_1`` / ``lag_24`` / ``lag_168`` meant "1
/ 24 / 168 *recorded observations* ago", not real clock hours, so the
autoregressive features were not physically meaningful.

This module builds the missing piece: a COMPLETE hourly grid of
``active grid_cell_id × every clock hour`` over the dataset's full IST span, with
structural blanks zero-filled. On this dense grid ``lag_k`` is a true k-hour lag
and rolling windows span real calendar time, which is the precondition for the
spatial-temporal features in :mod:`ml.forecast.feature_engineering`.

Design decisions (honest, leakage-safe)
---------------------------------------
* **REAL DATA ONLY.** Counts come from the ``violations`` table in
  ``data/parkvision.db`` (loaded from the anonymized Bengaluru CSV). No synthetic
  seeding, ever.
* **IST clock.** ``created_datetime`` is stored in UTC ("...+00:00"). It is parsed
  as UTC and converted to Asia/Kolkata (IST, +05:30) BEFORE the hour-of-day / date
  are read, so the grid and all calendar features reflect local Bengaluru time and
  the temporal cliff (enforcement shifts end ~16:00 IST) lands where it physically
  is. The dataset's IST span is ≈ 2023-11-10 00:00 → 2024-04-08 23:00.
* **Active cells only.** Only cells with ``>= MIN_OBS`` (30) total violations are
  materialized — the same filter the sparse pipeline used — so the dense grid
  stays bounded (≈ 601 cells × ≈ 3,624 hours).
* **grid_cell_id is preserved** as the primary key (Person 1's backend depends on
  it). ``grid_lat`` / ``grid_lon`` are carried per cell for the spatial join.
* **is_data_rich_hour** flags IST hours 0–15 (the ~99% data-rich window); hours
  16–23 are still materialized (so lags are physically correct) but flagged so
  downstream code can report data-rich-only headline metrics.

The dense frame is the input to Phase 2. It can also be persisted to the
``dense_hourly`` SQLite table for inspection (``persist=True`` /
``python data/regularize_grid.py``).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths / constants ─────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"

IST_TZ = "Asia/Kolkata"
MIN_OBS = 30                       # match the sparse pipeline's active-cell filter
DATA_RICH_HOURS = set(range(16))   # IST hours 0–15 (temporal-cliff guard)


# ── Load ──────────────────────────────────────────────────────────────────

def load_active_violations(db_path: Path = DB_PATH, min_obs: int = MIN_OBS) -> pd.DataFrame:
    """Load violations for active cells (>= ``min_obs`` total) with IST timestamps.

    Returns the per-violation rows (grid_cell_id, grid_lat, grid_lon, ts) where
    ``ts`` is the IST clock hour the violation was recorded in (tz-naive IST wall
    clock, floored to the hour).
    """
    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query(
        """
        SELECT grid_cell_id, grid_lat, grid_lon, created_datetime
        FROM violations
        WHERE grid_cell_id IS NOT NULL
          AND created_datetime IS NOT NULL
        """,
        conn,
    )
    conn.close()
    print(f"[grid] Raw violations (active-cell candidates): {len(df):,} rows")

    # UTC -> IST, then drop the tz so date_range / hour reflect local wall clock.
    dt_utc = pd.to_datetime(df["created_datetime"], utc=True, errors="coerce")
    df = df.loc[dt_utc.notna()].copy()
    dt_ist = dt_utc.loc[dt_utc.notna()].dt.tz_convert(IST_TZ).dt.tz_localize(None)
    df["ts"] = dt_ist.dt.floor("h")

    # Active-cell filter (>= min_obs total violations).
    totals = df.groupby("grid_cell_id")["grid_cell_id"].transform("size")
    df = df.loc[totals >= min_obs].copy()
    n_cells = df["grid_cell_id"].nunique()
    print(f"[grid] Active cells (>= {min_obs} obs): {n_cells} ({len(df):,} rows)")
    return df


# ── Build dense grid ───────────────────────────────────────────────────────

def build_dense_grid(
    db_path: Path = DB_PATH,
    min_obs: int = MIN_OBS,
    persist: bool = False,
) -> pd.DataFrame:
    """Build the complete ``active cell × hourly`` grid with zero-filled counts.

    Columns: ``grid_cell_id, ts, date, hour, day_of_week, month, is_weekend,
    is_peak, is_data_rich_hour, violation_count, grid_lat, grid_lon``.

    Every ``(cell, hour)`` slot in the continuous IST span is present exactly once;
    slots with no recorded violation get ``violation_count = 0``. Calendar features
    are derived from the IST timestamp. The frame is sorted by ``(grid_cell_id,
    ts)`` so each cell occupies a contiguous, time-ordered block (the layout Phase
    2's lag/rolling/spatial features rely on).
    """
    raw = load_active_violations(db_path, min_obs)

    # Hourly counts per cell.
    counts = (
        raw.groupby(["grid_cell_id", "ts"]).size().rename("violation_count").reset_index()
    )

    # Per-cell centroid (grid_lat / grid_lon are constant within a cell).
    meta = (
        raw.groupby("grid_cell_id")
        .agg(grid_lat=("grid_lat", "first"), grid_lon=("grid_lon", "first"))
        .reset_index()
    )

    cells = sorted(meta["grid_cell_id"].unique())
    t_min, t_max = counts["ts"].min(), counts["ts"].max()
    full_hours = pd.date_range(t_min, t_max, freq="h")
    print(
        f"[grid] IST span: {t_min} → {t_max} "
        f"({len(full_hours):,} hourly steps) × {len(cells)} cells "
        f"= {len(full_hours) * len(cells):,} dense rows"
    )

    # Complete cross-join (cell × hour), sorted (cell, ts) by construction.
    idx = pd.MultiIndex.from_product([cells, full_hours], names=["grid_cell_id", "ts"])
    dense = pd.DataFrame(index=idx).reset_index()

    # Left-join counts; structural blanks -> 0.
    dense = dense.merge(counts, on=["grid_cell_id", "ts"], how="left")
    dense["violation_count"] = dense["violation_count"].fillna(0).astype("int32")

    # Carry the per-cell centroid.
    dense = dense.merge(meta, on="grid_cell_id", how="left")

    # Calendar features from the IST timestamp.
    ts = dense["ts"]
    dense["hour"] = ts.dt.hour.astype("int16")
    dense["day_of_week"] = ts.dt.dayofweek.astype("int16")     # Mon=0
    dense["month"] = ts.dt.month.astype("int16")
    dense["date"] = ts.dt.strftime("%Y-%m-%d")
    dense["is_weekend"] = dense["day_of_week"].isin([5, 6]).astype("int8")
    dense["is_peak"] = (
        dense["hour"].between(8, 10) | dense["hour"].between(17, 19)
    ).astype("int8")
    dense["is_data_rich_hour"] = dense["hour"].isin(DATA_RICH_HOURS).astype("int8")

    dense = dense.sort_values(["grid_cell_id", "ts"]).reset_index(drop=True)

    nonzero = int((dense["violation_count"] > 0).sum())
    print(
        f"[grid] Dense frame: {dense.shape[0]:,} rows | "
        f"{dense['grid_cell_id'].nunique()} cells | {len(full_hours):,} hours | "
        f"nonzero slots: {nonzero:,} ({100 * nonzero / len(dense):.2f}%)"
    )

    if persist:
        persist_dense_hourly(dense, db_path)

    return dense


def persist_dense_hourly(dense: pd.DataFrame, db_path: Path = DB_PATH) -> None:
    """Persist the dense grid to the ``dense_hourly`` SQLite table (ts as ISO str)."""
    out = dense.copy()
    out["ts"] = out["ts"].astype(str)
    conn = sqlite3.connect(str(db_path))
    out.to_sql("dense_hourly", conn, if_exists="replace", index=False, chunksize=50_000)
    conn.close()
    print(f"[grid] Persisted {len(out):,} rows → SQLite 'dense_hourly'")


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("ParkVisionSaathi – Dense Hourly Grid (Phase 1)")
    print("=" * 60)
    frame = build_dense_grid(persist=True)
    print("\n✅ Dense grid complete.")
