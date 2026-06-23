"""
Tests for the CIS validation harness (``ml.congestion.validate_cis``, Task 2).
==============================================================================

Covers the Task 2 acceptance criteria:
* Spearman == 1.0 on synthetic monotonic data;
* the train/test split is deterministic across runs (and process-stable);
* n < 5 returns null correlations + a logged warning (no crash);
* the join, exploration subset, and written report behave as specified.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ml.congestion import validate_cis as vc
from ml.congestion.validate_cis import (
    MIN_POINTS_FOR_CORR,
    NON_TRAFFIC_COMPONENTS,
    TRAFFIC_COMPONENT,
    build_report,
    deterministic_split,
    honest_weights,
    join_points,
    pearson,
    run,
    spearman,
)


def _cis_artifact(scores: dict[str, float]) -> dict:
    """{h3_id: {all_day: {congestion_impact: x, ...}}} for the given scores."""
    return {
        h3: {"all_day": {"congestion_impact": s, "lat": 12.97, "lon": 77.59}}
        for h3, s in scores.items()
    }


def _observations(ratios: dict[str, float], exploration: set[str] | None = None) -> dict:
    exploration = exploration or set()
    return {
        h3: {
            "zone_id": h3,
            "congestion_ratio": r,
            "is_exploration": h3 in exploration,
        }
        for h3, r in ratios.items()
    }


# ─── Correlations ────────────────────────────────────────────────────────────

def test_spearman_is_one_on_monotonic_data():
    cis = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    ratio = [1.05, 1.10, 1.30, 1.60, 1.90, 2.40]  # strictly increasing with cis
    assert spearman(cis, ratio) == 1.0


def test_spearman_is_minus_one_on_antitone_data():
    cis = [10.0, 20.0, 30.0, 40.0, 50.0]
    ratio = [2.4, 2.0, 1.6, 1.3, 1.1]
    assert spearman(cis, ratio) == -1.0


def test_correlation_none_below_min_points():
    cis = [10.0, 20.0, 30.0]  # 3 < MIN_POINTS_FOR_CORR (5)
    ratio = [1.1, 1.2, 1.3]
    assert spearman(cis, ratio) is None
    assert pearson(cis, ratio) is None


def test_correlation_none_on_constant_input():
    cis = [30.0, 30.0, 30.0, 30.0, 30.0]
    ratio = [1.1, 1.2, 1.3, 1.4, 1.5]
    assert spearman(cis, ratio) is None
    assert pearson(cis, ratio) is None


# ─── Deterministic split ─────────────────────────────────────────────────────

def test_split_is_deterministic_and_process_stable():
    ids = [f"89000000{i:03d}ffff" for i in range(200)]
    first = {z: deterministic_split(z, seed=1337) for z in ids}
    second = {z: deterministic_split(z, seed=1337) for z in ids}
    assert first == second
    assert set(first.values()) <= {"train", "test"}
    # The split is roughly 70/30 (loose bounds; deterministic so this is stable).
    test_frac = sum(1 for v in first.values() if v == "test") / len(ids)
    assert 0.15 < test_frac < 0.45


def test_split_changes_with_seed():
    ids = [f"89000000{i:03d}ffff" for i in range(200)]
    a = {z: deterministic_split(z, seed=1) for z in ids}
    b = {z: deterministic_split(z, seed=2) for z in ids}
    assert a != b


# ─── Join + report ───────────────────────────────────────────────────────────

def test_join_only_keeps_zones_in_both_with_valid_values():
    cis = _cis_artifact({"a": 50.0, "b": 30.0, "c": 70.0})
    obs = _observations({"a": 1.5, "b": 1.2, "d": 2.0})  # d not in cis, c not in obs
    points = join_points(cis, obs)
    assert {p["h3_id"] for p in points} == {"a", "b"}
    for p in points:
        assert p["split"] in {"train", "test"}


def test_build_report_monotonic_all_and_subsets():
    n = 12
    scores = {f"z{i:02d}": float(10 + i * 5) for i in range(n)}
    ratios = {f"z{i:02d}": 1.0 + i * 0.1 for i in range(n)}  # monotone with score
    exploration = {f"z{i:02d}" for i in range(0, n, 3)}

    report = build_report(_cis_artifact(scores), _observations(ratios, exploration))
    assert report["n_measured"] == n
    assert report["spearman_all"] == 1.0
    assert report["pearson_all"] is not None
    # Subset metrics are present (may be null if a subset is too small/constant).
    assert "spearman_test" in report and "spearman_exploration" in report
    assert report["n_exploration"] == len(exploration)
    assert len(report["points"]) == n


def test_report_nulls_and_warns_below_min_points(caplog):
    scores = {"a": 10.0, "b": 20.0, "c": 30.0}  # 3 zones
    ratios = {"a": 1.1, "b": 1.2, "c": 1.3}
    with caplog.at_level(logging.WARNING):
        report = build_report(_cis_artifact(scores), _observations(ratios))
    assert report["n_measured"] == 3
    assert report["spearman_all"] is None
    assert report["pearson_all"] is None
    assert any("measured zones" in rec.message for rec in caplog.records)


def test_run_writes_report_and_is_deterministic(tmp_path):
    n = 10
    scores = {f"z{i:02d}": float(10 + i * 5) for i in range(n)}
    ratios = {f"z{i:02d}": 1.0 + i * 0.1 for i in range(n)}

    cis_path = tmp_path / "cis.json"
    obs_path = tmp_path / "obs.json"
    cis_path.write_text(json.dumps(_cis_artifact(scores)), encoding="utf-8")
    obs_path.write_text(json.dumps(_observations(ratios)), encoding="utf-8")

    out1 = tmp_path / "report1.json"
    out2 = tmp_path / "report2.json"
    fixed_ts = "2024-03-15T09:30:00+00:00"
    r1 = run(cis_path, obs_path, out1, generated_at=fixed_ts, verbose=False)
    r2 = run(cis_path, obs_path, out2, generated_at=fixed_ts, verbose=False)

    assert out1.exists()
    assert out1.read_bytes() == out2.read_bytes()  # byte-identical
    assert r1 == r2
    assert r1["spearman_all"] == 1.0


def test_run_with_missing_observations_yields_zero(tmp_path, caplog):
    cis_path = tmp_path / "cis.json"
    cis_path.write_text(json.dumps(_cis_artifact({"a": 50.0})), encoding="utf-8")
    out = tmp_path / "report.json"
    with caplog.at_level(logging.WARNING):
        report = run(cis_path, tmp_path / "missing.json", out, verbose=False)
    assert report["n_measured"] == 0
    assert report["spearman_all"] is None
    assert out.exists()


# ─── Task 10: density≠impact proof + non-circular honest trust ───────────────

import numpy as np  # noqa: E402  (test-local import for the proof fixtures)


def test_honest_weights_exclude_traffic_degradation():
    hw = honest_weights()  # expert weights, no calibration
    assert tuple(hw.keys()) == NON_TRAFFIC_COMPONENTS
    assert TRAFFIC_COMPONENT not in hw
    assert abs(sum(hw.values()) - 1.0) < 1e-9


def test_honest_weights_from_calibration_renormalized_and_drops_td():
    calib = {"new_weights": {
        "lane_blockage": 0.45, "intersection_impact": 0.10,
        "access_blockage": 0.15, "vehicle_size": 0.05,
        "traffic_degradation": 0.25,  # MUST be dropped
    }}
    hw = honest_weights(calib)
    assert TRAFFIC_COMPONENT not in hw
    assert abs(sum(hw.values()) - 1.0) < 1e-9
    # The 4 non-td weights (0.45/0.10/0.15/0.05, sum 0.75) renormalize to /0.75.
    assert hw["lane_blockage"] == pytest.approx(0.45 / 0.75)
    assert hw["vehicle_size"] == pytest.approx(0.05 / 0.75)


def _proof_fixture(n=60, seed=0):
    """Artifact+obs where the measured ratio depends ONLY on a component
    (lane_blockage), NOT on raw count. count is an independent permutation, so
    the honest CIS should beat the count baseline. cis_full embeds the ratio."""
    rng = np.random.default_rng(seed)
    counts = rng.permutation(np.arange(10, 10 + n))  # independent of lane
    artifact, obs = {}, {}
    for i in range(n):
        h3 = f"89proof{i:04d}f"
        lane = i / (n - 1)                      # the driver, spans [0,1]
        c1, c2, c3 = (rng.random(3) * 0.05).tolist()  # tiny noise on others
        ratio = round(1.0 + 1.5 * lane, 4)      # depends ONLY on lane (not count)
        td = max(0.0, min(1.0, (ratio - 1.0) / 2.0))
        cis_full = round(100.0 * (0.75 * lane + 0.25 * td), 4)  # embeds the ratio
        artifact[h3] = {"all_day": {
            "congestion_impact": cis_full,
            "total_records": int(counts[i]),
            "components": {
                "lane_blockage": lane, "intersection_impact": c1,
                "access_blockage": c2, "vehicle_size": c3,
                "traffic_degradation": td, "severity": 0.4,
            },
            "lat": 12.97, "lon": 77.59,
        }}
        obs[h3] = {"zone_id": h3, "congestion_ratio": ratio,
                   "is_exploration": False, "source": "synthetic_test"}
    return artifact, obs


def test_density_neq_impact_honest_beats_count():
    artifact, obs = _proof_fixture(n=60, seed=0)
    report = build_report(artifact, obs)
    assert report["n_proof"] >= MIN_POINTS_FOR_CORR
    assert report["spearman_cis_honest_test"] is not None
    assert report["spearman_count_test"] is not None
    # Honest (component-driven) CIS beats raw count when the truth is components.
    assert report["spearman_cis_honest_test"] > report["spearman_count_test"]
    assert report["baseline_beaten"] is True


def test_circular_full_cis_geq_honest_sanity():
    artifact, obs = _proof_fixture(n=60, seed=0)
    report = build_report(artifact, obs)
    # The circular full CIS (which contains the measured ratio) is an upper bound.
    assert report["spearman_cis_full_test"] >= report["spearman_cis_honest_test"] - 1e-9
    assert "circular" in report["cis_full_note"].lower()


def test_honest_metric_excludes_traffic_degradation_airtight():
    """Changing ONLY traffic_degradation (and cis_full) must not move the honest
    metric — proving it uses exactly the four non-traffic components."""
    artifact, obs = _proof_fixture(n=60, seed=0)
    # Build a perturbed artifact where td and congestion_impact are altered but the
    # four non-traffic components are byte-identical.
    perturbed = json.loads(json.dumps(artifact))
    for h3, buckets in perturbed.items():
        bd = buckets["all_day"]
        bd["components"]["traffic_degradation"] = 0.123456  # arbitrary, different
        bd["congestion_impact"] = 1.0                        # wreck the full CIS

    base = build_report(artifact, obs)
    pert = build_report(perturbed, obs)
    # honest metric and per-zone cis_honest are identical; full CIS changes.
    assert base["spearman_cis_honest_test"] == pert["spearman_cis_honest_test"]
    assert base["honest_weights"] == pert["honest_weights"]
    honest_base = {p["h3_id"]: p["cis_honest"] for p in base["points"]}
    honest_pert = {p["h3_id"]: p["cis_honest"] for p in pert["points"]}
    assert honest_base == honest_pert
    # The full (circular) metric DID move (sanity that we actually perturbed it).
    assert base["spearman_cis_full_test"] != pert["spearman_cis_full_test"]


def test_proof_metrics_carry_bootstrap_cis_and_are_deterministic():
    artifact, obs = _proof_fixture(n=60, seed=0)
    r1 = build_report(artifact, obs, generated_at="x")
    r2 = build_report(artifact, obs, generated_at="x")
    assert r1 == r2  # deterministic (fixed bootstrap seed, no live clock)
    for key in ("spearman_count_test_ci", "spearman_cis_honest_test_ci", "spearman_cis_full_test_ci"):
        ci = r1[key]
        assert isinstance(ci, dict) and "lo" in ci and "hi" in ci


def test_honest_trust_line_format():
    artifact, obs = _proof_fixture(n=60, seed=0)
    report = build_report(artifact, obs)
    line = vc._honest_trust_line(report)
    assert "Honest trust: CIS(non-traffic) ρ=" in line
    assert "vs raw-count ρ=" in line
    assert ("PROVEN" in line) or ("NOT" in line)
    assert "density!=impact" in line
