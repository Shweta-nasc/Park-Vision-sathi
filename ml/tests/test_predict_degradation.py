"""
Tests for predicted traffic-degradation (``ml.congestion.predict_degradation``,
Task 4).
==============================================================================

Fixtures use **CIS-independent** labels: the measured ``congestion_ratio`` is
driven by a raw feature (a POI count / free-flow speed / component value) or is
random — never the CIS score.

Covers the Task 4 acceptance criteria:
* predictions are in [0, 1];
* measured zones are flagged ``source="measured"`` and equal the real transform;
* LOZO is leakage-free (the held-out label never influences its own prediction);
* too-few-zones falls back to 0.5 (with a logged warning).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pytest

from ml.congestion.impact_score import DEFAULT_TRAFFIC_DEGRADATION
from ml.congestion.predict_degradation import (
    FEATURE_NAMES,
    build_predictions,
    degradation_lookup,
    lozo_oof_predictions,
    ratio_to_degradation,
    run,
    _make_model,
)


# ─── transform ───────────────────────────────────────────────────────────────

def test_ratio_to_degradation_transform():
    assert ratio_to_degradation(1.0) == 0.0
    assert ratio_to_degradation(2.0) == 0.5
    assert ratio_to_degradation(3.0) == 1.0
    assert ratio_to_degradation(5.0) == 1.0  # clamped
    assert ratio_to_degradation(0.5) == 0.0  # clamped


# ─── fixtures (CIS-independent) ──────────────────────────────────────────────

def _make_artifact_obs(n_measured=40, n_unmeasured=60, seed=0, driver="poi"):
    """Build a CIS artifact + observations where the measured ratio is driven by
    a RAW feature (poi count or free-flow speed), not by the CIS score."""
    rng = np.random.default_rng(seed)
    artifact, obs = {}, {}

    def comps():
        c = rng.random(4)
        return {
            "lane_blockage": float(c[0]),
            "intersection_impact": float(c[1]),
            "access_blockage": float(c[2]),
            "vehicle_size": float(c[3]),
            "traffic_degradation": 0.5,
            "severity": 0.4,
        }

    for i in range(n_measured):
        h3 = f"89meas{i:04d}fff"
        artifact[h3] = {"all_day": {"components": comps(), "lat": 12.97, "lon": 77.59}}
        poi_n = i % 5  # 0..4 raw POI count
        ffs = 15.0 + (i % 7) * 3.0
        # ratio driven by a raw feature (CIS-independent), mild + bounded
        if driver == "poi":
            ratio = 1.0 + 0.3 * poi_n + rng.uniform(-0.05, 0.05)
        else:
            ratio = 1.0 + 0.05 * ffs + rng.uniform(-0.05, 0.05)
        obs[h3] = {
            "zone_id": h3,
            "congestion_ratio": round(float(max(1.0, ratio)), 3),
            "pois": [{"name": f"p{j}"} for j in range(poi_n)],
            "free_flow_speed_kmph": ffs,
            "is_exploration": False,
            "source": "synthetic_test",
        }

    for i in range(n_unmeasured):
        h3 = f"89unme{i:04d}fff"
        artifact[h3] = {"all_day": {"components": comps(), "lat": 12.98, "lon": 77.60}}

    return artifact, obs


# ─── build_predictions ───────────────────────────────────────────────────────

def test_predictions_in_unit_interval_and_sources():
    artifact, obs = _make_artifact_obs(40, 60, seed=1)
    report = build_predictions(artifact, obs)

    assert report["model"] == "ridge"
    assert report["n"] == 40
    assert report["n_predicted"] == 60
    assert list(report["features"]) == list(FEATURE_NAMES)

    measured = [z for z in report["zones"].values() if z["source"] == "measured"]
    predicted = [z for z in report["zones"].values() if z["source"] == "predicted"]
    assert len(measured) == 40 and len(predicted) == 60

    for z in report["zones"].values():
        assert 0.0 <= z["degradation"] <= 1.0


def test_measured_zones_equal_real_transform():
    artifact, obs = _make_artifact_obs(20, 10, seed=2)
    report = build_predictions(artifact, obs)
    for h3, o in obs.items():
        entry = report["zones"][h3]
        assert entry["source"] == "measured"
        assert entry["degradation"] == pytest.approx(
            round(ratio_to_degradation(o["congestion_ratio"]), 6)
        )


def test_lozo_metrics_present_and_reasonable():
    # Label cleanly driven by a raw feature -> LOZO should generalize.
    artifact, obs = _make_artifact_obs(50, 0, seed=3, driver="poi")
    report = build_predictions(artifact, obs)
    assert report["lozo_r2"] is not None
    assert report["lozo_spearman"] is not None
    assert -1.0 <= report["lozo_spearman"] <= 1.0


# ─── LOZO leakage-free ───────────────────────────────────────────────────────

def test_lozo_is_leakage_free():
    """Changing a held-out row's label must NOT change its own LOZO prediction."""
    rng = np.random.default_rng(7)
    X = rng.random((15, len(FEATURE_NAMES)))
    y = rng.random(15)

    oof_a = lozo_oof_predictions(X, y, _make_model)

    y2 = y.copy()
    k = 6
    y2[k] = 0.99 if y[k] < 0.5 else 0.01  # drastically change held-out label
    oof_b = lozo_oof_predictions(X, y2, _make_model)

    # Row k's own prediction is unchanged (its label was never used to predict it).
    assert oof_a[k] == pytest.approx(oof_b[k])
    # Other rows DO change (their fold's training set saw the modified y[k]).
    assert not np.allclose(np.delete(oof_a, k), np.delete(oof_b, k))


