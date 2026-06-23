"""
End-to-end calibration pipeline test (Task 14).
==============================================================================

Drives the WHOLE v2 chain on a tiny, CIS-INDEPENDENT fixture inside ``tmp_path``,
exactly in the order the real pipeline runs it:

    collector snapshot  →  validate_cis  →  calibrate_weights  →
    predict_degradation →  build_calibrated_artifact (v2 + sidecar)  →
    agent run_from_artifact  →  DataStore.load() + /health serving

and asserts the chain produces a coherent, trustable artifact:

* the v2 artifact is PURE (no ``_``-prefixed metadata key) and every per-zone
  breakdown validates against the contract (weights sum to 1, components in
  [0, 1], score in [0, 100]);
* a REAL weight fit ran (not the flat-abort / insufficient-data fallback) and the
  fitted weights still sum to 1;
* the DataStore serves v2 by default, marks it calibrated, and serves the
  calibrated headline bucket; ``/health`` reports ``calibrated: true``;
* the agent's offline ``calibration_run`` block is available and its coherence
  mode is consistent with whether a real fit was applied;
* ZERO synthetic leakage: the measured ratios are generated from a RAW feature
  (the double-parking count), never from the CIS score, and the honest trust
  metric provably EXCLUDES ``traffic_degradation`` (the measured signal) — so the
  proof cannot be circular.

The "collector" step is represented by writing its cached ``congestion_observations.json``
output directly (the demo replays from cached JSON; no network), with ratios
driven by the raw double-parking count + a deterministic jitter — strictly
CIS-independent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from backend.app.data_loader import CIS_CALIBRATION_META_FILENAME, DataStore, store
from backend.app.main import app
from backend.app.models import CongestionBreakdown
from fastapi.testclient import TestClient

from ml.agent.validation_agent import _calibration_applied, run_from_artifact
from ml.congestion import calibrate_weights, predict_degradation, validate_cis
from ml.congestion.build_artifact import build_congestion_artifact, h3_id_for
from ml.congestion.build_calibrated_artifact import build_calibrated_artifact
from ml.congestion.diff_top_zones import diff_top_zones
from ml.congestion.predict_degradation import ratio_to_degradation

MORNING_PEAK_TS = "2024-03-15T09:30:00+05:30"  # 09:30 IST -> morning_peak bucket
N_MEASURED = 24
N_UNMEASURED = 4


def _zone_specs():
    """Deterministic per-zone fixture specs (raw features, CIS-independent)."""
    specs = []
    for i in range(N_MEASURED + N_UNMEASURED):
        lat = round(12.95 + i * 0.012, 6)
        lon = round(77.55 + i * 0.011, 6)
        d = (i % 5) + 1          # double-parking rows (raw driver of lane_blockage)
        m = i % 3                # main-road rows
        j = 1 if i % 2 == 0 else 0
        vehicle = ("SCOOTER", "CAR", "BUS")[i % 3]
        measured = i < N_MEASURED
        explore = N_MEASURED - 4 <= i < N_MEASURED  # a few exploration zones
        # Ratio is a function of the RAW double-park count (+ jitter) — NEVER the CIS.
        ratio = round(1.0 + 0.16 * d + 0.002 * (i % 7), 4)
        specs.append({
            "i": i, "lat": lat, "lon": lon, "d": d, "m": m, "j": j,
            "vehicle": vehicle, "measured": measured, "explore": explore,
            "ratio": ratio, "h3": h3_id_for(lat, lon),
        })
    return specs


def _violations_df(specs) -> pd.DataFrame:
    rows = []
    for s in specs:
        def _row(violations, vehicle=s["vehicle"], junction="NO JUNCTION"):
            return {
                "latitude": s["lat"], "longitude": s["lon"],
                "created_datetime": MORNING_PEAK_TS,
                "violation_type": violations, "vehicle_type": vehicle,
                "updated_vehicle_type": None, "junction_name": junction,
                "police_station": "Upparpet",
            }
        for _ in range(s["d"]):
            rows.append(_row(["DOUBLE PARKING"]))
        for _ in range(s["m"]):
            rows.append(_row(["PARKING IN A MAIN ROAD"]))
        for _ in range(s["j"]):
            rows.append(_row(["PARKING NEAR ROAD CROSSING"], junction="Trinity Circle"))
        rows.append(_row(["PARKING ON FOOTPATH"]))  # access variety
    return pd.DataFrame(rows)


def _observations(specs) -> dict:
    """The collector's cached output (CIS-independent ratios)."""
    obs = {}
    for s in specs:
        if not s["measured"]:
            continue
        obs[s["h3"]] = {
            "zone_id": s["h3"], "lat": s["lat"], "lon": s["lon"],
            "congestion_ratio": s["ratio"],
            "n_legs": 4,
            "free_flow_speed_kmph": 20.0 + s["i"],
            "pois": ["TRNBUS"] * (s["i"] % 3),
            "is_exploration": s["explore"],
            "measured_at": MORNING_PEAK_TS,
            "method": "local_segment_v2", "source": "mapmyindia",
        }
    return obs


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    """Run the full v2 chain ONCE (module-scoped) and return artifact paths + reports.

    Module-scoped on purpose: the chain is deterministic, so building it once and
    sharing the read-only artifacts across the assertions keeps the suite fast and
    avoids running the heavy native scipy/sklearn stack many times over.
    """
    prev_env = os.environ.pop("CIS_ARTIFACT_PATH", None)
    try:
        specs = _zone_specs()
        df = _violations_df(specs)

        data_dir = tmp_path_factory.mktemp("e2e") / "data"
        processed = data_dir / "processed"
        enriched = data_dir / "enriched"
        processed.mkdir(parents=True)
        enriched.mkdir(parents=True)

        no_traffic = data_dir / "absent_traffic.json"  # no ratios -> defaulted v1
        obs_path = enriched / "congestion_observations.json"
        obs_path.write_text(json.dumps(_observations(specs)), encoding="utf-8")

        v1_path = processed / "zone_congestion_impact.json"
        v2_path = processed / "zone_congestion_impact_v2.json"
        meta_path = processed / CIS_CALIBRATION_META_FILENAME
        report_path = processed / "cis_validation_report.json"
        calib_path = processed / "cis_calibration.json"
        deg_path = processed / "predicted_degradation.json"
        absent_cal = data_dir / "absent_calibration.json"

        # 1) v1 (uncalibrated) artifact from the raw violations.
        build_congestion_artifact(df, traffic_context_path=no_traffic, out_path=v1_path)

        # 2) validate (baseline trust — expert honest weights, no calibration yet).
        validate_cis.run(cis_artifact_path=v1_path, observations_path=obs_path,
                         report_path=report_path, calibration_path=absent_cal, verbose=False)

        # 3) calibrate weights against the measured ratio.
        calibrate_weights.run(cis_artifact_path=v1_path, observations_path=obs_path,
                              calibration_path=calib_path, n_samples=2000, verbose=False)

        # 4) predict the degradation component for every zone.
        predict_degradation.run(cis_artifact_path=v1_path, observations_path=obs_path,
                                degradation_path=deg_path, verbose=False)

        # 5) build the calibrated v2 artifact + its metadata sidecar.
        build_calibrated_artifact(
            df, calibration_path=calib_path, degradation_path=deg_path,
            validation_path=report_path, traffic_context_path=no_traffic,
            observations_path=obs_path, out_path=v2_path, meta_path=meta_path,
            calibrated_bucket="morning_peak", generated_at="2024-03-15T00:00:00+00:00",
        )

        # 6) agent run over v2 (reads the calibration sidecar for coherence + the run block).
        _, summary = run_from_artifact(
            v2_path, calibrated_out=processed / "calibrated_scores.json",
            log_out=processed / "agent_log.json", verbose=False,
            validation_path=report_path, calibration_path=calib_path, degradation_path=deg_path,
        )

        yield {
            "data_dir": data_dir, "v1_path": v1_path, "v2_path": v2_path,
            "meta_path": meta_path, "calib_path": calib_path, "deg_path": deg_path,
            "report_path": report_path, "summary": summary, "specs": specs,
        }
    finally:
        if prev_env is not None:
            os.environ["CIS_ARTIFACT_PATH"] = prev_env


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ─── v2 artifact: pure + contract-valid ──────────────────────────────────────

