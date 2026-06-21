"""
feature_engineering.py – Phase 2: spatial-temporal feature matrix for the
hourly violation-count forecaster (LightGBM + CatBoost).

This revision consumes the DENSE hourly grid built by
:func:`data.regularize_grid.build_dense_grid` (Phase 1) instead of the old SPARSE
``(cell, date, hour)`` representation. On the dense grid every ``(cell, hour)``
slot exists, so the autoregressive features are PHYSICALLY CORRECT:

* ``lag_1`` / ``lag_24`` / ``lag_168``  = the count exactly 1 hour / 1 day / 1
  week before the target hour ``t`` (true clock lags, not "recorded observations
  ago").
* ``rolling_mean_24h`` / ``rolling_std_24h`` / ``rolling_mean_168h`` /
  ``rolling_std_168h``  = trailing windows computed on STRICTLY-PAST data
  (``shift(1)`` before rolling), so the current target never enters its own
  feature.
* ``violation_rate``  = ``lag_1 / rolling_mean_168h`` (both strictly-past) — a
  spike detector that never references the current target.
* ``spatial_lag_1``  = mean over a cell's spatial neighbours of their count at
  ``t-1`` (strictly ``t-1``, never ``t``).

TARGET-LEAKAGE AUDIT (this revision)
------------------------------------
Every predictive feature is a function of data strictly BEFORE the target hour
``t``:
  - lags use ``shift(k)`` with ``k >= 1``;
  - rolling stats are ``shift(1)`` THEN ``rolling(window)`` — the window for row
    ``t`` covers ``t-1 .. t-window`` only;
  - the spatial lag uses neighbour counts at ``t-1`` (the ``t-1`` count matrix),
    never ``t``;
  - ``violation_rate`` is built only from ``lag_1`` and the shifted rolling mean.
Calendar/cyclical features (``hour``, ``day_of_week``, ``month``, the sin/cos
encodings, ``is_weekend`` / ``is_peak`` / ``is_data_rich_hour``) and the static
zone descriptors (``grid_lat`` / ``grid_lon`` and the per-cell
``mean_vehicle_severity`` / ``mean_validation_trust`` / ``heavy_vehicle_ratio`` /
``junction_flag``) are all known at or before prediction time and carry no
per-row target information.

SPATIAL-NEIGHBOUR NOTE (deviation from the literal blueprint, documented)
-------------------------------------------------------------------------
The blueprint specified the spatial lag's neighbours via an H3 res-9
``grid_disk(h3, 1)`` k-ring. The violation grid, however, is a ~550 m lat/lon
lattice (``GRID_RESOLUTION = 0.005°`` in ``data/load_and_clean.py``), while H3
res-9 cells are only ~330 m across; the ~550 m grid spacing straddles the H3
res-9 k-ring1/k-ring2 boundary, so a literal ``grid_disk(h3, 1)`` lookup finds a
neighbour for only some cells (measured: ~275 of 601) and misses the rest
depending on how each centroid happens to fall inside its hexagon — an
inconsistent, alignment-dependent adjacency. To produce a physically meaningful
and CONSISTENT spatial lag, neighbours are taken on the grid's OWN integer
lattice — the 8-cell Moore neighbourhood ``(lat_i ± 1, lon_i ± 1)`` (measured:
561 of 601 cells have >=1 active neighbour) — which is the correct adjacency for
this grid. The ``h3_id`` (res-9) column is still attached per the blueprint (it
aligns this matrix with the H3-keyed Congestion Impact artifact).

Output
------
- SQLite table ``forecast_features`` in ``data/parkvision.db`` (``grid_cell_id``
  preserved as the key; an ``h3_id`` column is ADDED).
- CSV file ``data/forecast_features.csv``.
"""

from __future__ import annotations

import importlib.util
import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import h3
except ImportError as exc:  # pragma: no cover
    raise ImportError("The 'h3' package is required. Install via: pip install h3") from exc

# ── Paths ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"
CSV_PATH = PROJECT_ROOT / "data" / "forecast_features.csv"

H3_RESOLUTION = 9
DATA_RICH_HOURS = set(range(16))


# ── Phase-1 import (path-robust) ───────────────────────────────────────────

