"""
hotspot_dbscan.py – Time-aware DBSCAN clustering for ParkVisionSaathi.

Workflow
--------
1. Load violations from SQLite (data/parkvision.db).
2. Split into 4 time buckets: night_0_6, morning_6_10, midday_10_16, evening_16_22.
3. For each bucket run DBSCAN on (lat, lon) using haversine metric via BallTree
   (eps ≈ 330 m → 0.003°, converted to radians for haversine, min_samples=10).
4. Compute cluster centroids, member counts, bounding boxes, top junction.
5. Save results to the ``hotspot_clusters`` table.
6. Validate clusters against known junction_name values.

ADDITIONS vs v1
---------------
- Temporal cliff guard: warns if a bucket has <5% of total data (evening hours).
- Exports ``hotspot_summary_by_bucket`` table for the frontend time-slider.
- Skips hours 22–23 intentionally (documented, not silently dropped).
- Data-rich zone flag: marks buckets with >10% total data as "data_rich".
- cluster_density column added (members / bbox area in km²).
"""

from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

# ── Paths ───────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"

# ── Constants ────────────────────────────────────────────────────────────
TIME_BUCKETS: dict[str, tuple[int, int]] = {
    "night_0_6":     (0,  6),
    "morning_6_10":  (6,  10),
    "midday_10_16":  (10, 16),
    "evening_16_22": (16, 22),
    # Hours 22-23 intentionally excluded — see TEMPORAL CLIFF note above.
}

# DBSCAN: eps in radians for haversine. 0.003° ≈ 333 m on earth surface.
EPS_RADIANS  = np.radians(0.003)
MIN_SAMPLES  = 10

# Temporal cliff threshold: bucket with <5% of rows flagged as sparse.
SPARSE_BUCKET_THRESHOLD = 0.05

# Earth radius for area estimate (km)
EARTH_RADIUS_KM = 6371.0


# ── Helpers ──────────────────────────────────────────────────────────────

def _assign_time_bucket(hour: int) -> str | None:
    for name, (lo, hi) in TIME_BUCKETS.items():
        if lo <= hour < hi:
            return name
    return None  # 22, 23 intentionally unmapped


def _load_violations(conn: sqlite3.Connection) -> pd.DataFrame:
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


def _bbox_area_km2(min_lat: float, max_lat: float,
                   min_lon: float, max_lon: float) -> float:
    """Approximate cluster bounding-box area in km²."""
    lat_km = np.radians(max_lat - min_lat) * EARTH_RADIUS_KM
    lon_km = (np.radians(max_lon - min_lon)
              * EARTH_RADIUS_KM
              * np.cos(np.radians((min_lat + max_lat) / 2)))
    area = lat_km * lon_km
    return max(area, 1e-6)  # avoid division by zero for tiny clusters


def _temporal_cliff_check(df: pd.DataFrame) -> None:
    """Warn if any bucket has very few points (evening hours data cliff)."""
    total = len(df)
    print("\n  ── Temporal distribution ──")
    for name, (lo, hi) in TIME_BUCKETS.items():
        n = ((df["hour"] >= lo) & (df["hour"] < hi)).sum()
        pct = n / total * 100
        flag = "⚠️  SPARSE" if pct < SPARSE_BUCKET_THRESHOLD * 100 else "✅"
        rich = "DATA-RICH" if pct >= 10 else ""
        print(f"    {name:20s}  {n:>8,} rows  ({pct:5.1f}%)  {flag} {rich}")
    unmapped = (df["hour"] >= 22).sum()
    print(f"    {'hours_22_23 (excluded)':20s}  {unmapped:>8,} rows  "
          f"({unmapped/total*100:5.1f}%)  ℹ️  intentionally excluded")
    print()


def _run_dbscan_for_bucket(
    df_bucket: pd.DataFrame,
    bucket_name: str,
    is_data_rich: bool,
) -> pd.DataFrame | None:
    coords = df_bucket[["latitude", "longitude"]].values
    if len(coords) < MIN_SAMPLES:
        print(f"  [{bucket_name}] Only {len(coords)} points – skipping.")
        return None

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

    clustered = df_bucket[df_bucket["cluster_label"] != -1]
    n_clusters = clustered["cluster_label"].nunique()
    n_noise = (labels == -1).sum()
    print(
        f"  [{bucket_name}] {len(coords):,} pts → "
        f"{n_clusters} clusters, {n_noise:,} noise  "
        f"({'DATA-RICH' if is_data_rich else 'sparse'})"
    )

    if n_clusters == 0:
        return None

    records: list[dict] = []
    for cid, grp in clustered.groupby("cluster_label"):
        lats = grp["latitude"].values
        lons = grp["longitude"].values
        junctions = grp["junction_name"].dropna().tolist()
        top_j = Counter(junctions).most_common(1)
        top_junction_name = top_j[0][0] if top_j else None

        min_lat, max_lat = float(np.min(lats)), float(np.max(lats))
        min_lon, max_lon = float(np.min(lons)), float(np.max(lons))
        area_km2 = _bbox_area_km2(min_lat, max_lat, min_lon, max_lon)

        records.append({
            "cluster_id":    f"{bucket_name}_{int(cid)}",
            "time_bucket":   bucket_name,
            "centroid_lat":  float(np.mean(lats)),
            "centroid_lon":  float(np.mean(lons)),
            "member_count":  len(grp),
            "bbox_min_lat":  min_lat,
            "bbox_min_lon":  min_lon,
            "bbox_max_lat":  max_lat,
            "bbox_max_lon":  max_lon,
            "top_junction":  top_junction_name,
            "bbox_area_km2": round(area_km2, 6),
            # density = violations per km² within bbox
            "cluster_density": round(len(grp) / area_km2, 2),
            "is_data_rich":  int(is_data_rich),
        })

    return pd.DataFrame(records)


