"""
run_pipeline.py – Master runner for the full ParkVisionSaathi ML pipeline.

Run this ONCE to go from raw DB → all SQLite tables + JSON exports.

Steps
-----
0. (Optional) Seed DB with synthetic data if parkvision.db does not exist.
1. Hotspot DBSCAN clustering
2. Risk score computation + JSON export
3. Feature engineering
4. LightGBM training
5. Stackelberg + Blotto + What-If
6. Violator expected utility
7. Spillover simulation

Usage
-----
    # First time (no real DB):
    python scripts/seed_db.py
    python run_pipeline.py

    # With your real DB already in data/parkvision.db:
    python run_pipeline.py
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# ── Add sub-directories to sys.path so imports work ──────────────────────
sys.path.insert(0, str(PROJECT_ROOT / "ml"))
sys.path.insert(0, str(PROJECT_ROOT / "ml" / "forecast"))
sys.path.insert(0, str(PROJECT_ROOT / "ml" / "game"))

DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"


def step(name: str):
    print("\n" + "▶ " + name)
    print("─" * 60)
    return time.time()


def done(t0: float):
    print(f"  ⏱  {time.time() - t0:.1f}s")


def main():
    if not DB_PATH.exists():
        print("⚠  parkvision.db not found.")
        print("   Run:  python scripts/seed_db.py   to generate synthetic data.")
        sys.exit(1)

    total_t0 = time.time()

    # ── 1. Hotspot DBSCAN ─────────────────────────────────────────────────
    t0 = step("1 / 7  Hotspot DBSCAN Clustering")
    from hotspot_dbscan import run_hotspot_clustering
    run_hotspot_clustering(DB_PATH)
    done(t0)

    # ── 2. Risk scores ────────────────────────────────────────────────────
    t0 = step("2 / 7  Risk Score Computation")
    from risk_score import run_risk_scoring
    run_risk_scoring(DB_PATH)
    done(t0)

    # ── 3. Feature engineering ────────────────────────────────────────────
    t0 = step("3 / 7  Feature Engineering")
    from feature_engineering import build_feature_matrix, save_features
    features = build_feature_matrix(DB_PATH)
    save_features(features, DB_PATH)
    done(t0)

    # ── 4. LightGBM training ──────────────────────────────────────────────
    t0 = step("4 / 7  LightGBM Training")
    from train_model import (load_features, preprocess, train_model,
                              evaluate, save_model, save_feature_importance,
                              save_predictions, write_model_card)
    df = load_features(DB_PATH)
    X_train, X_test, y_train, y_test, id_train, id_test, feat_names = preprocess(df)
    model = train_model(X_train, y_train)
    preds, metrics = evaluate(model, X_test, y_test, id_test)
    save_model(model)
    save_feature_importance(model, feat_names)
    save_predictions(id_test, y_test, preds)
    write_model_card(metrics, len(X_train), len(X_test), feat_names)
    done(t0)

    # ── 5. Stackelberg + Blotto + What-If ─────────────────────────────────
    t0 = step("5 / 7  Stackelberg / Blotto / What-If")
    from stackelberg import run
    run()
    done(t0)

    # ── 6. Violator expected utility ──────────────────────────────────────
    t0 = step("6 / 7  Violator Expected Utility")
    from expected_utility import run as run_eu
    run_eu()
    done(t0)

    # ── 7. Spillover simulation ───────────────────────────────────────────
    t0 = step("7 / 7  Spillover Simulation")
    from spillover import run as run_spill
    run_spill()
    done(t0)

    total = time.time() - total_t0
    print(f"\n{'='*60}")
    print(f"✅  Full pipeline complete in {total:.1f}s")
    print(f"{'='*60}")
    print("\nSQLite tables created:")
    tables = [
        "violations", "hotspot_clusters", "hotspot_summary_by_bucket",
        "risk_scores", "forecast_features", "forecast_predictions",
        "patrol_history", "game_stackelberg", "game_blotto",
        "game_whatif", "game_violator_adaptation", "game_spillover",
    ]
    for t in tables:
        print(f"  ✓  {t}")

    print("\nJSON files for frontend:")
    json_files = [
        "data/risk_scores_by_hour.json",
        "data/whatif_coverage.json",
        "data/violator_utility.json",
        "data/spillover_arrows.json",
    ]
    for j in json_files:
        p = PROJECT_ROOT / j
        size = f"{p.stat().st_size // 1024} KB" if p.exists() else "NOT FOUND"
        print(f"  ✓  {j}  ({size})")

    print("\nModel artefacts:")
    print(f"  ✓  models/lightgbm_v1.pkl")
    print(f"  ✓  models/feature_importance.txt")
    print(f"  ✓  models/MODEL_CARD.md")


if __name__ == "__main__":
    main()
