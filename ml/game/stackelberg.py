"""
stackelberg.py – Stackelberg Mixed-Strategy Patrol Optimisation
================================================================

Models the DEFENDER (police) side of the game-theoretic framework.

Theory basis: Tambe et al. AAAI 2011 Security Games + Lei et al. 2017
Transportation Research Part B (parking enforcement Stackelberg).

What this implements
---------------------
1. **Stackelberg patrol probabilities** – risk-weighted allocation with
   enforcement-fatigue decay. Each hour's probabilities sum to 1.0.

2. **Colonel Blotto allocation** (NEW) – given K patrol teams, distributes
   them across zones proportional to Stackelberg probabilities. This is
   the *discrete* version of the Stackelberg mixed strategy. Both are the
   same allocation problem; we label both frameworks for the pitch.

3. **What-If simulation table** (NEW) – for every possible team count
   K ∈ {2, 4, 6, 8, 10}, compute which zones get a team assigned (top-K
   cells by patrol_probability) and what % of HIGH/CRITICAL risk cells are
   covered. Exported to ``game_whatif`` table and
   ``data/whatif_coverage.json`` for the frontend slider panel.

Output tables
-------------
- game_stackelberg         : per zone-hour patrol probabilities
- patrol_history           : synthetic baseline patrol counts
- game_blotto              : discrete team allocation (K=6 default)
- game_whatif              : coverage statistics per K
"""

from pathlib import Path
import json
import sqlite3
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH      = PROJECT_ROOT / "data" / "parkvision.db"
WHATIF_JSON  = PROJECT_ROOT / "data" / "whatif_coverage.json"

# ── Hyper-parameters ──────────────────────────────────────────────────────
ALPHA          = 1.5    # risk^alpha for baseline weight
LAMBDA_FATIGUE = 0.3    # fatigue decay
DEFAULT_K      = 6      # default patrol teams for Blotto
WHATIF_K_LIST  = [2, 4, 6, 8, 10, 15, 20]
RANDOM_SEED    = 42


# ── Loaders ───────────────────────────────────────────────────────────────

def load_risk_scores(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT grid_cell_id, hour, grid_lat, grid_lon, risk_score, "
        "       road_importance, peak_weight "
        "FROM risk_scores",
        conn,
    )
    print(f"[stackelberg] Loaded {len(df):,} risk-score rows "
          f"({df['grid_cell_id'].nunique()} cells, "
          f"{df['hour'].nunique()} hours).")
    return df


# ── Synthetic patrol history ──────────────────────────────────────────────

