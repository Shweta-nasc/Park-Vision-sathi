"""
Tests for CIS weight calibration (``ml.congestion.calibrate_weights``, Task 3).
==============================================================================

All fixtures use **CIS-independent** labels: the measured ``y`` is driven by a
single raw component (or random), never by the CIS weighted sum — so the fit is
never circular.

Covers the Task 3 acceptance criteria:
* fitted weights are >= 0 and sum to 1 ± 1e-9 (full 5-vector, td fixed at 0.25);
* when ``y`` depends only on ``lane_blockage``, the optimizer puts ~all mass there;
* the fit is reproducible for a fixed seed.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ml.congestion.calibrate_weights import (
    COMPONENTS_4,
    W_TD_FIXED,
    assemble_full_weights,
    build_calibration,
    fit_weights,
    old_normalized_weights,
    run,
)
from ml.congestion.impact_score import WEIGHTS, WEIGHT_SUM_TOLERANCE


def _rng(seed=0):
    return np.random.default_rng(seed)


def _components_matrix(n, seed=0):
    """Random 4-component matrix in [0,1] (the predictors)."""
    return _rng(seed).random((n, 4))


# ─── assemble_full_weights ───────────────────────────────────────────────────

def test_assemble_full_weights_sums_to_one_and_td_fixed():
    a4 = [0.25, 0.25, 0.25, 0.25]
    full = assemble_full_weights(a4)
    assert abs(sum(full.values()) - 1.0) < WEIGHT_SUM_TOLERANCE
    assert full["traffic_degradation"] == pytest.approx(W_TD_FIXED)
    # The four scaled components share the remaining (1 - td) mass.
    for i, c in enumerate(COMPONENTS_4):
        assert full[c] == pytest.approx(a4[i] * (1.0 - W_TD_FIXED))
    assert set(full) == set(WEIGHTS)


def test_assemble_full_weights_all_mass_on_one_component():
    full = assemble_full_weights([1.0, 0.0, 0.0, 0.0])
    assert abs(sum(full.values()) - 1.0) < WEIGHT_SUM_TOLERANCE
    assert full["lane_blockage"] == pytest.approx(1.0 - W_TD_FIXED)  # 0.75
    assert full["traffic_degradation"] == pytest.approx(W_TD_FIXED)  # 0.25


# ─── fit_weights ─────────────────────────────────────────────────────────────

def test_fit_weights_are_nonneg_and_sum_to_one():
    X = _components_matrix(60, seed=1)
    y = _rng(2).random(60)  # CIS-INDEPENDENT random label
    a, _ = fit_weights(X, y, seed=42, n_samples=2000)
    assert (a >= 0).all()
    assert a.sum() == pytest.approx(1.0, abs=1e-9)


def test_fit_puts_mass_on_lane_when_y_depends_only_on_lane():
    # y is a strictly increasing function of lane_blockage (column 0) ONLY.
    # The other three columns are independent noise -> CIS-independent label.
    X = _components_matrix(80, seed=3)
    X[:, 0] = np.linspace(0.0, 1.0, 80)        # lane_blockage spans [0,1]
    y = 1.0 + 1.5 * X[:, 0]                      # depends ONLY on lane_blockage
    a, train_rho = fit_weights(X, y, seed=7, n_samples=5000)

    assert int(np.argmax(a)) == 0, f"expected lane_blockage dominant, got {a}"
    assert a[0] > 0.5
    assert train_rho == pytest.approx(1.0)      # perfect rank match achievable


def test_fit_puts_mass_on_access_when_y_depends_only_on_access():
    # Same idea, different column (access_blockage = index 2). Non-negative
    # weights make the predictor monotonically INCREASING in each feature, so the
    # label must increase with the driving feature for it to be recoverable.
    X = _components_matrix(80, seed=5)
    X[:, 2] = np.linspace(0.0, 1.0, 80)
    y = 1.0 + 1.5 * X[:, 2]                      # monotone (increasing) in access only
    a, _ = fit_weights(X, y, seed=11, n_samples=5000)
    assert int(np.argmax(a)) == 2, f"expected access_blockage dominant, got {a}"


def test_fit_is_reproducible_for_seed():
    X = _components_matrix(50, seed=9)
    y = _rng(10).random(50)
    a1, r1 = fit_weights(X, y, seed=123, n_samples=3000)
    a2, r2 = fit_weights(X, y, seed=123, n_samples=3000)
    assert np.allclose(a1, a2)
    assert r1 == pytest.approx(r2)


def test_old_normalized_weights_sum_to_one():
    a = old_normalized_weights()
    assert a.sum() == pytest.approx(1.0)
    assert len(a) == 4


# ─── build_calibration (end-to-end, in-memory) ───────────────────────────────

def _artifact_and_obs(n=40, seed=0, label="lane"):
    """Build a CIS artifact + CIS-INDEPENDENT observations.

    The measured ratio is driven by a chosen RAW component column, never by the
    CIS weighted sum.
    """
    rng = _rng(seed)
    comp_idx = {"lane": 0, "intersection": 1, "access": 2, "vehicle": 3}[label]
    artifact, obs = {}, {}
    for i in range(n):
        h3 = f"89cal{i:04d}ffff"
        comps = rng.random(4)
        comps[comp_idx] = i / (n - 1)  # the driver spans [0,1] monotonically
        artifact[h3] = {
            "all_day": {
                "congestion_impact": 50.0,  # irrelevant to the label (not used)
                "components": {
                    "lane_blockage": float(comps[0]),
                    "intersection_impact": float(comps[1]),
                    "access_blockage": float(comps[2]),
                    "vehicle_size": float(comps[3]),
                    "traffic_degradation": 0.5,
                    "severity": 0.4,
                },
                "lat": 12.97, "lon": 77.59,
            }
        }
        # y depends ONLY on the chosen raw component (+ tiny independent noise).
        obs[h3] = {
            "zone_id": h3,
            "congestion_ratio": 1.0 + 1.5 * (i / (n - 1)),
            "is_exploration": False,
            "source": "synthetic_test",
        }
    return artifact, obs


def test_build_calibration_reports_weights_and_metrics():
    artifact, obs = _artifact_and_obs(n=40, seed=2, label="lane")
    report = build_calibration(artifact, obs, n_samples=4000)

    assert abs(sum(report["new_weights"].values()) - 1.0) < WEIGHT_SUM_TOLERANCE
    assert report["new_weights"]["traffic_degradation"] == pytest.approx(W_TD_FIXED)
    assert all(w >= 0 for w in report["new_weights"].values())
    assert report["n_train"] + report["n_test"] == 40
    # lane drives y -> lane should carry the largest non-td weight.
    non_td = {k: v for k, v in report["new_weights"].items() if k != "traffic_degradation"}
    assert max(non_td, key=non_td.get) == "lane_blockage"


def test_build_calibration_falls_back_when_insufficient_data():
    artifact, obs = _artifact_and_obs(n=3, seed=1, label="lane")
    report = build_calibration(artifact, obs, n_samples=1000)
    assert report["method"] == "fallback_insufficient_data"
    assert report["new_weights"] == WEIGHTS  # unchanged
    assert abs(sum(report["new_weights"].values()) - 1.0) < WEIGHT_SUM_TOLERANCE


def test_run_writes_report_and_is_deterministic(tmp_path):
    artifact, obs = _artifact_and_obs(n=40, seed=4, label="access")
    cis_path = tmp_path / "cis.json"
    obs_path = tmp_path / "obs.json"
    cis_path.write_text(json.dumps(artifact), encoding="utf-8")
    obs_path.write_text(json.dumps(obs), encoding="utf-8")

    out1 = tmp_path / "calib1.json"
    out2 = tmp_path / "calib2.json"
    ts = "2024-03-15T09:30:00+00:00"
    r1 = run(cis_path, obs_path, out1, generated_at=ts, n_samples=3000, verbose=False)
    r2 = run(cis_path, obs_path, out2, generated_at=ts, n_samples=3000, verbose=False)

    assert out1.exists()
    assert out1.read_bytes() == out2.read_bytes()
    assert r1 == r2
    # access drives y -> access should carry the largest non-td weight.
    non_td = {k: v for k, v in r1["new_weights"].items() if k != "traffic_degradation"}
    assert max(non_td, key=non_td.get) == "access_blockage"
