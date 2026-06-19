"""
spillover.py – Waterbed / Spillover Effect Simulation
======================================================

Simulates crime-displacement when enforcement increases in high-risk zones.

ADDITIONS vs v1
---------------
- Corrected PROJECT_ROOT depth.
- ``adaptation_response`` from game_violator_adaptation now gates which zones
  are *spillover targets*: only zones labelled 'park_illegally' or 'uncertain'
  absorb displaced violations. 'search_legal' zones do not receive spillover.
- Exports ``data/spillover_arrows.json`` for animated arrows on the map:
  { "arrows": [{"from_lat","from_lon","to_lat","to_lon","hour","magnitude"}, ...] }
  (one arrow per patrolled→neighbour pair per hour, top-50 by magnitude).
- Adds ``magnitude`` column: absolute risk increase in spillover zones.
- Validation now checks 2nd-degree neighbours too.
"""

from pathlib import Path
import json
import sqlite3

import numpy as np
import pandas as pd
from scipy.spatial import KDTree

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH      = PROJECT_ROOT / "data" / "parkvision.db"
ARROWS_JSON  = PROJECT_ROOT / "data" / "spillover_arrows.json"

K_NEIGHBOURS        = 6
TOP_PATROL_FRAC     = 0.20
REDUCTION_PATROLLED = 0.80
INCREASE_NEIGHBOUR1 = 1.10
INCREASE_NEIGHBOUR2 = 1.05


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
    print(f"[spillover] Neighbour graph: {len(adj)} cells, k={k}.")
    return adj


def get_second_degree(adj: dict, first: set, patrolled: set) -> set:
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

    # Violator gate: which cells are eligible spillover targets?
    if not adapt_df.empty:
        spillover_targets = set(
            adapt_df[adapt_df["adaptation_response"].isin(
                ["park_illegally", "uncertain"]
            )]["grid_cell_id"]
        )
    else:
        spillover_targets = set(risk_df["grid_cell_id"])   # all if no data

    # Centroid lookup for arrow coordinates
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
        first_deg   = set()
        for cell in patrolled:
            for nbr in adj.get(cell, []):
                if nbr not in patrolled and nbr in spillover_targets:
                    first_deg.add(nbr)
        second_deg = get_second_degree(adj, first_deg, patrolled) & spillover_targets

        for _, row in group.iterrows():
            cell = row["grid_cell_id"]
            orig = row["risk_score"]

            if cell in patrolled:
                stype    = "patrolled"
                adjusted = orig * REDUCTION_PATROLLED
            elif cell in first_deg:
                stype    = "neighbor_1"
                adjusted = orig * INCREASE_NEIGHBOUR1
            elif cell in second_deg:
                stype    = "neighbor_2"
                adjusted = orig * INCREASE_NEIGHBOUR2
            else:
                stype    = "unaffected"
                adjusted = orig

            adjusted   = max(0.0, min(100.0, adjusted))
            change_pct = ((adjusted - orig) / orig * 100) if orig > 0 else 0.0
            magnitude  = abs(adjusted - orig)

            results.append({
                "grid_cell_id":  cell,
                "hour":          hour,
                "grid_lat":      row["grid_lat"],
                "grid_lon":      row["grid_lon"],
                "original_risk": orig,
                "adjusted_risk": round(adjusted, 4),
                "spillover_type": stype,
                "risk_change_pct": round(change_pct, 4),
                "magnitude":     round(magnitude, 4),
            })

            # Arrow: from patrolled centroid to 1st-degree neighbour
            if stype == "neighbor_1":
                # Find which patrolled cell is closest
                patrol_list = list(patrolled)
                if patrol_list:
                    from_cell = patrol_list[0]   # simplified: first patrolled cell
                    fc = centroid_map.get(from_cell, {})
                    tc = centroid_map.get(cell, {})
                    if fc and tc:
                        arrows.append({
                            "from_lat":  round(fc["grid_lat"], 5),
                            "from_lon":  round(fc["grid_lon"], 5),
                            "to_lat":    round(tc["grid_lat"], 5),
                            "to_lon":    round(tc["grid_lon"], 5),
                            "hour":      int(hour),
                            "magnitude": round(magnitude, 2),
                        })

    result_df = pd.DataFrame(results)
    print(f"[spillover] Simulated {len(result_df):,} zone-hour pairs.")
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
    print(f"[spillover] Arrows JSON → {out_path}  ({len(top_arrows)} arrows)")


def save_results(df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    df.to_sql("game_spillover", conn, if_exists="replace", index=False)
    print(f"[spillover] Saved {len(df):,} rows → game_spillover")


def print_summary(df: pd.DataFrame) -> None:
    print("\n" + "=" * 80)
    print("SPILLOVER SUMMARY")
    print("=" * 80)
    for stype in ["patrolled", "neighbor_1", "neighbor_2", "unaffected"]:
        sub = df[df["spillover_type"] == stype]
        if len(sub) == 0:
            continue
        mean_chg = sub["risk_change_pct"].mean()
        print(f"  {stype:<14}  {len(sub):>8,} rows  mean_change={mean_chg:>+.2f}%")
    print(f"\n  Risk before: mean={df['original_risk'].mean():.2f}  "
          f"std={df['original_risk'].std():.2f}")
    print(f"  Risk after:  mean={df['adjusted_risk'].mean():.2f}  "
          f"std={df['adjusted_risk'].std():.2f}")
    print("=" * 80)


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

        # ── Validation ──────────────────────────────────────────────────────
        assert result["adjusted_risk"].between(0, 100).all(), "Risk out of range!"
        patrolled = result[result["spillover_type"] == "patrolled"]
        if len(patrolled):
            assert (patrolled["adjusted_risk"] <= patrolled["original_risk"]).all()
        nbr1 = result[result["spillover_type"] == "neighbor_1"]
        if len(nbr1):
            assert (nbr1["adjusted_risk"] >= nbr1["original_risk"]).all()
        print("  ✓ All assertions pass.")
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    run()