def generate_synthetic_patrols(risk_df: pd.DataFrame,
                                conn: sqlite3.Connection,
                                seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Inverse-risk patrol counts (low-risk zones get more routine patrols)."""
    rng = np.random.default_rng(seed)
    max_risk = risk_df["risk_score"].max()
    inv = 1 - (risk_df["risk_score"] / (max_risk + 1e-9))

    p = np.column_stack([
        0.1 + 0.3 * (1 - inv),
        0.2 + 0.1 * (1 - inv),
        0.3 - 0.1 * (1 - inv),
        0.4 - 0.3 * (1 - inv),
    ])
    p = p / p.sum(axis=1, keepdims=True)
    counts = np.array([rng.choice([0, 1, 2, 3], p=row) for row in p])

    patrol_df = risk_df[["grid_cell_id", "hour"]].copy()
    patrol_df["patrol_count"] = counts
    patrol_df.to_sql("patrol_history", conn, if_exists="replace", index=False)
    print(f"[stackelberg] Synthetic patrol history: mean={counts.mean():.2f}")
    return patrol_df


# ── Stackelberg computation ────────────────────────────────────────────────

def compute_stackelberg(risk_df: pd.DataFrame, patrol_df: pd.DataFrame,
                        alpha: float = ALPHA, lam: float = LAMBDA_FATIGUE) -> pd.DataFrame:
    merged = risk_df.merge(patrol_df, on=["grid_cell_id", "hour"], how="left")
    merged["patrol_count"]    = merged["patrol_count"].fillna(0)
    merged["baseline_weight"] = merged["risk_score"] ** alpha
    merged["adjusted_weight"] = (
        merged["baseline_weight"] / (1 + lam * merged["patrol_count"])
    )
    hourly_sum = merged.groupby("hour")["adjusted_weight"].transform("sum")
    merged["patrol_probability"] = merged["adjusted_weight"] / (hourly_sum + 1e-12)

    result = merged[[
        "grid_cell_id", "hour", "grid_lat", "grid_lon",
        "risk_score", "baseline_weight", "adjusted_weight", "patrol_probability",
    ]].copy()
    print(f"[stackelberg] Patrol probabilities computed for {len(result):,} zone-hours.")
    return result


# ── Colonel Blotto allocation (NEW) ──────────────────────────────────────

def compute_blotto(stackelberg_df: pd.DataFrame,
                   k: int = DEFAULT_K) -> pd.DataFrame:
    """
    Colonel Blotto: distribute K patrol teams across zones per hour.

    Each team is assigned to the zone with highest patrol_probability
    (greedy proportional). A zone can receive at most 1 team.
    If K > n_zones, every zone gets a team.

    Adds columns: teams_assigned (0/1), blotto_priority (rank within hour).
    """
    records = []
    for hour, grp in stackelberg_df.groupby("hour"):
        grp_sorted = grp.sort_values("patrol_probability", ascending=False).copy()
        n = len(grp_sorted)
        grp_sorted["blotto_priority"]  = range(1, n + 1)
        grp_sorted["teams_assigned"]   = (grp_sorted["blotto_priority"] <= k).astype(int)
        records.append(grp_sorted)

    blotto_df = pd.concat(records, ignore_index=True)
    n_assigned = blotto_df["teams_assigned"].sum()
    print(f"[blotto] K={k} teams → {n_assigned:,} zone-hour assignments "
          f"across {blotto_df['hour'].nunique()} hours.")
    return blotto_df


# ── What-If simulation (NEW) ──────────────────────────────────────────────

def compute_whatif(stackelberg_df: pd.DataFrame,
                   k_list: list[int] = WHATIF_K_LIST) -> pd.DataFrame:
    """
    For each K in k_list, compute per-hour coverage of HIGH/CRITICAL risk cells.

    Returns a DataFrame suitable for the frontend slider panel:
        k, hour, n_zones, n_high_critical, n_covered_high_critical, coverage_pct
    """
    records = []
    for hour, grp in stackelberg_df.groupby("hour"):
        grp_sorted = grp.sort_values("patrol_probability", ascending=False)
        n_total    = len(grp_sorted)
        # High/critical = risk_score ≥ 60
        high_crit_ids = set(grp_sorted[grp_sorted["risk_score"] >= 60]["grid_cell_id"])
        n_hc = len(high_crit_ids)

        for k in k_list:
            top_k_ids = set(grp_sorted.head(k)["grid_cell_id"])
            covered   = len(top_k_ids & high_crit_ids)
            cov_pct   = (covered / n_hc * 100) if n_hc > 0 else 0.0
            records.append({
                "k":                      k,
                "hour":                   int(hour),
                "n_zones":                n_total,
                "n_high_critical":        n_hc,
                "n_covered_high_critical": covered,
                "coverage_pct":           round(cov_pct, 2),
            })

    whatif_df = pd.DataFrame(records)
    print(f"[whatif] Computed {len(whatif_df):,} scenario rows "
          f"(k values: {k_list}).")
    return whatif_df


def export_whatif_json(whatif_df: pd.DataFrame, out_path: Path = WHATIF_JSON) -> None:
    """Export What-If data as JSON for the React simulation panel."""
    output = {}
    for k, grp in whatif_df.groupby("k"):
        # Aggregate across hours (mean coverage)
        avg_cov = grp["coverage_pct"].mean()
        output[str(k)] = {
            "avg_coverage_pct": round(avg_cov, 2),
            "by_hour": {
                str(row["hour"]): row["coverage_pct"]
                for _, row in grp.iterrows()
            },
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    print(f"[whatif] JSON exported → {out_path}  ({out_path.stat().st_size // 1024} KB)")


# ── Persistence ───────────────────────────────────────────────────────────

def save_results(stack_df: pd.DataFrame, blotto_df: pd.DataFrame,
                 whatif_df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    stack_df.to_sql("game_stackelberg",  conn, if_exists="replace", index=False)
    blotto_df.to_sql("game_blotto",      conn, if_exists="replace", index=False)
    whatif_df.to_sql("game_whatif",      conn, if_exists="replace", index=False)
    print(f"[stackelberg] Tables saved: game_stackelberg, game_blotto, game_whatif")


def print_top_zones(df: pd.DataFrame) -> None:
    peak_hours = [8, 9, 10, 17, 18, 19]
    peak = df[df["hour"].isin(peak_hours)]
    top = (
        peak.groupby("grid_cell_id")
        .agg(avg_p=("patrol_probability", "mean"), avg_risk=("risk_score", "mean"),
             grid_lat=("grid_lat", "first"), grid_lon=("grid_lon", "first"))
        .sort_values("avg_p", ascending=False)
        .head(10)
    )
    print("\n" + "=" * 80)
    print("TOP-10 ZONES BY PATROL PROBABILITY (Peak Hours)")
    print("=" * 80)
    print(f"{'Rank':<5}{'Grid Cell':<18}{'P(patrol)':>12}{'Risk':>8}{'Lat':>10}{'Lon':>11}")
    print("-" * 80)
    for i, (cell, row) in enumerate(top.iterrows(), 1):
        print(f"{i:<5}{cell:<18}{row['avg_p']:>12.6f}{row['avg_risk']:>8.2f}"
              f"{row['grid_lat']:>10.4f}{row['grid_lon']:>11.4f}")
    print("=" * 80)


# ── Main ──────────────────────────────────────────────────────────────────

def run() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        risk_df    = load_risk_scores(conn)
        patrol_df  = generate_synthetic_patrols(risk_df, conn)
        stack_df   = compute_stackelberg(risk_df, patrol_df)
        blotto_df  = compute_blotto(stack_df, k=DEFAULT_K)
        whatif_df  = compute_whatif(stack_df, k_list=WHATIF_K_LIST)
        save_results(stack_df, blotto_df, whatif_df, conn)
        conn.commit()
        export_whatif_json(whatif_df)
        print_top_zones(stack_df)

        print("\n── Validation ──")
        for hr in sorted(stack_df["hour"].unique())[:4]:
            total_p = stack_df.loc[stack_df["hour"] == hr, "patrol_probability"].sum()
            print(f"  Hour {hr:>2}: ΣP = {total_p:.6f}  (should be ≈ 1.0)")

        return stack_df
    finally:
        conn.close()


if __name__ == "__main__":
    run()