def test_v2_artifact_is_pure_and_contract_valid(pipeline):
    v2 = _load(pipeline["v2_path"])
    assert v2, "v2 artifact should be non-empty"
    # PURE: no metadata key leaked into the data (Option A).
    assert all(not k.startswith("_") for k in v2)
    for buckets in v2.values():
        assert "morning_peak" in buckets and "all_day" in buckets
        for breakdown in buckets.values():
            model = CongestionBreakdown.model_validate(breakdown)
            assert abs(sum(model.weights.values()) - 1.0) < 1e-9
            assert 0.0 <= model.congestion_impact <= 100.0
            comps = model.components
            for c in (comps.lane_blockage, comps.intersection_impact,
                      comps.traffic_degradation, comps.access_blockage, comps.vehicle_size):
                assert 0.0 <= c <= 1.0


# ─── calibration: a REAL fit ran, weights sum to 1 ───────────────────────────

def test_calibration_is_a_real_fit_with_unit_weights(pipeline):
    report = _load(pipeline["calib_path"])
    assert report["method"] == calibrate_weights.METHOD_TAG, (
        f"expected a real fit, got {report['method']!r}"
    )
    assert abs(sum(report["new_weights"].values()) - 1.0) < 1e-9
    # traffic_degradation stays the fixed measured-signal weight.
    assert report["new_weights"]["traffic_degradation"] == pytest.approx(0.25)