def _load_regularize_grid():
    """Import ``data/regularize_grid.py`` by file path (no package assumptions)."""
    path = PROJECT_ROOT / "data" / "regularize_grid.py"
    spec = importlib.util.spec_from_file_location("regularize_grid", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Zone metadata (static descriptors, from the raw violations) ────────────

def compute_zone_metadata(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Per-cell static descriptors aggregated over each cell's full history.

    These are zone-level constants (not per-hour), so they carry no target
    information for any individual row.
    """
    conn = sqlite3.connect(str(db_path))
    raw = pd.read_sql_query(
        """
        SELECT grid_cell_id, vehicle_severity, validation_trust, junction_name
        FROM violations
        WHERE grid_cell_id IS NOT NULL
        """,
        conn,
    )
    conn.close()

    meta = raw.groupby("grid_cell_id").agg(
        mean_vehicle_severity=("vehicle_severity", "mean"),
        mean_validation_trust=("validation_trust", "mean"),
    )
    heavy = raw.groupby("grid_cell_id").apply(
        lambda g: float((g["vehicle_severity"] >= 0.6).sum()) / len(g),
        include_groups=False,
    ).rename("heavy_vehicle_ratio")
    junc = raw.groupby("grid_cell_id").apply(
        lambda g: int(g["junction_name"].notna().sum() > len(g) / 2),
        include_groups=False,
    ).rename("junction_flag")

    meta = meta.join(heavy).join(junc).reset_index()
    print(f"[meta] Zone metadata: {len(meta)} cells")
    return meta


# ── Cyclical encodings ─────────────────────────────────────────────────────

def add_cyclical_features(df: pd.DataFrame) -> pd.DataFrame:
    df["sin_hour"] = np.sin(2 * math.pi * df["hour"] / 24)
    df["cos_hour"] = np.cos(2 * math.pi * df["hour"] / 24)
    df["sin_dow"] = np.sin(2 * math.pi * df["day_of_week"] / 7)
    df["cos_dow"] = np.cos(2 * math.pi * df["day_of_week"] / 7)
    df["sin_month"] = np.sin(2 * math.pi * df["month"] / 12)
    df["cos_month"] = np.cos(2 * math.pi * df["month"] / 12)
    return df


# ── Autoregressive lags ────────────────────────────────────────────────────

def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """True clock lags on the dense grid: 1 hour, 1 day, 1 week."""
    g = df.groupby("grid_cell_id")["violation_count"]
    for lag in (1, 24, 168):
        df[f"lag_{lag}"] = g.shift(lag)
    return df


def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Trailing rolling stats on STRICTLY-PAST counts (shift(1) before rolling)."""
    df["_past"] = df.groupby("grid_cell_id")["violation_count"].shift(1)
    past = df.groupby("grid_cell_id")["_past"]

    df["rolling_mean_24h"] = past.transform(lambda s: s.rolling(24, min_periods=1).mean())
    df["rolling_std_24h"] = past.transform(lambda s: s.rolling(24, min_periods=1).std())
    df["rolling_mean_168h"] = past.transform(lambda s: s.rolling(168, min_periods=1).mean())
    df["rolling_std_168h"] = past.transform(lambda s: s.rolling(168, min_periods=1).std())

    for col in ("rolling_mean_24h", "rolling_std_24h", "rolling_mean_168h", "rolling_std_168h"):
        df[col] = df[col].fillna(0.0)

    # PAST spike detector: most recent count vs recent-past average. Strictly-past.
    df["violation_rate"] = np.where(
        df["rolling_mean_168h"] > 0, df["lag_1"] / df["rolling_mean_168h"], 1.0
    )
    df = df.drop(columns=["_past"])
    return df


# ── Spatial lag (grid Moore neighbourhood; H3 coverage reported) ───────────

def _parse_cell(cell_id: str) -> tuple[int, int]:
    """Parse ``"lat_lon"`` grid id into its integer lattice coordinates."""
    lat_s, lon_s = cell_id.split("_")
    return int(lat_s), int(lon_s)


def _report_h3_kring_coverage(cell_h3: dict[str, str]) -> None:
    """Measure how many cells have >=1 active neighbour under H3 res-9 k-ring=1.

    Documents WHY the literal blueprint mapping is unusable on this ~550 m grid.
    """
    active_h3 = set(cell_h3.values())
    with_nbr = 0
    for cid, hid in cell_h3.items():
        try:
            ring = set(h3.grid_disk(hid, 1)) - {hid}
        except Exception:  # pragma: no cover
            ring = set()
        if active_h3 & ring:
            with_nbr += 1
    print(
        f"[spatial] H3 res-9 k-ring=1 coverage: {with_nbr}/{len(cell_h3)} cells have "
        f">=1 active neighbour (INCONSISTENT — the ~550 m grid spacing straddles the "
        f"k-ring1/k-ring2 boundary depending on hex alignment, so many cells get no "
        f"neighbour). The grid Moore neighbourhood below is used instead."
    )


def add_spatial_lag(df: pd.DataFrame) -> pd.DataFrame:
    """SpatialLag_{i,t} = mean over grid-Moore neighbours j of count_{j, t-1}.

    Also attaches the ``h3_id`` (res-9) column and reports H3 k-ring coverage.
    Uses a matrix formulation over the contiguous (cell × hour) grid so it is fast
    and unambiguously strictly-``t-1``.
    """
    df = df.sort_values(["grid_cell_id", "ts"]).reset_index(drop=True)

    cells = df["grid_cell_id"].drop_duplicates().tolist()  # reshape row order
    n_cells = len(cells)
    n_hours = len(df) // n_cells
    assert n_cells * n_hours == len(df), "dense grid is not perfectly rectangular"
    cell_idx = {c: i for i, c in enumerate(cells)}

    # Per-cell centroid -> H3 res-9 id (added as a column; one value per cell).
    centroids = df.groupby("grid_cell_id")[["grid_lat", "grid_lon"]].first()
    cell_h3 = {
        c: h3.latlng_to_cell(float(centroids.loc[c, "grid_lat"]),
                             float(centroids.loc[c, "grid_lon"]), H3_RESOLUTION)
        for c in cells
    }
    df["h3_id"] = df["grid_cell_id"].map(cell_h3)
    _report_h3_kring_coverage(cell_h3)

    # Grid Moore adjacency (the correct adjacency for the ~550 m lattice).
    coords = {c: _parse_cell(c) for c in cells}
    present = set(coords.values())
    coord_to_cell = {v: k for k, v in coords.items()}
    A = np.zeros((n_cells, n_cells), dtype=np.float64)
    deltas = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    for c in cells:
        li, lj = coords[c]
        i = cell_idx[c]
        for dx, dy in deltas:
            nb = (li + dx, lj + dy)
            if nb in present:
                A[i, cell_idx[coord_to_cell[nb]]] = 1.0
    deg = A.sum(axis=1)
    n_with_nbr = int((deg > 0).sum())
    print(
        f"[spatial] Grid Moore neighbourhood: {n_with_nbr}/{n_cells} cells have "
        f">=1 active neighbour (mean degree {deg[deg > 0].mean():.2f})."
    )

    # Count matrix M[cell, hour]; t-1 matrix L (first hour has no past -> 0).
    M = df["violation_count"].to_numpy(dtype=np.float64).reshape(n_cells, n_hours)
    L = np.zeros_like(M)
    L[:, 1:] = M[:, :-1]

    # Neighbour mean of t-1 counts. deg==0 -> 0 (no neighbours).
    safe_deg = np.where(deg > 0, deg, 1.0)
    SL = (A @ L) / safe_deg[:, None]
    SL[deg == 0, :] = 0.0

    df["spatial_lag_1"] = SL.reshape(-1)
    return df


# ── Full pipeline ─────────────────────────────────────────────────────────

def build_feature_matrix(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Build the dense spatial-temporal feature matrix (Phase 1 -> Phase 2)."""
    rg = _load_regularize_grid()
    dense = rg.build_dense_grid(db_path=db_path, persist=False)

    dense = add_cyclical_features(dense)
    dense = add_lag_features(dense)
    dense = add_rolling_features(dense)
    dense = add_spatial_lag(dense)

    meta = compute_zone_metadata(db_path)
    dense = dense.merge(meta, on="grid_cell_id", how="left")

    # Drop the timestamp (date + hour are retained); keep grid_cell_id + h3_id.
    dense = dense.drop(columns=["ts"])

    print(f"[done] Feature matrix: {dense.shape}")
    return dense


def save_features(df: pd.DataFrame, db_path: Path = DB_PATH,
                  csv_path: Path = CSV_PATH) -> None:
    conn = sqlite3.connect(str(db_path))
    df.to_sql("forecast_features", conn, if_exists="replace", index=False, chunksize=50_000)
    conn.close()
    print(f"[save] {len(df):,} rows → SQLite 'forecast_features'")

    # Export the CSV by STREAMING from SQLite in chunks rather than materializing
    # the whole 2.1M-row frame as one CSV string in memory (that OOMs on small
    # machines). Floats are rounded to 5 dp to keep the file compact.
    export_features_csv(db_path=db_path, csv_path=csv_path)


def export_features_csv(db_path: Path = DB_PATH, csv_path: Path = CSV_PATH,
                        batch: int = 50_000) -> None:
    """Write ``forecast_features`` to CSV by streaming straight from SQLite.

    Uses a raw ``sqlite3`` cursor + the stdlib ``csv`` writer with ``fetchmany``
    so peak memory is one batch of rows (no DataFrame, no giant CSV string) —
    the pandas ``to_csv`` path OOMs on memory-constrained machines for 2.1M rows.
    Float fields are rounded to 5 dp to keep the file compact.
    """
    import csv as _csv

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        csv_path.unlink()

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT * FROM forecast_features")
    cols = [d[0] for d in cur.description]

    total = 0
    with open(csv_path, "w", newline="") as fh:
        writer = _csv.writer(fh)
        writer.writerow(cols)
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            formatted = [
                [("%.5f" % v if isinstance(v, float) else v) for v in row]
                for row in rows
            ]
            writer.writerows(formatted)
            total += len(rows)
    conn.close()
    print(f"[save] {total:,} rows → {csv_path}")


# ── Entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("ParkVisionSaathi – Feature Engineering (Phase 2, dense grid)")
    print("=" * 60)

    features = build_feature_matrix()
    save_features(features)

    print("\n── Feature columns ──")
    print([c for c in features.columns])

    print("\n── Null counts (expected only in lag_* / first hours) ──")
    nulls = features.isnull().sum()
    print(nulls[nulls > 0].to_string() or "  (none)")

    print("\n✅ Feature engineering complete.")