def _save_bucket_summary(clusters_df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    """Persist per-bucket aggregate summary for the frontend time-slider."""
    summary = (
        clusters_df.groupby("time_bucket")
        .agg(
            n_clusters=("cluster_id", "count"),
            total_members=("member_count", "sum"),
            avg_members=("member_count", "mean"),
            max_members=("member_count", "max"),
            is_data_rich=("is_data_rich", "first"),
        )
        .reset_index()
    )
    summary.to_sql("hotspot_summary_by_bucket", conn, if_exists="replace", index=False)
    print(f"  ✓ Saved bucket summary ({len(summary)} rows) → hotspot_summary_by_bucket")


def _validate_clusters(clusters_df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    known = set(
        pd.read_sql_query(
            "SELECT DISTINCT junction_name FROM violations "
            "WHERE junction_name IS NOT NULL",
            conn,
        )["junction_name"]
    )
    mapped = clusters_df["top_junction"].dropna()
    valid = mapped.isin(known).sum()
    print(f"\n  Validation: {valid}/{len(mapped)} top_junctions match known junctions.")
    top_freq = mapped.value_counts().head(10)
    print("  Top-10 junctions across clusters:")
    for jname, cnt in top_freq.items():
        print(f"    {jname}: {cnt} clusters")


# ── Main pipeline ────────────────────────────────────────────────────────

def run_hotspot_clustering(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Execute the full time-aware DBSCAN pipeline and persist results."""
    print("=" * 60)
    print("Hotspot DBSCAN Clustering  (ParkVisionSaathi)")
    print("=" * 60)

    conn = sqlite3.connect(str(db_path))
    try:
        df = _load_violations(conn)

        # ── Temporal cliff report ────────────────────────────────────────
        _temporal_cliff_check(df)

        # Compute total per bucket for data-richness flag
        total = len(df)
        df["time_bucket"] = df["hour"].apply(_assign_time_bucket)
        df = df.dropna(subset=["time_bucket"])
        print(f"  {len(df):,} violations mapped to defined time buckets.")

        bucket_sizes = df["time_bucket"].value_counts()

        all_clusters: list[pd.DataFrame] = []
        for bucket_name in TIME_BUCKETS:
            df_bucket = df[df["time_bucket"] == bucket_name]
            n = len(df_bucket)
            is_rich = (n / total) >= 0.10  # ≥10% of total = data-rich
            result = _run_dbscan_for_bucket(df_bucket, bucket_name, is_rich)
            if result is not None:
                all_clusters.append(result)

        if not all_clusters:
            print("  ⚠  No clusters found in any time bucket.")
            return pd.DataFrame()

        clusters_df = pd.concat(all_clusters, ignore_index=True)

        # ── Persist main table ────────────────────────────────────────────
        clusters_df.to_sql("hotspot_clusters", conn, if_exists="replace", index=False)
        print(f"\n  ✓ Saved {len(clusters_df)} cluster rows → hotspot_clusters")

        # ── Bucket summary for frontend ───────────────────────────────────
        _save_bucket_summary(clusters_df, conn)

        # ── Validate ──────────────────────────────────────────────────────
        _validate_clusters(clusters_df, conn)

        return clusters_df
    finally:
        conn.close()


def _print_summary(clusters_df: pd.DataFrame) -> None:
    if clusters_df.empty:
        print("  No clusters to summarize.")
        return

    print("\n" + "=" * 60)
    print("Summary Statistics")
    print("=" * 60)
    print(f"\n  Total clusters : {len(clusters_df)}")
    print(f"  Total members  : {clusters_df['member_count'].sum():,}")

    print("\n  Per time bucket:")
    for bucket, grp in clusters_df.groupby("time_bucket"):
        rich_flag = "✅ RICH" if grp["is_data_rich"].iloc[0] else "⚠️  sparse"
        print(
            f"    {bucket:20s}  clusters={len(grp):4d}  "
            f"members={grp['member_count'].sum():>7,}  "
            f"avg_size={grp['member_count'].mean():.1f}  {rich_flag}"
        )

    print("\n  Top-5 largest clusters:")
    for _, row in clusters_df.nlargest(5, "member_count").iterrows():
        print(
            f"    {row['cluster_id']:32s}  members={row['member_count']:>6,}  "
            f"density={row['cluster_density']:>8.1f}/km²  "
            f"junction={row['top_junction']}"
        )


# ── Entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        print("Run:  python scripts/seed_db.py  first.")
        sys.exit(1)

    result = run_hotspot_clustering()
    _print_summary(result)
    print("\nDone.")
