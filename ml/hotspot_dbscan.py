"""
hotspot_dbscan.py – Time-aware DBSCAN clustering for ParkVisionSaathi.

Workflow
--------
1. Load violations from SQLite (data/parkvision.db).
2. Split into 4 time buckets: night_0_6, morning_6_10, midday_10_16, evening_16_22.
3. For each bucket run DBSCAN on (lat, lon) using haversine metric via BallTree
   (eps ≈ 330 m → 0.003 radians on the earth surface, min_samples=10).
4. Compute cluster centroids, member counts, bounding boxes and top junction.
5. Save results to the ``hotspot_clusters`` table.
6. Validate clusters against known junction_name values.
"""

from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TIME_BUCKETS: dict[str, tuple[int, int]] = {
    "night_0_6": (0, 6),
    "morning_6_10": (6, 10),
    "midday_10_16": (10, 16),
    "evening_16_22": (16, 22),
}

# DBSCAN hyperparams
# eps in *radians*: 330 m / 6_371_000 m (earth radius) ≈ 5.18e-5
# but the user spec says eps=0.003 (~330 m) treating degrees; to honour the
# spec *and* use haversine we convert to radians where 0.003° ≈ 333 m.
EPS_RADIANS = np.radians(0.003)  # ≈ 5.24e-5 rad
MIN_SAMPLES = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assign_time_bucket(hour: int) -> str | None:
    """Return the time bucket name for a given hour (0-23), or None if out of range."""
    for bucket_name, (lo, hi) in TIME_BUCKETS.items():
        if lo <= hour < hi:
            return bucket_name
    return None  # hours 22-23 fall outside defined buckets


def _load_violations(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load relevant columns from the violations table."""
    query = """
        SELECT latitude, longitude, hour, junction_name
        FROM violations
        WHERE latitude IS NOT NULL
          AND longitude IS NOT NULL
          AND hour IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    print(f"  Loaded {len(df):,} violations with valid lat/lon/hour.")
    return df


def _run_dbscan_for_bucket(
    df_bucket: pd.DataFrame,
    bucket_name: str,
) -> pd.DataFrame | None:
    """Run DBSCAN on a single time-bucket slice and return cluster summary rows."""
    coords = df_bucket[["latitude", "longitude"]].values
    if len(coords) < MIN_SAMPLES:
        print(f"  [{bucket_name}] Only {len(coords)} points – skipping.")
        return None

    # Convert to radians for haversine
    coords_rad = np.radians(coords)

    db = DBSCAN(
        eps=EPS_RADIANS,
        min_samples=MIN_SAMPLES,
        metric="haversine",
        algorithm="ball_tree",
    )
    labels = db.fit_predict(coords_rad)

    df_bucket = df_bucket.copy()
    df_bucket["cluster_label"] = labels

    # Discard noise (label == -1)
    clustered = df_bucket[df_bucket["cluster_label"] != -1]
    n_clusters = clustered["cluster_label"].nunique()
    n_noise = (labels == -1).sum()
    print(
        f"  [{bucket_name}] {len(coords):,} pts → "
        f"{n_clusters} clusters, {n_noise:,} noise points"
    )

    if n_clusters == 0:
        return None

    # Aggregate per cluster
    records: list[dict] = []
    for cid, grp in clustered.groupby("cluster_label"):
        lats = grp["latitude"].values
        lons = grp["longitude"].values
        junctions = grp["junction_name"].dropna().tolist()
        top_junction = Counter(junctions).most_common(1)
        top_junction_name = top_junction[0][0] if top_junction else None

        records.append(
            {
                "cluster_id": f"{bucket_name}_{int(cid)}",
                "time_bucket": bucket_name,
                "centroid_lat": float(np.mean(lats)),
                "centroid_lon": float(np.mean(lons)),
                "member_count": len(grp),
                "bbox_min_lat": float(np.min(lats)),
                "bbox_min_lon": float(np.min(lons)),
                "bbox_max_lat": float(np.max(lats)),
                "bbox_max_lon": float(np.max(lons)),
                "top_junction": top_junction_name,
            }
        )

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_hotspot_clustering(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Execute the full time-aware DBSCAN pipeline and persist results.

    Returns
    -------
    pd.DataFrame
        The aggregated ``hotspot_clusters`` table written to SQLite.
    """
    print("=" * 60)
    print("Hotspot DBSCAN Clustering")
    print("=" * 60)

    conn = sqlite3.connect(str(db_path))
    try:
        df = _load_violations(conn)

        # Assign time buckets
        df["time_bucket"] = df["hour"].apply(_assign_time_bucket)
        df = df.dropna(subset=["time_bucket"])
        print(f"  {len(df):,} violations mapped to time buckets.")

        all_clusters: list[pd.DataFrame] = []
        for bucket_name in TIME_BUCKETS:
            df_bucket = df[df["time_bucket"] == bucket_name]
            result = _run_dbscan_for_bucket(df_bucket, bucket_name)
            if result is not None:
                all_clusters.append(result)

        if not all_clusters:
            print("  ⚠  No clusters found in any time bucket.")
            return pd.DataFrame()

        clusters_df = pd.concat(all_clusters, ignore_index=True)

        # ---- Persist -------------------------------------------------------
        clusters_df.to_sql(
            "hotspot_clusters", conn, if_exists="replace", index=False
        )
        print(f"\n  ✓ Saved {len(clusters_df)} cluster rows to 'hotspot_clusters'.")

        # ---- Validate against junction_name --------------------------------
        _validate_clusters(clusters_df, conn)

        return clusters_df
    finally:
        conn.close()


def _validate_clusters(clusters_df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    """Cross-check cluster top_junction values against known junction_name values."""
    known_junctions = set(
        pd.read_sql_query(
            "SELECT DISTINCT junction_name FROM violations WHERE junction_name IS NOT NULL",
            conn,
        )["junction_name"]
    )

    mapped = clusters_df["top_junction"].dropna()
    valid = mapped.isin(known_junctions).sum()
    total = len(mapped)
    print(f"\n  Validation: {valid}/{total} cluster top_junctions match known junctions.")

    # Show top-junction frequency
    top_freq = mapped.value_counts().head(10)
    print("\n  Top-10 junctions across clusters:")
    for jname, cnt in top_freq.items():
        print(f"    {jname}: {cnt} clusters")


def _print_summary(clusters_df: pd.DataFrame) -> None:
    """Print summary statistics to stdout."""
    if clusters_df.empty:
        print("  No clusters to summarize.")
        return

    print("\n" + "=" * 60)
    print("Summary Statistics")
    print("=" * 60)

    print(f"\n  Total clusters: {len(clusters_df)}")
    print(f"  Total violations in clusters: {clusters_df['member_count'].sum():,}")

    print("\n  Per time bucket:")
    for bucket, grp in clusters_df.groupby("time_bucket"):
        print(
            f"    {bucket:20s}  clusters={len(grp):4d}  "
            f"members={grp['member_count'].sum():>7,}  "
            f"avg_size={grp['member_count'].mean():.1f}"
        )

    print("\n  Largest clusters:")
    top5 = clusters_df.nlargest(5, "member_count")
    for _, row in top5.iterrows():
        print(
            f"    {row['cluster_id']:30s}  members={row['member_count']:>6,}  "
            f"centroid=({row['centroid_lat']:.4f}, {row['centroid_lon']:.4f})  "
            f"junction={row['top_junction']}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)

    result = run_hotspot_clustering()
    _print_summary(result)
    print("\nDone.")