# ─── degradation: measured == real transform; predicted zones exist ──────────

def test_degradation_measured_real_transform_and_predicted_present(pipeline):
    report = _load(pipeline["deg_path"])
    assert report["model"] == "ridge"  # >= 5 measured -> a real model, not 0.5 fallback
    zones = report["zones"]
    sources = {v["source"] for v in zones.values()}
    assert "measured" in sources and "predicted" in sources

    by_h3 = {s["h3"]: s for s in pipeline["specs"]}
    for h3, rec in zones.items():
        if rec["source"] == "measured":
            expected = round(ratio_to_degradation(by_h3[h3]["ratio"]), 6)
            assert rec["degradation"] == pytest.approx(expected)


# ─── DataStore serves v2, calibrated, headline bucket = morning_peak ─────────

def test_datastore_serves_calibrated_v2(pipeline):
    s = DataStore(data_dir=pipeline["data_dir"]).load()
    assert s.cis_artifact_path.name == "zone_congestion_impact_v2.json"
    assert s.calibration_meta["calibrated"] is True
    assert s.calibration_meta["calibrated_bucket"] == "morning_peak"
    assert s.headline_bucket == "morning_peak"
    assert s.congestion, "served congestion universe should be non-empty"

    zone = next(iter(s.congestion))
    peak = s.congestion_breakdown(zone, "morning_peak")
    allday = s.congestion_breakdown(zone, "all_day")
    assert peak["time_regime"] == "calibrated"
    assert allday["time_regime"] == "uncalibrated"


def test_health_reports_calibrated_true(pipeline):
    # Repoint the module-level singleton at the tmp artifacts, snapshot/restore so
    # the suite stays order-independent. TestClient(app) without its context
    # manager skips the startup load(), so our injected state is served as-is.
    saved = dict(store.__dict__)
    try:
        store.data_dir = pipeline["data_dir"]
        store.loaded = False
        store.load()
        body = TestClient(app).get("/health").json()
        assert body["calibration"]["calibrated"] is True
        assert body["calibrated_bucket"] == "morning_peak"
        assert body["headline_bucket"] == "morning_peak"
    finally:
        store.__dict__.clear()
        store.__dict__.update(saved)


# ─── agent calibration_run available + coherent ──────────────────────────────

def test_agent_calibration_run_available_and_coherent(pipeline):
    summary = pipeline["summary"]
    block = summary["calibration_run"]
    assert block["available"] is True
    # Coherence: report-only iff a real weight fit was applied; else legacy nudge.
    calib_report = _load(pipeline["calib_path"])
    expected_mode = "report_only" if _calibration_applied(calib_report) else "legacy_nudge"
    assert summary["coherence_mode"] == expected_mode


# ─── zero synthetic leakage: the honest trust metric is non-circular ─────────

def test_zero_synthetic_leakage_honest_excludes_traffic_degradation(pipeline):
    report = _load(pipeline["report_path"])
    # The honest predictor provably drops the measured signal -> not circular.
    assert report["honest_excludes"] == "traffic_degradation"
    assert "traffic_degradation" not in report["honest_weights"]
    assert set(report["honest_weights"]) == {
        "lane_blockage", "intersection_impact", "access_blockage", "vehicle_size",
    }


# ─── v1 ↔ v2 top-zone diff runs on the real chain output ─────────────────────

def test_diff_top_zones_on_pipeline_output(pipeline):
    v1 = _load(pipeline["v1_path"])
    v2 = _load(pipeline["v2_path"])
    diff = diff_top_zones(v1, v2, top_n=15)
    # Both top lists are valid, descending-CIS rankings.
    for key in ("v1_top", "v2_top"):
        cis_seq = [z["cis"] for z in diff[key]]
        assert cis_seq == sorted(cis_seq, reverse=True)
    # Adds and drops are symmetric in count (same list length).
    assert diff["n_added"] == diff["n_dropped"]