def test_lozo_predictions_clamped_to_unit_interval():
    rng = np.random.default_rng(9)
    X = rng.random((12, len(FEATURE_NAMES)))
    y = rng.random(12)
    oof = lozo_oof_predictions(X, y, _make_model)
    assert oof.min() >= 0.0 and oof.max() <= 1.0


# ─── fallback ────────────────────────────────────────────────────────────────

def test_fallback_when_too_few_measured(caplog):
    artifact, obs = _make_artifact_obs(3, 10, seed=4)  # 3 < MIN_TRAIN_FOR_MODEL
    with caplog.at_level(logging.WARNING):
        report = build_predictions(artifact, obs)
    assert report["model"] == "fallback_0.5"
    assert report["lozo_r2"] is None
    for h3 in list(obs)[:3]:
        assert report["zones"][h3]["source"] == "measured"
    unmeasured = [z for z in report["zones"].values() if z["source"] == "default_fallback"]
    assert unmeasured and all(z["degradation"] == DEFAULT_TRAFFIC_DEGRADATION for z in unmeasured)
    assert any("falling back" in rec.message for rec in caplog.records)


# ─── run + lookup ────────────────────────────────────────────────────────────

def test_run_writes_and_is_deterministic(tmp_path):
    artifact, obs = _make_artifact_obs(30, 20, seed=5)
    cis_path = tmp_path / "cis.json"
    obs_path = tmp_path / "obs.json"
    cis_path.write_text(json.dumps(artifact), encoding="utf-8")
    obs_path.write_text(json.dumps(obs), encoding="utf-8")

    out1 = tmp_path / "deg1.json"
    out2 = tmp_path / "deg2.json"
    ts = "2024-03-15T09:30:00+00:00"
    r1 = run(cis_path, obs_path, out1, generated_at=ts, verbose=False)
    r2 = run(cis_path, obs_path, out2, generated_at=ts, verbose=False)
    assert out1.read_bytes() == out2.read_bytes()
    assert r1 == r2

    lookup = degradation_lookup(r1)
    assert len(lookup) == 50
    assert all(0.0 <= v <= 1.0 for v in lookup.values())
