"""
run_pipeline.py — regenerate the backend's data artifacts (NO database).

This rebuilds the pre-computed JSON the FastAPI backend serves from memory. It is
a LOCAL developer tool: it reads the raw anonymized violation CSV (which is large
and git-ignored under ``dataset/``), so it only runs where that CSV is present.

It is NOT needed to deploy or run the API — the backend serves the committed JSON
artifacts and never runs this pipeline. (See the README "Deploy on Render" section.)

Steps (all database-free, deterministic, offline):
  1. Re-key the MapMyIndia enrichment to true H3 ids  → data/enriched/traffic_context_h3.json
  2. Build the Congestion Impact Score (CIS) artifact  → data/processed/zone_congestion_impact.json
     (optionally also multi-resolution res5/7/8/9 with --multi-res)
  3. Run the self-validating agent over the artifact   → data/processed/calibrated_scores.json
                                                          data/processed/agent_log.json
  4. Build the H3-native daily forecast (map-aligned)  → data/processed/forecasts.json

Usage
-----
    python run_pipeline.py                # rekey + build res9 + calibrate + forecast
    python run_pipeline.py --multi-res    # also build zone_impact_res{5,7,8,9}.json
    python run_pipeline.py --skip-agent   # skip the calibration step
    python run_pipeline.py --skip-forecast  # skip the H3 forecast build
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))  # make the `ml` package importable

ARTIFACT_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact.json"
REKEYED_TRAFFIC_PATH = PROJECT_ROOT / "data" / "enriched" / "traffic_context_h3.json"


def _step(name: str) -> float:
    print("\n▶ " + name)
    print("─" * 64)
    return time.time()


def _done(t0: float) -> None:
    print(f"  ⏱  {time.time() - t0:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate the backend's CIS data artifacts (no DB).")
    parser.add_argument("--multi-res", action="store_true",
                        help="Also build zone_impact_res{5,7,8,9}.json")
    parser.add_argument("--skip-agent", action="store_true",
                        help="Skip the self-validating agent calibration step")
    parser.add_argument("--skip-forecast", action="store_true",
                        help="Skip building the H3 forecast artifact")
    args = parser.parse_args()

    # Imports are local so a missing optional dep surfaces a clear message here
    # rather than at module load.
    from ml.congestion.build_artifact import (
        _resolve_real_csv, build_from_real_csv, build_multi_resolution,
    )
    from ml.enrichment.rekey_traffic_context import rekey
    from ml.agent.validation_agent import run_from_artifact
    from ml.forecast.build_h3_forecast import build_h3_forecast

    # The raw CSV is git-ignored (dataset/) and only exists locally.
    try:
        csv_path = _resolve_real_csv()
    except FileNotFoundError as e:
        print("⚠  Raw violations CSV not found — cannot regenerate artifacts.\n")
        print(str(e))
        print("\nThe committed artifacts in data/ are what the backend serves; you only")
        print("need this pipeline to REBUILD them from the raw dataset. Place the CSV in")
        print("one of the locations above and re-run.")
        sys.exit(1)

    print("=" * 64)
    print("  ParkVision-Saathi — data artifact pipeline (JSON + in-memory, no DB)")
    print("=" * 64)
    print(f"  Raw CSV: {csv_path}")
    total_t0 = time.time()

    # ── 1. Re-key the MapMyIndia enrichment to true H3 ids ───────────────────
    t0 = _step("1 / 4  Re-key MapMyIndia enrichment → traffic_context_h3.json")
    rekey()
    _done(t0)

    # ── 2. Build the Congestion Impact Score artifact(s) ─────────────────────
    if args.multi_res:
        t0 = _step("2 / 4  Build CIS artifacts (multi-resolution 5/7/8/9 + canonical res9)")
        build_multi_resolution(csv_path=csv_path, traffic_context_path=str(REKEYED_TRAFFIC_PATH))
        # The canonical res9 artifact the backend loads:
        build_from_real_csv(csv_path=csv_path, traffic_context_path=str(REKEYED_TRAFFIC_PATH),
                            out_path=str(ARTIFACT_PATH), resolution=9)
        _done(t0)
    else:
        t0 = _step("2 / 4  Build CIS artifact (res9) → zone_congestion_impact.json")
        build_from_real_csv(csv_path=csv_path, traffic_context_path=str(REKEYED_TRAFFIC_PATH),
                            out_path=str(ARTIFACT_PATH), resolution=9)
        _done(t0)

    # ── 3. Self-validating agent calibration ─────────────────────────────────
    if args.skip_agent:
        print("\n⏭  Skipping the self-validating agent (--skip-agent).")
    else:
        t0 = _step("3 / 4  Self-validating agent → calibrated_scores.json + agent_log.json")
        run_from_artifact(artifact_path=ARTIFACT_PATH, verbose=True)
        _done(t0)

    # ── 4. H3-native daily forecast (map-aligned) ────────────────────────────
    if args.skip_forecast:
        print("\n⏭  Skipping the H3 forecast build (--skip-forecast).")
    else:
        t0 = _step("4 / 4  H3 daily forecast → forecasts.json (LightGBM Poisson, real held-out metrics)")
        build_h3_forecast(csv_path=csv_path)
        _done(t0)

    print(f"\n{'=' * 64}")
    print(f"✅  Pipeline complete in {time.time() - total_t0:.1f}s")
    print(f"{'=' * 64}")
    print("\nArtifacts the backend serves (commit these for deployment):")
    for p in [
        "data/processed/zone_congestion_impact.json",
        "data/enriched/traffic_context_h3.json",
        "data/processed/calibrated_scores.json",
        "data/processed/agent_log.json",
        "data/processed/forecasts.json",
    ]:
        fp = PROJECT_ROOT / p
        size = f"{fp.stat().st_size // 1024} KB" if fp.exists() else "NOT FOUND"
        print(f"  ✓  {p}  ({size})")
    print("\nRun the API:  uvicorn backend.app.main:app --reload --port 8000")


if __name__ == "__main__":
    main()
