# ParkVision-Saathi — Build Status

> **Read this before assuming the `data/` directory is incomplete.** Empty
> calibration artifacts are *expected* until the live MapMyIndia collector run.

## Where things stand

- **Tasks 1–9 (machinery): built + tested offline.** The full calibration
  pipeline, calibrated-CIS wiring (additive-shadow), self-validating agent,
  throughput simulation, MapMyIndia road features, and bias/SHAP layer all exist
  with passing tests. Run `python -m pytest -q` from the repo root.
- **Sections 10–11 (credibility hardening): in progress.** Non-circular trust
  metric (density≠impact proof), bootstrap CIs, flat-variance abort, immutable
  snapshots, calibration-coherence fixes, the proof visual, an end-to-end
  pipeline test, and the rehearsed weak/aborted fallback.

## Why `data/processed` looks "empty" of calibration outputs

The hard **data boundary**: real calibration numbers come ONLY from a live,
peak-time MapMyIndia collector run. Until that run, these files are intentionally
absent and the system serves the honest v1 baseline:

| Artifact | Produced by | Status |
| --- | --- | --- |
| `data/enriched/congestion_observations.json` | Task 1 collector (live, peak) | pending live run |
| `data/processed/cis_validation_report.json` | Task 2 / 10 | pending |
| `data/processed/cis_calibration.json` | Task 3 | pending |
| `data/processed/predicted_degradation.json` | Task 4 | pending |
| `data/processed/zone_congestion_impact_v2.json` | Task 5 builder | pending |
| `data/processed/cis_calibration_meta.json` | Task 5 sidecar | pending |
| `data/enriched/zone_adjacency.json` | Task 8 | pending |
| `data/processed/forecasts_v2.json` | Task 8 forecast v2 | pending |
| `data/processed/forecast_explanations.json` | Task 9 SHAP | pending |

Until v2 exists, the backend **falls back to v1** (`zone_congestion_impact.json`),
`/health` reports `cis_version: v1, calibrated: false`, and every "pending" block
(`calibration_run.available`, `measured_minutes.available`, `/validation/proof`,
`/forecast/explanations`) reports honestly rather than fabricating numbers.

**No synthetic calibration numbers are ever committed.** All synthetic data lives
only in tests (`ml/tests/`) and is CIS-independent.

## After the live run (data-boundary runbook)

1. Pilot a few zones, then full collection at a real Bengaluru congestion window
   (~08:00–11:00 / 18:00–20:00 IST).
2. Build adjacency (`python -m ml.enrichment.adjacency`).
3. Re-run Tasks 2 → 3 → 4 → 5 → 6 → 10 → 11.
4. Promote v2 (it auto-serves once `zone_congestion_impact_v2.json` exists; or set
   `CIS_ARTIFACT_PATH`).
5. Light up the proof visual, run `diff_top_zones`, set `calibration_strength`,
   and update `DEMO_SCRIPT.md` / `JUDGE_QA.md` with the real numbers.

To revert to v1 at any time: remove/rename the v2 artifact or unset
`CIS_ARTIFACT_PATH`.
