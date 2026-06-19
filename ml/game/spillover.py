"""
spillover.py – Waterbed / Spillover Effect Simulation for ParkVisionSaathi.

Simulates crime-displacement (waterbed effect) when police patrol coverage shifts 
violators to neighboring cells. Conserves system-wide total risk and gates 
spillover targets based on violator utility adaptation.
Exports displacement arrows to data/spillover_arrows.json.
"""

from pathlib import Path
import json
import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.spatial import KDTree

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH      = PROJECT_ROOT / "data" / "parkvision.db"
ARROWS_JSON  = PROJECT_ROOT / "data" / "spillover_arrows.json"

# ── Hyper-parameters ──────────────────────────────────────────────────────
K_NEIGHBOURS        = 6
TOP_PATROL_FRAC     = 0.20
REDUCTION_PATROLLED = 0.80   # patrolled zones lose 20% of baseline risk


# ── Loaders ───────────────────────────────────────────────────────────────

def load_risk_scores(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT grid_cell_id, hour, grid_lat, grid_lon, risk_score FROM risk_scores",
        conn
    )


def load_stackelberg(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT grid_cell_id, hour, patrol_probability FROM game_stackelberg",
        conn
    )


def load_violator_adaptation(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load adaptation_response for spillover gating."""
    try:
        df = pd.read_sql_query(
            "SELECT grid_cell_id, hour, adaptation_response "
            "FROM game_violator_adaptation",
            conn
        )
        print(f"[spillover] Loaded {len(df):,} violator adaptation rows.")
        return df
    except Exception:
        print("[spillover] ⚠️  game_violator_adaptation not found – skipping gating.")
        return pd.DataFrame()


# ── Neighbour graph ───────────────────────────────────────────────────────

def build_neighbour_graph(risk_df: pd.DataFrame,
                           k: int = K_NEIGHBOURS) -> dict[str, list[str]]:
    centroids = (
        risk_df.groupby("grid_cell_id")[["grid_lat", "grid_lon"]]
        .first().reset_index()
    )
    coords   = centroids[["grid_lat", "grid_lon"]].values
    tree     = KDTree(coords)
    _, idxs  = tree.query(coords, k=k + 1)
    cell_ids = centroids["grid_cell_id"].values
    adj: dict[str, list[str]] = {
        cell_ids[i]: [cell_ids[j] for j in idxs[i, 1:]]
        for i in range(len(cell_ids))
    }
    print(f"[spillover] Neighbour graph built: {len(adj)} cells, k={k}.")
    return adj


def get_second_degree_neighbours(adj: dict, first: set, patrolled: set) -> set:
    out: set = set()
    for c in first:
        for n in adj.get(c, []):
            if n not in patrolled and n not in first:
                out.add(n)
    return out


# ── Simulation ────────────────────────────────────────────────────────────

def simulate_spillover(risk_df: pd.DataFrame, stack_df: pd.DataFrame,
                        adj: dict[str, list[str]],
                        adapt_df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    merged = risk_df.merge(
        stack_df[["grid_cell_id", "hour", "patrol_probability"]],
        on=["grid_cell_id", "hour"], how="left"
    )
    merged["patrol_probability"] = merged["patrol_probability"].fillna(0)

    # Centroid lookup for coordinates
    centroid_map = (
        risk_df.groupby("grid_cell_id")[["grid_lat", "grid_lon"]]
        .first().to_dict("index")
    )

    results  = []
    arrows   = []

    for hour, group in merged.groupby("hour"):
        n_patrolled = max(1, int(len(group) * TOP_PATROL_FRAC))
        patrolled   = set(
            group.nlargest(n_patrolled, "patrol_probability")["grid_cell_id"]
        )

        # Hour-specific target gating: which cells are eligible spillover targets?
        if not adapt_df.empty:
            hour_adapt = adapt_df[adapt_df["hour"] == hour]
            spillover_targets = set(
                hour_adapt[hour_adapt["adaptation_response"].isin(
                    ["park_illegally", "uncertain"]
                )]["grid_cell_id"]
            )
        else:
            spillover_targets = set(group["grid_cell_id"])

        # 1st-degree neighbours of patrolled zones
        first_deg_all = set()
        for cell in patrolled:
            for nbr in adj.get(cell, []):
                if nbr not in patrolled:
                    first_deg_all.add(nbr)

        # Gate 1st-degree neighbours (fallback to all if gated set is empty)
        first_deg = first_deg_all & spillover_targets
        if not first_deg:
            first_deg = first_deg_all

        # 2nd-degree neighbours
        second_deg_all = get_second_degree_neighbours(adj, first_deg_all, patrolled)
        second_deg = second_deg_all & spillover_targets
        if not second_deg:
            second_deg = second_deg_all

        # Build a risk lookup for this hour
        risk_map = dict(zip(group["grid_cell_id"], group["risk_score"]))

        # --- Conservation-preserving displacement ---
        total_displaced = 0.0
        for cell in patrolled:
            orig = risk_map.get(cell, 0.0)
            total_displaced += orig * (1 - REDUCTION_PATROLLED)

        # Distribute displaced risk: 70% to N1, 30% to N2 (adjust if one set is empty)
        if first_deg and second_deg:
            displaced_n1 = total_displaced * 0.70
            displaced_n2 = total_displaced * 0.30
        elif first_deg:
            displaced_n1 = total_displaced
            displaced_n2 = 0.0
        elif second_deg:
            displaced_n1 = 0.0
            displaced_n2 = total_displaced
        else:
            displaced_n1 = 0.0
            displaced_n2 = 0.0

        n1_addition = displaced_n1 / len(first_deg) if first_deg else 0.0
        n2_addition = displaced_n2 / len(second_deg) if second_deg else 0.0

        # Step 3: Assign adjusted risks
        for _, row in group.iterrows():
            cell = row["grid_cell_id"]
            orig = row["risk_score"]

            if cell in patrolled:
                stype    = "patrolled"
                adjusted = orig * REDUCTION_PATROLLED
            elif cell in first_deg:
                stype    = "neighbor_1"
                adjusted = orig + n1_addition
            elif cell in second_deg:
                stype    = "neighbor_2"
                adjusted = orig + n2_addition
            else:
                stype    = "unaffected"
                adjusted = orig

            # Clamp adjusted risk to [0, 100]
            adjusted   = max(0.0, min(100.0, adjusted))
            change_pct = ((adjusted - orig) / orig * 100) if orig > 0 else 0.0
            magnitude  = abs(adjusted - orig)

            results.append({
                "grid_cell_id":  cell,
                "hour":          int(hour),
                "grid_lat":      row["grid_lat"],
                "grid_lon":      row["grid_lon"],
                "original_risk": orig,
                "adjusted_risk": round(adjusted, 4),
                "spillover_type": stype,
                "risk_change_pct": round(change_pct, 4),
                "magnitude":     round(magnitude, 4),
            })

            # Arrow: from patrolled centroid to 1st-degree neighbour
            if stype == "neighbor_1" and magnitude > 0.1:
                # Find which patrolled cells have this neighbor
                parent_patrols = [p for p in patrolled if cell in adj.get(p, [])]
                if parent_patrols:
                    # Select the closest patrolled cell
                    from_cell = parent_patrols[0]
                    tc_lat, tc_lon = row["grid_lat"], row["grid_lon"]
                    if len(parent_patrols) > 1:
                        min_dist = float('inf')
                        for p in parent_patrols:
                            fc = centroid_map.get(p)
                            if fc:
                                dist = (fc["grid_lat"] - tc_lat) ** 2 + (fc["grid_lon"] - tc_lon) ** 2
                                if dist < min_dist:
                                    min_dist = dist
                                    from_cell = p
                    
                    fc = centroid_map.get(from_cell, {})
                    if fc:
                        arrows.append({
                            "from_lat":  round(fc["grid_lat"], 5),
                            "from_lon":  round(fc["grid_lon"], 5),
                            "to_lat":    round(tc_lat, 5),
                            "to_lon":    round(tc_lon, 5),
                            "hour":      int(hour),
                            "magnitude": round(magnitude, 2),
                        })

    result_df = pd.DataFrame(results)
    print(f"[spillover] Simulated spillover for {len(result_df):,} zone-hour pairs.")
    return result_df, arrows


def export_arrows_json(arrows: list[dict], out_path: Path = ARROWS_JSON) -> None:
    """Export top-50 arrows per hour for animated map overlay."""
    by_hour: dict[str, list] = {}
    for a in arrows:
        h = str(a["hour"])
        by_hour.setdefault(h, []).append(a)

    # Keep top 50 by magnitude per hour
    top_arrows = []
    for h, hour_arrows in by_hour.items():
        top_arrows.extend(
            sorted(hour_arrows, key=lambda x: x["magnitude"], reverse=True)[:50]
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"arrows": top_arrows}, f, separators=(",", ":"))
    print(f"[spillover] Arrows JSON exported → {out_path} ({len(top_arrows)} arrows)")


def save_results(df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    df.to_sql("game_spillover", conn, if_exists="replace", index=False)
    print(f"[spillover] Saved results to SQLite table 'game_spillover'.")


def print_summary(df: pd.DataFrame) -> None:
    print("\n" + "=" * 85)
    print("SPILLOVER / WATERBED EFFECT SUMMARY")
    print("=" * 85)

    type_counts = df["spillover_type"].value_counts()
    print("\n  Zone-hour classification:")
    for stype in ["patrolled", "neighbor_1", "neighbor_2", "unaffected"]:
        cnt = type_counts.get(stype, 0)
        pct = cnt / len(df) * 100
        print(f"    {stype:<14}: {cnt:>8,} ({pct:>5.1f}%)")

    print(f"\n  Overall risk (before):  mean={df['original_risk'].mean():.2f}, std={df['original_risk'].std():.2f}")
    print(f"  Overall risk (after):   mean={df['adjusted_risk'].mean():.2f}, std={df['adjusted_risk'].std():.2f}")

    print("\n  Mean risk change by type:")
    for stype in ["patrolled", "neighbor_1", "neighbor_2", "unaffected"]:
        subset = df[df["spillover_type"] == stype]
        if len(subset) > 0:
            mean_change = subset["risk_change_pct"].mean()
            print(f"    {stype:<14}: {mean_change:>+.2f}%")
    print("=" * 85)


# ── Main ──────────────────────────────────────────────────────────────────

def run() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        risk_df   = load_risk_scores(conn)
        stack_df  = load_stackelberg(conn)
        adapt_df  = load_violator_adaptation(conn)
        adj       = build_neighbour_graph(risk_df)
        result, arrows = simulate_spillover(risk_df, stack_df, adj, adapt_df)
        save_results(result, conn)
        conn.commit()
        export_arrows_json(arrows)
        print_summary(result)

        # ── Validation ──
        print("\n── Validation ──")
        assert result["adjusted_risk"].between(0, 100).all(), "Risk out of range!"
        patrolled = result[result["spillover_type"] == "patrolled"]
        if len(patrolled):
            assert (patrolled["adjusted_risk"] <= patrolled["original_risk"]).all(), "Patrolled risk should decrease!"
        nbr1 = result[result["spillover_type"] == "neighbor_1"]
        if len(nbr1):
            assert (nbr1["adjusted_risk"] >= nbr1["original_risk"]).all(), "Neighbor 1 risk should increase/stay same!"
        print("  ✓ All assertions pass.")
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    run()
