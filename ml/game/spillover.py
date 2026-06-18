"""
Waterbed / Spillover Effect Simulation
========================================

Simulates the crime-displacement (waterbed) effect: when enforcement
increases in high-risk zones, violations spill over to neighbouring
cells.

Pipeline:
    1. Load ``risk_scores`` and ``game_stackelberg`` tables.
    2. Build a spatial neighbour graph via ``scipy.spatial.KDTree``
       (k = 6 nearest neighbours per cell).
    3. For each hour, identify the top-20 % of cells by patrol probability
       as *patrolled* zones, then:
       - Patrolled zones:       risk × 0.80  (−20 %)
       - 1st-degree neighbours: risk × 1.10  (+10 %)
       - 2nd-degree neighbours: risk × 1.05  (+5 %)
       - Others:                unchanged
    4. Clamp all adjusted risks to [0, 100].
    5. Persist results to ``game_spillover`` table.

Output table – ``game_spillover``:
    grid_cell_id, hour, grid_lat, grid_lon, original_risk,
    adjusted_risk, spillover_type, risk_change_pct
"""

from pathlib import Path
import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.spatial import KDTree

# ── Project paths ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"

# ── Hyper-parameters ──────────────────────────────────────────────────
K_NEIGHBOURS = 6         # neighbours per cell in the KDTree
TOP_PATROL_FRAC = 0.20   # fraction of cells considered "patrolled"
REDUCTION_PATROLLED = 0.80   # multiplier for patrolled zones
INCREASE_NEIGHBOUR1 = 1.10   # 1st-degree neighbour multiplier
INCREASE_NEIGHBOUR2 = 1.05   # 2nd-degree neighbour multiplier


