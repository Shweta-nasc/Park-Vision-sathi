"""
stackelberg.py – Stackelberg Mixed-Strategy Patrol Optimisation for ParkVisionSaathi.

Computes mixed-strategy patrol probabilities incorporating a fatigue adjustment
derived from real historical enforcement data (approved violations).
Also computes Colonel Blotto discrete team assignments and What-If coverage analytics.
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
LAMBDA_FATIGUE = 0.3    # fatigue decay factor
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


# ── Real patrol history ───────────────────────────────────────────────────

def compute_real_patrol_history(risk_df: pd.DataFrame,
                                conn: sqlite3.Connection) -> pd.DataFrame:
    """Derive patrol history from actual enforcement data.

    Approved violations imply police presence at that location/time,
    so we count approved violations per (grid_cell_id, hour) as a
    proxy for patrol frequency.
    """
    query = """
        SELECT grid_cell_id, hour,
               COUNT(*) as raw_count
        FROM violations
        WHERE validation_status_clean = 'approved'
          AND grid_cell_id IS NOT NULL
          AND hour IS NOT NULL
        GROUP BY grid_cell_id, hour
    """
    patrol_df = pd.read_sql_query(query, conn)

    if patrol_df.empty:
        print("[stackelberg] WARNING: No approved violations found, falling back to zero patrol counts.")
        patrol_df = risk_df[["grid_cell_id", "hour"]].copy()
        patrol_df["patrol_count"] = 0
    else:
        # Normalise to 0-3 range to match the fatigue model's expected scale
        max_count = patrol_df["raw_count"].max()
        if max_count > 0:
            patrol_df["patrol_count"] = (
                patrol_df["raw_count"] / max_count * 3
            ).round().astype(int).clip(0, 3)
        else:
            patrol_df["patrol_count"] = 0
        patrol_df = patrol_df.drop(columns=["raw_count"])

    # Persist patrol history
    patrol_df.to_sql("patrol_history", conn, if_exists="replace", index=False)
    print(f"[stackelberg] Computed real patrol history from approved violations: "
          f"{len(patrol_df):,} rows. Mean patrols: {patrol_df['patrol_count'].mean():.2f}")
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


# ── Colonel Blotto allocation ─────────────────────────────────────────────

def compute_blotto(stackelberg_df: pd.DataFrame,
                   k: int = DEFAULT_K) -> pd.DataFrame:
    """
    Colonel Blotto: distribute K patrol teams across zones per hour.

    Each team is assigned to the zone with highest patrol_probability.
    A zone can receive at most 1 team.
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
    print(f"[blotto] K={k} teams → {n_assigned:,} zone-hour assignments across {blotto_df['hour'].nunique()} hours.")
    return blotto_df


# ── What-If simulation ────────────────────────────────────────────────────

def compute_whatif(stackelberg_df: pd.DataFrame,
                   k_list: list[int] = WHATIF_K_LIST) -> pd.DataFrame:
    """
    For each K in k_list, compute per-hour coverage of HIGH/CRITICAL risk cells.
    """
    records = []
    for hour, grp in stackelberg_df.groupby("hour"):
        grp_sorted = grp.sort_values("patrol_probability", ascending=False)
        n_total    = len(grp_sorted)
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
    print(f"[whatif] Computed {len(whatif_df):,} scenario rows (k values: {k_list}).")
    return whatif_df


def export_whatif_json(whatif_df: pd.DataFrame, out_path: Path = WHATIF_JSON) -> None:
    """Export What-If data as JSON for the simulation panel."""
    output = {}
    for k, grp in whatif_df.groupby("k"):
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
    print(f"[whatif] JSON exported → {out_path} ({out_path.stat().st_size // 1024} KB)")


# ── Persistence ───────────────────────────────────────────────────────────

def save_results(stack_df: pd.DataFrame, blotto_df: pd.DataFrame,
                 whatif_df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    stack_df.to_sql("game_stackelberg",  conn, if_exists="replace", index=False)
    blotto_df.to_sql("game_blotto",      conn, if_exists="replace", index=False)
    whatif_df.to_sql("game_whatif",      conn, if_exists="replace", index=False)
    print("[stackelberg] Saved tables to SQLite: game_stackelberg, game_blotto, game_whatif")


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
        patrol_df  = compute_real_patrol_history(risk_df, conn)
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
