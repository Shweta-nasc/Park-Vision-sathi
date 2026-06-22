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
    build_report,
    deterministic_split,
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
