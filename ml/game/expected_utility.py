"""
Violator Expected Utility & Adaptation Model
==============================================

Models the *attacker* (violator) side of the Stackelberg game by
estimating the expected utility of committing a parking violation in
each zone during each hour.

Utility components:
    - **Benefit**: time saved by parking illegally minus search-time cost,
      converted to monetary value at ₹20/min.
    - **Expected cost**: patrol probability × fine amount (₹500).
    - **Net benefit**: benefit − expected_cost.
    - **Violator risk score**: sigmoid mapping of net_benefit to 0–100.

Output table – ``game_violator_adaptation``:
    grid_cell_id, hour, grid_lat, grid_lon, time_saved, search_time,
    benefit, expected_cost, net_benefit, violator_risk_score
"""

from pathlib import Path
import sqlite3
import numpy as np
import pandas as pd

# ── Project paths ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"

# ── Model parameters ──────────────────────────────────────────────────
FINE_AMOUNT = 500        # ₹500 default fine
TIME_VALUE_PER_MIN = 20  # ₹20 per minute saved
MAX_TIME_SAVED = 22.5    # practical ceiling (minutes)
SIGMOID_SCALE = 100      # divisor inside the sigmoid exponent


def load_stackelberg(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load Stackelberg patrol-probability results."""
    df = pd.read_sql_query(
        "SELECT grid_cell_id, hour, grid_lat, grid_lon, patrol_probability "
        "FROM game_stackelberg",
        conn,
    )
    print(f"[expected_utility] Loaded {len(df):,} Stackelberg rows.")
    return df


def load_risk_scores(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load risk scores with road_importance and peak_weight."""
    df = pd.read_sql_query(
        "SELECT grid_cell_id, hour, road_importance, peak_weight "
        "FROM risk_scores",
        conn,
    )
    print(f"[expected_utility] Loaded {len(df):,} risk-score rows.")
    return df


def compute_violator_utility(
    stackelberg_df: pd.DataFrame,
    risk_df: pd.DataFrame,
    fine: float = FINE_AMOUNT,
    time_value: float = TIME_VALUE_PER_MIN,
) -> pd.DataFrame:
    """Compute expected utility for a rational violator in every zone-hour.

    Returns
    -------
    pd.DataFrame
        Columns: grid_cell_id, hour, grid_lat, grid_lon, time_saved,
        search_time, benefit, expected_cost, net_benefit, violator_risk_score
    """
    merged = stackelberg_df.merge(
        risk_df, on=["grid_cell_id", "hour"], how="left"
    )

    # Fill missing road_importance / peak_weight with conservative defaults
    merged["road_importance"] = merged["road_importance"].fillna(0.5)
    merged["peak_weight"]     = merged["peak_weight"].fillna(1.0)

    # Time saved by parking illegally (minutes)
    merged["time_saved"] = (
        merged["road_importance"] * merged["peak_weight"] * 15
    ).clip(upper=MAX_TIME_SAVED)

    # Time spent searching for legal parking (minutes)
    merged["search_time"] = 5 + (1 - merged["road_importance"]) * 10

    # Net time benefit (minutes)
    merged["benefit"] = merged["time_saved"] - merged["search_time"]

    # Expected monetary cost of getting caught
    merged["expected_cost"] = merged["patrol_probability"] * fine

    # Net benefit in ₹
    merged["net_benefit"] = merged["benefit"] * time_value - merged["expected_cost"]

    # Sigmoid mapping → violator risk score (0–100)
    merged["violator_risk_score"] = (
        100 / (1 + np.exp(-merged["net_benefit"] / SIGMOID_SCALE))
    )

    result = merged[
        ["grid_cell_id", "hour", "grid_lat", "grid_lon",
         "time_saved", "search_time", "benefit",
         "expected_cost", "net_benefit", "violator_risk_score"]
    ].copy()

    print(f"[expected_utility] Computed violator utility for "
          f"{len(result):,} zone-hour pairs.")
    return result


def save_results(df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    """Persist violator adaptation results to SQLite."""
    df.to_sql("game_violator_adaptation", conn, if_exists="replace", index=False)
    print(f"[expected_utility] Saved {len(df):,} rows → "
          f"game_violator_adaptation table.")


def print_summary(df: pd.DataFrame) -> None:
    """Print zones most attractive to violators."""
    print("\n" + "=" * 85)
    print("VIOLATOR EXPECTED-UTILITY SUMMARY")
    print("=" * 85)

    # Overall stats
    print(f"\n  Violator risk score  – "
          f"min: {df['violator_risk_score'].min():.2f}, "
          f"mean: {df['violator_risk_score'].mean():.2f}, "
          f"max: {df['violator_risk_score'].max():.2f}")
    print(f"  Net benefit (₹)     – "
          f"min: {df['net_benefit'].min():.1f}, "
          f"mean: {df['net_benefit'].mean():.1f}, "
          f"max: {df['net_benefit'].max():.1f}")

    # Top-10 most attractive zones for violators
    top = (
        df.groupby("grid_cell_id")
        .agg(
            avg_vrs=("violator_risk_score", "mean"),
            avg_net=("net_benefit", "mean"),
            avg_time_saved=("time_saved", "mean"),
            avg_expected_cost=("expected_cost", "mean"),
            grid_lat=("grid_lat", "first"),
            grid_lon=("grid_lon", "first"),
        )
        .sort_values("avg_vrs", ascending=False)
        .head(10)
    )

    print(f"\n{'Rank':<5} {'Grid Cell':<18} {'Avg VRS':>9} {'Avg Net₹':>10} "
          f"{'TimeSaved':>10} {'ExpCost':>9} {'Lat':>9} {'Lon':>10}")
    print("-" * 85)
    for rank, (cell, row) in enumerate(top.iterrows(), 1):
        print(f"{rank:<5} {cell:<18} {row['avg_vrs']:>9.2f} "
              f"{row['avg_net']:>10.1f} "
              f"{row['avg_time_saved']:>10.1f} "
              f"{row['avg_expected_cost']:>9.2f} "
              f"{row['grid_lat']:>9.4f} {row['grid_lon']:>10.4f}")

    # Distribution buckets
    print("\n  Violator Risk Score Distribution:")
    for lo, hi, label in [
        (0, 30, "Low attraction"),
        (30, 50, "Neutral"),
        (50, 70, "Moderate attraction"),
        (70, 100.01, "High attraction"),
    ]:
        count = ((df["violator_risk_score"] >= lo)
                 & (df["violator_risk_score"] < hi)).sum()
        pct = count / len(df) * 100
        print(f"    {label:<22} [{lo:>5.0f}-{hi:>5.0f}): "
              f"{count:>8,} ({pct:.1f}%)")
    print("=" * 85)


def run() -> pd.DataFrame:
    """End-to-end violator expected-utility pipeline."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        stack_df = load_stackelberg(conn)
        risk_df = load_risk_scores(conn)
        result = compute_violator_utility(stack_df, risk_df)
        save_results(result, conn)
        print_summary(result)

        # ── Quick validation ──
        print("\n── Validation ──")
        print(f"  violator_risk_score range: "
              f"[{result['violator_risk_score'].min():.2f}, "
              f"{result['violator_risk_score'].max():.2f}] "
              f"(expected: 0–100)")
        assert result["violator_risk_score"].between(0, 100).all(), \
            "violator_risk_score out of [0, 100] range!"
        print("  ✓ All scores within valid range.")
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    run()