def load_risk_scores(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load risk scores from SQLite."""
    df = pd.read_sql_query(
        "SELECT grid_cell_id, hour, grid_lat, grid_lon, risk_score "
        "FROM risk_scores",
        conn,
    )
    print(f"[spillover] Loaded {len(df):,} risk-score rows.")
    return df


def load_stackelberg(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load Stackelberg patrol probabilities."""
    df = pd.read_sql_query(
        "SELECT grid_cell_id, hour, patrol_probability "
        "FROM game_stackelberg",
        conn,
    )
    print(f"[spillover] Loaded {len(df):,} Stackelberg rows.")
    return df


def build_neighbour_graph(
    risk_df: pd.DataFrame,
    k: int = K_NEIGHBOURS,
) -> dict[str, list[str]]:
    """Build a spatial adjacency graph using KDTree on grid centroids.

    Parameters
    ----------
    risk_df : pd.DataFrame
        Must contain grid_cell_id, grid_lat, grid_lon.
    k : int
        Number of nearest neighbours per cell.

    Returns
    -------
    dict
        {cell_id: [neighbour_cell_ids]}
    """
    # Unique centroids
    centroids = (
        risk_df.groupby("grid_cell_id")[["grid_lat", "grid_lon"]]
        .first()
        .reset_index()
    )

    coords = centroids[["grid_lat", "grid_lon"]].values
    tree = KDTree(coords)

    # k+1 because query returns the point itself
    distances, indices = tree.query(coords, k=k + 1)

    cell_ids = centroids["grid_cell_id"].values
    adjacency: dict[str, list[str]] = {}
    for i, cell_id in enumerate(cell_ids):
        neighbour_indices = indices[i, 1:]  # skip self
        adjacency[cell_id] = [cell_ids[j] for j in neighbour_indices]

    print(f"[spillover] Built neighbour graph: {len(adjacency)} cells, "
          f"k={k} neighbours each.")
    return adjacency


def get_second_degree_neighbours(
    adjacency: dict[str, list[str]],
    first_degree_set: set[str],
    patrolled_set: set[str],
) -> set[str]:
    """Find 2nd-degree neighbours (neighbours of 1st-degree that are not
    already patrolled or 1st-degree)."""
    second_degree: set[str] = set()
    for cell in first_degree_set:
        for neighbour in adjacency.get(cell, []):
            if neighbour not in patrolled_set and neighbour not in first_degree_set:
                second_degree.add(neighbour)
    return second_degree


def simulate_spillover(
    risk_df: pd.DataFrame,
    stack_df: pd.DataFrame,
    adjacency: dict[str, list[str]],
    top_frac: float = TOP_PATROL_FRAC,
) -> pd.DataFrame:
    """Run the spillover simulation for every hour.

    Returns a DataFrame with columns:
        grid_cell_id, hour, grid_lat, grid_lon, original_risk,
        adjusted_risk, spillover_type, risk_change_pct
    """
    merged = risk_df.merge(
        stack_df[["grid_cell_id", "hour", "patrol_probability"]],
        on=["grid_cell_id", "hour"],
        how="left",
    )
    merged["patrol_probability"] = merged["patrol_probability"].fillna(0)

    results = []

    for hour, group in merged.groupby("hour"):
        n_patrolled = max(1, int(len(group) * top_frac))

        # Identify patrolled cells (top % by patrol probability this hour)
        patrolled_cells = set(
            group.nlargest(n_patrolled, "patrol_probability")["grid_cell_id"]
        )

        # 1st-degree neighbours of patrolled zones
        first_degree: set[str] = set()
        for cell in patrolled_cells:
            for nbr in adjacency.get(cell, []):
                if nbr not in patrolled_cells:
                    first_degree.add(nbr)

        # 2nd-degree neighbours
        second_degree = get_second_degree_neighbours(
            adjacency, first_degree, patrolled_cells
        )

        # Assign spillover type and multiplier
        for _, row in group.iterrows():
            cell = row["grid_cell_id"]
            orig = row["risk_score"]

            if cell in patrolled_cells:
                stype = "patrolled"
                adjusted = orig * REDUCTION_PATROLLED
            elif cell in first_degree:
                stype = "neighbor_1"
                adjusted = orig * INCREASE_NEIGHBOUR1
            elif cell in second_degree:
                stype = "neighbor_2"
                adjusted = orig * INCREASE_NEIGHBOUR2
            else:
                stype = "unaffected"
                adjusted = orig

            # Clamp to [0, 100]
            adjusted = max(0.0, min(100.0, adjusted))

            change_pct = (
                ((adjusted - orig) / orig * 100) if orig > 0 else 0.0
            )

            results.append({
                "grid_cell_id": cell,
                "hour": hour,
                "grid_lat": row["grid_lat"],
                "grid_lon": row["grid_lon"],
                "original_risk": orig,
                "adjusted_risk": round(adjusted, 4),
                "spillover_type": stype,
                "risk_change_pct": round(change_pct, 4),
            })

    result_df = pd.DataFrame(results)
    print(f"[spillover] Simulated spillover for "
          f"{len(result_df):,} zone-hour pairs.")
    return result_df


def save_results(df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    """Persist spillover results to SQLite."""
    df.to_sql("game_spillover", conn, if_exists="replace", index=False)
    print(f"[spillover] Saved {len(df):,} rows → game_spillover table.")


def print_summary(df: pd.DataFrame) -> None:
    """Print before/after risk stats and spillover examples."""
    print("\n" + "=" * 85)
    print("SPILLOVER / WATERBED EFFECT SUMMARY")
    print("=" * 85)

    # Type distribution
    type_counts = df["spillover_type"].value_counts()
    print("\n  Zone-hour classification:")
    for stype in ["patrolled", "neighbor_1", "neighbor_2", "unaffected"]:
        cnt = type_counts.get(stype, 0)
        pct = cnt / len(df) * 100
        print(f"    {stype:<14}: {cnt:>8,} ({pct:>5.1f}%)")

    # Before / After stats
    print(f"\n  Overall risk (before):  mean={df['original_risk'].mean():.2f}, "
          f"std={df['original_risk'].std():.2f}")
    print(f"  Overall risk (after):   mean={df['adjusted_risk'].mean():.2f}, "
          f"std={df['adjusted_risk'].std():.2f}")

    # Per-type stats
    print("\n  Mean risk change by type:")
    for stype in ["patrolled", "neighbor_1", "neighbor_2", "unaffected"]:
        subset = df[df["spillover_type"] == stype]
        if len(subset) > 0:
            mean_change = subset["risk_change_pct"].mean()
            print(f"    {stype:<14}: {mean_change:>+.2f}%")

    # Example spillover cases
    print("\n  Example spillover cases (top-5 largest risk increases):")
    top_spill = (
        df[df["spillover_type"].isin(["neighbor_1", "neighbor_2"])]
        .nlargest(5, "risk_change_pct")
    )
    print(f"    {'Cell':<18} {'Type':<12} {'Before':>8} {'After':>8} "
          f"{'Change':>8}")
    print("    " + "-" * 60)
    for _, row in top_spill.iterrows():
        print(f"    {row['grid_cell_id']:<18} {row['spillover_type']:<12} "
              f"{row['original_risk']:>8.2f} {row['adjusted_risk']:>8.2f} "
              f"{row['risk_change_pct']:>+8.2f}%")

    # Example patrolled reductions
    print("\n  Example patrolled reductions (top-5 largest risk decreases):")
    top_reduce = (
        df[df["spillover_type"] == "patrolled"]
        .nsmallest(5, "risk_change_pct")
    )
    print(f"    {'Cell':<18} {'Type':<12} {'Before':>8} {'After':>8} "
          f"{'Change':>8}")
    print("    " + "-" * 60)
    for _, row in top_reduce.iterrows():
        print(f"    {row['grid_cell_id']:<18} {row['spillover_type']:<12} "
              f"{row['original_risk']:>8.2f} {row['adjusted_risk']:>8.2f} "
              f"{row['risk_change_pct']:>+8.2f}%")

    print("=" * 85)


def run() -> pd.DataFrame:
    """End-to-end spillover simulation pipeline."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        risk_df = load_risk_scores(conn)
        stack_df = load_stackelberg(conn)
        adjacency = build_neighbour_graph(risk_df)
        result = simulate_spillover(risk_df, stack_df, adjacency)
        save_results(result, conn)
        print_summary(result)

        # ── Quick validation ──
        print("\n── Validation ──")
        assert result["adjusted_risk"].between(0, 100).all(), \
            "adjusted_risk out of [0, 100] range!"
        print("  ✓ All adjusted risks within [0, 100].")

        patrolled = result[result["spillover_type"] == "patrolled"]
        if len(patrolled) > 0:
            assert (patrolled["adjusted_risk"] <= patrolled["original_risk"]).all(), \
                "Patrolled zones should have reduced risk!"
            print("  ✓ Patrolled zones all have reduced risk.")

        nbr1 = result[result["spillover_type"] == "neighbor_1"]
        if len(nbr1) > 0:
            assert (nbr1["adjusted_risk"] >= nbr1["original_risk"]).all(), \
                "1st-degree neighbours should have increased risk!"
            print("  ✓ 1st-degree neighbours all have increased risk.")

        unaffected = result[result["spillover_type"] == "unaffected"]
        if len(unaffected) > 0:
            assert np.allclose(
                unaffected["adjusted_risk"], unaffected["original_risk"]
            ), "Unaffected zones should have unchanged risk!"
            print("  ✓ Unaffected zones have unchanged risk.")

        print(f"  Total zone-hours: {len(result):,}")
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    run()
