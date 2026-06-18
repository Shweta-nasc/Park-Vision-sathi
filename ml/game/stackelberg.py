"""
Stackelberg Mixed-Strategy Patrol Optimization
================================================

Computes optimal patrol probability distributions using a Stackelberg
game-theoretic model. The defender (police) commits to a mixed strategy
that maximises coverage of high-risk zones while accounting for
enforcement fatigue from past patrols.

Pipeline:
    1. Load ``risk_scores`` from SQLite.
    2. Generate synthetic patrol history (no real data yet) weighted by
       *inverse* risk so low-risk areas have a higher baseline patrol count.
    3. For every hour, compute:
       - baseline weight  w_i = risk_score_i ** alpha   (alpha = 1.5)
       - fatigue-adjusted weight  w_i / (1 + lambda * patrol_count_i)
       - normalised patrol probability
    4. Persist results to ``game_stackelberg`` and ``patrol_history`` tables.

Output table – ``game_stackelberg``:
    grid_cell_id, hour, grid_lat, grid_lon, risk_score,
    baseline_weight, adjusted_weight, patrol_probability
"""

from pathlib import Path
import sqlite3
import numpy as np
import pandas as pd

# ── Project paths ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"

# ── Hyper-parameters ──────────────────────────────────────────────────
ALPHA = 1.5          # risk-score exponent for baseline weight
LAMBDA_FATIGUE = 0.3  # enforcement-fatigue decay factor
RANDOM_SEED = 42


def load_risk_scores(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load the pre-computed risk_scores table."""
    query = """
        SELECT grid_cell_id, hour, grid_lat, grid_lon, risk_score,
               road_importance, peak_weight
        FROM risk_scores
    """
    df = pd.read_sql_query(query, conn)
    print(f"[stackelberg] Loaded {len(df):,} risk-score rows "
          f"({df['grid_cell_id'].nunique()} cells, "
          f"{df['hour'].nunique()} hours).")
    return df


def generate_synthetic_patrols(
    risk_df: pd.DataFrame,
    conn: sqlite3.Connection,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """Create synthetic patrol counts inversely weighted by risk.

    Low-risk zones are assumed to already receive more routine patrols,
    which the Stackelberg model should then *re-allocate* away from.

    Returns a DataFrame with columns: grid_cell_id, hour, patrol_count.
    """
    rng = np.random.default_rng(seed)

    # Higher risk → lower patrol probability (inverse weighting)
    max_risk = risk_df["risk_score"].max()
    inverse_weight = 1 - (risk_df["risk_score"] / (max_risk + 1e-9))
    # Map to probabilities for 0, 1, 2, 3
    # More inverse_weight → heavier towards 3
    probs_high = np.column_stack([
        0.1 + 0.3 * (1 - inverse_weight),  # P(0)
        0.2 + 0.1 * (1 - inverse_weight),  # P(1)
        0.3 - 0.1 * (1 - inverse_weight),  # P(2)
        0.4 - 0.3 * (1 - inverse_weight),  # P(3)
    ])
    # Normalise each row
    probs_high = probs_high / probs_high.sum(axis=1, keepdims=True)

    patrol_counts = np.array([
        rng.choice([0, 1, 2, 3], p=p) for p in probs_high
    ])

    patrol_df = risk_df[["grid_cell_id", "hour"]].copy()
    patrol_df["patrol_count"] = patrol_counts

    # Persist
    patrol_df.to_sql("patrol_history", conn, if_exists="replace", index=False)
    print(f"[stackelberg] Generated {len(patrol_df):,} synthetic patrol rows → "
          f"patrol_history table.  Mean patrols: {patrol_counts.mean():.2f}")
    return patrol_df


def compute_stackelberg(
    risk_df: pd.DataFrame,
    patrol_df: pd.DataFrame,
    alpha: float = ALPHA,
    lam: float = LAMBDA_FATIGUE,
) -> pd.DataFrame:
    """Compute mixed-strategy patrol probabilities per zone per hour."""

    merged = risk_df.merge(patrol_df, on=["grid_cell_id", "hour"], how="left")
    merged["patrol_count"] = merged["patrol_count"].fillna(0)

    # Baseline weight
    merged["baseline_weight"] = merged["risk_score"] ** alpha

    # Enforcement-fatigue adjustment
    merged["adjusted_weight"] = (
        merged["baseline_weight"] / (1 + lam * merged["patrol_count"])
    )

    # Normalise per hour
    hourly_sums = merged.groupby("hour")["adjusted_weight"].transform("sum")
    merged["patrol_probability"] = merged["adjusted_weight"] / (hourly_sums + 1e-12)

    result = merged[
        ["grid_cell_id", "hour", "grid_lat", "grid_lon", "risk_score",
         "baseline_weight", "adjusted_weight", "patrol_probability"]
    ].copy()

    print(f"[stackelberg] Computed patrol probabilities for "
          f"{len(result):,} zone-hour pairs.")
    return result


def save_results(df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    """Persist Stackelberg results to SQLite."""
    df.to_sql("game_stackelberg", conn, if_exists="replace", index=False)
    print(f"[stackelberg] Saved {len(df):,} rows → game_stackelberg table.")


def print_top_zones(df: pd.DataFrame, peak_hours: list | None = None) -> None:
    """Pretty-print the top-10 zones by patrol probability for peak hours."""
    if peak_hours is None:
        peak_hours = [8, 9, 10, 17, 18, 19]

    peak = df[df["hour"].isin(peak_hours)]
    top = (
        peak.groupby("grid_cell_id")
        .agg(
            avg_patrol_prob=("patrol_probability", "mean"),
            avg_risk=("risk_score", "mean"),
            grid_lat=("grid_lat", "first"),
            grid_lon=("grid_lon", "first"),
        )
        .sort_values("avg_patrol_prob", ascending=False)
        .head(10)
    )

    print("\n" + "=" * 80)
    print("TOP-10 ZONES BY PATROL PROBABILITY (Peak Hours)")
    print("=" * 80)
    print(f"{'Rank':<5} {'Grid Cell':<18} {'Avg P(patrol)':<15} "
          f"{'Avg Risk':<12} {'Lat':>9} {'Lon':>10}")
    print("-" * 80)
    for rank, (cell_id, row) in enumerate(top.iterrows(), 1):
        print(f"{rank:<5} {cell_id:<18} {row['avg_patrol_prob']:.6f}      "
              f"{row['avg_risk']:.2f}       "
              f"{row['grid_lat']:>9.4f} {row['grid_lon']:>10.4f}")
    print("=" * 80)


def run() -> pd.DataFrame:
    """End-to-end Stackelberg optimisation pipeline."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        risk_df = load_risk_scores(conn)
        patrol_df = generate_synthetic_patrols(risk_df, conn)
        result = compute_stackelberg(risk_df, patrol_df)
        save_results(result, conn)
        print_top_zones(result)

        # ── Quick validation ──
        print("\n── Validation ──")
        for hr in sorted(result["hour"].unique())[:3]:
            total_p = result.loc[result["hour"] == hr, "patrol_probability"].sum()
            print(f"  Hour {hr:>2}: sum(P) = {total_p:.6f}  "
                  f"(should be ≈ 1.0)")
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    run()
