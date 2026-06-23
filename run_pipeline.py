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
    python run_pipeline.py                # rekey + build res9 + calibrate + forecast (v1)
    python run_pipeline.py --multi-res    # also build zone_impact_res{5,7,8,9}.json
    python run_pipeline.py --skip-agent   # skip the calibration step
    python run_pipeline.py --skip-forecast  # skip the H3 forecast build
    python run_pipeline.py --v2           # OFFLINE calibrated v2 re-run (see below)

Offline calibrated v2 re-run (``--v2``)
---------------------------------------
A SEPARATE, reproducible, idempotent sequence that turns the uncalibrated v1
artifact + a frozen MapMyIndia ``congestion_observations.json`` snapshot into the
calibrated v2 artifact the backend can serve. It makes **no network calls** — the
live MapMyIndia collectors (``ml.enrichment.congestion_collector`` and
``ml.enrichment.adjacency``) are SEPARATE, manual, budget-guarded steps that must
be run first; this re-run only *consumes* their cached, frozen output.

Order (each step reads the previous step's artifact; deterministic / offline):

  1. validate_cis (v1 baseline)      → cis_validation_report_baseline.json
  2. calibrate_weights               → cis_calibration.json
  3. predict_degradation             → predicted_degradation.json
  4. build_calibrated_artifact       → zone_congestion_impact_v2.json
     (calibrated_bucket="all_day")     + cis_calibration_meta.json (sidecar)
  5. validate_cis (v2, served)       → cis_validation_report.json
  6. agent run_from_artifact (v2)    → calibrated_scores.json + agent_log.json
  7. build_h3_forecast_v2            → forecasts_v2.json + forecast_explanations.json
     (+ cached adjacency, + SHAP)

Idempotent: re-running on the same frozen observations snapshot reproduces the
same artifact contents (only embedded ``generated_at`` timestamps differ). We
measure the MIDDAY window, so ``calibrated_bucket="all_day"`` throughout (this is
not a peak-hour collection). Refuses to run if the v1 artifact or the
observations snapshot is absent — it never fabricates a calibration.
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

# ── Offline calibrated v2 re-run artifacts (--v2) ────────────────────────────
_PROC = PROJECT_ROOT / "data" / "processed"
_ENR = PROJECT_ROOT / "data" / "enriched"
V2_ARTIFACT_PATH = _PROC / "zone_congestion_impact_v2.json"
CALIBRATION_META_PATH = _PROC / "cis_calibration_meta.json"
OBSERVATIONS_PATH = _ENR / "congestion_observations.json"
VALIDATION_BASELINE_PATH = _PROC / "cis_validation_report_baseline.json"
VALIDATION_REPORT_PATH = _PROC / "cis_validation_report.json"
CALIBRATION_PATH = _PROC / "cis_calibration.json"
DEGRADATION_PATH = _PROC / "predicted_degradation.json"
CALIBRATED_SCORES_PATH = _PROC / "calibrated_scores.json"
AGENT_LOG_PATH = _PROC / "agent_log.json"
ADJACENCY_PATH = _ENR / "zone_adjacency.json"
FORECAST_V2_PATH = _PROC / "forecasts_v2.json"
FORECAST_EXPLANATIONS_PATH = _PROC / "forecast_explanations.json"
# We measure the midday window, so the calibrated headline bucket is all_day.
CALIBRATED_BUCKET = "all_day"


def _step(name: str) -> float:
    print("\n▶ " + name)
    print("─" * 64)
    return time.time()


def _done(t0: float) -> None:
    print(f"  ⏱  {time.time() - t0:.1f}s")


def run_v2_offline(csv_path: Path, *, skip_agent: bool = False,
                   skip_forecast: bool = False) -> None:
    """Offline, idempotent calibrated-v2 re-run (NO network).

    Consumes the uncalibrated v1 artifact + the frozen MapMyIndia
    ``congestion_observations.json`` snapshot (produced by the SEPARATE, manual,
    budget-guarded live collector) and produces the calibrated v2 artifact and its
    downstream reports, in the documented order. Refuses to run if a required
    input is missing — it never fabricates a calibration.
    """
    # Local imports so a missing optional dep surfaces a clear message here.
    from ml.congestion import calibrate_weights, predict_degradation, validate_cis
    from ml.congestion.build_calibrated_artifact import build_calibrated_artifact
    from ml.agent.validation_agent import run_from_artifact
    from ml.forecast.build_h3_forecast_v2 import build_h3_forecast_v2

    # ── Preconditions: never fabricate a calibration ─────────────────────────
    if not ARTIFACT_PATH.exists():
        print("⚠  v1 CIS artifact not found — run `python run_pipeline.py` first.")
        print(f"   expected: {ARTIFACT_PATH}")
        sys.exit(1)

    def _nonempty_json(path: Path) -> bool:
        if not path.exists():
            return False
        try:
            import json
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return isinstance(data, dict) and len(data) > 0
        except (ValueError, OSError):
            return False

    if not _nonempty_json(OBSERVATIONS_PATH):
        print("⚠  No congestion observations snapshot — cannot calibrate.")
        print(f"   expected: {OBSERVATIONS_PATH}")
        print("\n   Run the SEPARATE, budget-guarded live collector first (peak/midday window):")
        print("     python -m ml.enrichment.congestion_collector --dry-run   # preview cost")
        print("     python -m ml.enrichment.congestion_collector --budget <N> --top-n <N> --explore-n <N>")
        print("\n   This offline re-run only CONSUMES that frozen snapshot; it makes no API calls.")
        sys.exit(1)

    print("=" * 64)
    print("  ParkVision-Saathi — OFFLINE calibrated v2 re-run (no network)")
    print("=" * 64)
    print(f"  Raw CSV:       {csv_path}")
    print(f"  v1 artifact:   {ARTIFACT_PATH.relative_to(PROJECT_ROOT)}")
    print(f"  observations:  {OBSERVATIONS_PATH.relative_to(PROJECT_ROOT)}")
    print(f"  calibrated_bucket: {CALIBRATED_BUCKET}  (midday measurement)")
    total_t0 = time.time()

    # ── 1. validate_cis (v1 baseline — expert honest weights, the "before") ──
    t0 = _step("1 / 7  validate_cis (v1 baseline) → cis_validation_report_baseline.json")
    validate_cis.run(
        cis_artifact_path=ARTIFACT_PATH, observations_path=OBSERVATIONS_PATH,
        report_path=VALIDATION_BASELINE_PATH, calibration_path=None, verbose=True,
    )
    _done(t0)

    # ── 2. calibrate_weights (fit the 4 non-traffic weights to measured ratio) ─
    t0 = _step("2 / 7  calibrate_weights → cis_calibration.json")
    calibrate_weights.run(
        cis_artifact_path=ARTIFACT_PATH, observations_path=OBSERVATIONS_PATH,
        calibration_path=CALIBRATION_PATH, time_bucket=CALIBRATED_BUCKET, verbose=True,
    )
    _done(t0)

    # ── 3. predict_degradation (replace the flat 0.5 with a predicted value) ──
    t0 = _step("3 / 7  predict_degradation → predicted_degradation.json")
    predict_degradation.run(
        cis_artifact_path=ARTIFACT_PATH, observations_path=OBSERVATIONS_PATH,
        degradation_path=DEGRADATION_PATH, time_bucket=CALIBRATED_BUCKET, verbose=True,
    )
    _done(t0)

    # ── 4. build_calibrated_artifact (fitted weights + degradation override) ──
    t0 = _step("4 / 7  build_calibrated_artifact → zone_congestion_impact_v2.json (+ meta sidecar)")
    # build_calibrated_artifact -> build_congestion_artifact -> read_violations only
    # accepts a DataFrame or .parquet/.json (NOT a raw .csv), so read the CSV here
    # the same way the v1 pipeline (build_from_real_csv) does and pass the frame.
    import pandas as pd
    violations_df = pd.read_csv(csv_path, low_memory=False)
    build_calibrated_artifact(
        violations_df,
        calibration_path=CALIBRATION_PATH, degradation_path=DEGRADATION_PATH,
        validation_path=VALIDATION_BASELINE_PATH, traffic_context_path=REKEYED_TRAFFIC_PATH,
        observations_path=OBSERVATIONS_PATH, out_path=V2_ARTIFACT_PATH,
        meta_path=CALIBRATION_META_PATH, resolution=9, calibrated_bucket=CALIBRATED_BUCKET,
    )
    _done(t0)

    # ── 5. validate_cis (v2 — calibrated honest weights, the SERVED "after") ──
    t0 = _step("5 / 7  validate_cis (v2, served) → cis_validation_report.json")
    validate_cis.run(
        cis_artifact_path=V2_ARTIFACT_PATH, observations_path=OBSERVATIONS_PATH,
        report_path=VALIDATION_REPORT_PATH, calibration_path=CALIBRATION_PATH, verbose=True,
    )
    _done(t0)

    # ── 6. self-validating agent over v2 (report-only when calibrated) ───────
    if skip_agent:
        print("\n⏭  Skipping the self-validating agent (--skip-agent).")
    else:
        t0 = _step("6 / 7  agent run_from_artifact (v2) → calibrated_scores.json + agent_log.json")
        run_from_artifact(
            artifact_path=V2_ARTIFACT_PATH, calibrated_out=CALIBRATED_SCORES_PATH,
            log_out=AGENT_LOG_PATH, time_bucket=CALIBRATED_BUCKET,
            validation_path=VALIDATION_REPORT_PATH, calibration_path=CALIBRATION_PATH,
            degradation_path=DEGRADATION_PATH, verbose=True,
        )
        _done(t0)

    # ── 7. forecast v2 (+ cached adjacency, + SHAP sidecar) ──────────────────
    if skip_forecast:
        print("\n⏭  Skipping the v2 forecast build (--skip-forecast).")
    else:
        t0 = _step("7 / 7  build_h3_forecast_v2 → forecasts_v2.json + forecast_explanations.json")
        if not ADJACENCY_PATH.exists():
            print(f"   ℹ  no cached adjacency ({ADJACENCY_PATH.name}); neighbor lag is 0 "
                  "(honest no-change). Run `python -m ml.enrichment.adjacency` to add it.")
        build_h3_forecast_v2(
            csv_path=csv_path, adjacency_path=ADJACENCY_PATH,
            observations_path=OBSERVATIONS_PATH, out_path=FORECAST_V2_PATH,
            explain_out=FORECAST_EXPLANATIONS_PATH, compare=True,
        )
        _done(t0)

    print(f"\n{'=' * 64}")
    print(f"✅  Calibrated v2 re-run complete in {time.time() - total_t0:.1f}s")
    print(f"{'=' * 64}")
    print("\nv2 artifacts (the backend serves v2 when present; v1 remains the fallback):")
    for p in [
        "data/processed/zone_congestion_impact_v2.json",
        "data/processed/cis_calibration_meta.json",
        "data/processed/cis_calibration.json",
        "data/processed/predicted_degradation.json",
        "data/processed/cis_validation_report.json",
        "data/processed/calibrated_scores.json",
        "data/processed/agent_log.json",
        "data/processed/forecasts_v2.json",
        "data/processed/forecast_explanations.json",
    ]:
        fp = PROJECT_ROOT / p
        size = f"{fp.stat().st_size // 1024} KB" if fp.exists() else "NOT FOUND"
        print(f"  ✓  {p}  ({size})")
    print("\nVerify the served calibration:  curl localhost:8000/health  |  /validation/proof")


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate the backend's CIS data artifacts (no DB).")
    parser.add_argument("--multi-res", action="store_true",
                        help="Also build zone_impact_res{5,7,8,9}.json")
    parser.add_argument("--skip-agent", action="store_true",
                        help="Skip the self-validating agent calibration step")
    parser.add_argument("--skip-forecast", action="store_true",
                        help="Skip building the H3 forecast artifact")
    parser.add_argument("--v2", action="store_true",
                        help="Run the OFFLINE calibrated v2 re-run (consumes the frozen "
                             "observations snapshot; no network). See module docstring.")
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

    # ── Offline calibrated v2 re-run (separate, idempotent, no network) ──────
    if args.v2:
        run_v2_offline(csv_path, skip_agent=args.skip_agent, skip_forecast=args.skip_forecast)
        return

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
