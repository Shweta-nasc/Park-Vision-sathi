"""
Tests for statistical-honesty helpers + immutable snapshot (Task 11).
==============================================================================

* bootstrap CI brackets the true ρ on synthetic monotone data;
* flat measured ratios trigger the abort (no fit);
* a frozen snapshot is not overwritten without --force; sha256 is stable;
* calibration aborts on flat data and carries a CI otherwise (CIS-independent).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from ml.congestion.stats_utils import (
    bootstrap_spearman_ci,
    content_sha256,
    flat_variance_abort,
)
from ml.enrichment import congestion_collector as cc
from ml.enrichment.congestion_collector import (
    SnapshotFrozenError,
    is_frozen,
    observations_content_sha256,
    read_snapshot_meta,
)


# ─── bootstrap_spearman_ci ───────────────────────────────────────────────────

def test_bootstrap_ci_brackets_strong_positive_rho():
    x = list(range(30))
    y = [v + (v % 3) * 0.1 for v in x]  # monotone increasing -> rho near 1
    out = bootstrap_spearman_ci(x, y, n_boot=500, seed=42)
    assert out["rho"] is not None and out["rho"] > 0.95
    assert out["lo"] is not None and out["hi"] is not None
    assert out["lo"] <= out["rho"] <= out["hi"] + 1e-9
    assert out["lo"] > 0          # CI excludes 0 for a strong signal
    assert out["p_approx"] is not None and out["p_approx"] < 0.05


def test_bootstrap_ci_none_below_min_or_constant():
    assert bootstrap_spearman_ci([1, 2], [1, 2])["rho"] is None  # n<5
    out = bootstrap_spearman_ci([1, 1, 1, 1, 1, 1], [1, 2, 3, 4, 5, 6])
    assert out["rho"] is None  # constant x


def test_bootstrap_ci_is_deterministic():
    rng = np.random.default_rng(0)
    x = list(rng.random(40))
    y = list(rng.random(40))
    a = bootstrap_spearman_ci(x, y, n_boot=300, seed=7)
    b = bootstrap_spearman_ci(x, y, n_boot=300, seed=7)
    assert a == b


def test_bootstrap_ci_brackets_zero_for_noise():
    rng = np.random.default_rng(1)
    x = list(rng.random(60))
    y = list(rng.random(60))  # independent -> rho near 0, CI straddles 0
    out = bootstrap_spearman_ci(x, y, n_boot=500, seed=42)
    assert out["lo"] < 0 < out["hi"]


# ─── flat_variance_abort ─────────────────────────────────────────────────────

def test_flat_variance_aborts_on_off_peak():
    y = [1.00, 1.01, 0.99, 1.00, 1.01, 0.99]  # all ~1.0 (off-peak)
    out = flat_variance_abort(y, std_min=0.02)
    assert out is not None
    assert out["status"] == "aborted_flat_variance"
    assert "off-peak" in out["reason"].lower()


def test_flat_variance_passes_on_real_spread():
    y = [1.1, 1.8, 2.4, 1.3, 2.0, 1.6]  # healthy spread
    assert flat_variance_abort(y, std_min=0.02) is None


def test_flat_variance_empty():
    out = flat_variance_abort([])
    assert out["status"] == "aborted_flat_variance"


# ─── content_sha256 ──────────────────────────────────────────────────────────

def test_content_sha256_stable_and_order_independent():
    a = {"z1": {"congestion_ratio": 1.5}, "z2": {"congestion_ratio": 1.2}}
    b = {"z2": {"congestion_ratio": 1.2}, "z1": {"congestion_ratio": 1.5}}  # different order
    assert content_sha256(a) == content_sha256(b)        # canonical (sorted keys)
    assert content_sha256(a) == content_sha256(a)        # stable across calls
    assert content_sha256(a) != content_sha256({"z1": {"congestion_ratio": 9.9}})


# ─── immutable snapshot (collector) ──────────────────────────────────────────

class _FakeApi:
    def __call__(self, url, params, label):
        if label == "distance_matrix":
            return {"results": {"code": "Ok", "durations": [[0.0, 100.0]], "distances": [[0.0, 400.0]]}}
        if label == "distance_matrix_eta":
            return {"results": {"code": "Ok", "durations": [[0.0, 200.0]]}}
        if label == "reverse_geocode":
            return {"results": [{"street": "S", "locality": "L"}]}
        return {"suggestedLocations": []}


def _artifact(n=3):
    art = {}
    for i in range(n):
        zid = f"89000000{i:03d}ffff"
        art[zid] = {"all_day": {"lat": 12.97 + i * 0.001, "lon": 77.59 + i * 0.001,
                                "total_records": (n - i) * 10, "station": f"PS{i}"}}
    return art


PEAK_NOW = __import__("datetime").datetime(2024, 3, 15, 9, 30, tzinfo=cc.IST)


def test_collection_freezes_snapshot_and_records_sha(tmp_path):
    art_path = tmp_path / "cis.json"
    art_path.write_text(json.dumps(_artifact(3)), encoding="utf-8")
    out = tmp_path / "obs.json"

    results = cc.collect(artifact_path=art_path, output_path=out, top_n=3, explore_n=0,
                         get_json=_FakeApi(), now_ist=PEAK_NOW, token="SECRET",
                         sleep_between_apis=0.0, sleep_between_zones=0.0, verbose=False)
    assert is_frozen(out)
    meta = read_snapshot_meta(out)
    assert meta["frozen"] is True
    assert meta["n_zones"] == 3
    # The recorded hash matches the written observations content.
    assert meta["content_sha256"] == observations_content_sha256(results)


def test_frozen_snapshot_not_overwritten_without_force(tmp_path):
    art_path = tmp_path / "cis.json"
    art_path.write_text(json.dumps(_artifact(3)), encoding="utf-8")
    out = tmp_path / "obs.json"
    common = dict(artifact_path=art_path, output_path=out, top_n=3, explore_n=0,
                  now_ist=PEAK_NOW, token="SECRET", sleep_between_apis=0.0,
                  sleep_between_zones=0.0, verbose=False)

    cc.collect(get_json=_FakeApi(), **common)
    assert is_frozen(out)

    # A second run (refresh -> would re-collect all 3) must refuse without --force.
    fake2 = _FakeApi()
    with pytest.raises(SnapshotFrozenError):
        cc.collect(get_json=fake2, refresh=True, **common)

    # With --force it proceeds and re-freezes.
    res = cc.collect(get_json=_FakeApi(), refresh=True, force=True, **common)
    assert len(res) == 3
    assert is_frozen(out)


def test_dry_run_does_not_freeze(tmp_path):
    art_path = tmp_path / "cis.json"
    art_path.write_text(json.dumps(_artifact(3)), encoding="utf-8")
    out = tmp_path / "obs.json"
    cc.collect(artifact_path=art_path, output_path=out, top_n=3, explore_n=0,
               dry_run=True, get_json=_FakeApi(), now_ist=PEAK_NOW, token="SECRET", verbose=False)
    assert not is_frozen(out)


# ─── build_calibration aborts on flat (off-peak) ratios ──────────────────────

def test_build_calibration_aborts_on_flat_ratios():
    from ml.congestion.calibrate_weights import build_calibration
    from ml.congestion.impact_score import WEIGHTS

    # CIS-independent fixture: components vary, but the measured ratio is ~flat
    # (off-peak), so calibration must abort rather than fit noise.
    rng = np.random.default_rng(0)
    artifact, obs = {}, {}
    for i in range(40):
        h3 = f"89flat{i:04d}fff"
        c = rng.random(4)
        artifact[h3] = {"all_day": {"components": {
            "lane_blockage": float(c[0]), "intersection_impact": float(c[1]),
            "access_blockage": float(c[2]), "vehicle_size": float(c[3]),
            "traffic_degradation": 0.5, "severity": 0.4}, "lat": 12.97, "lon": 77.59}}
        obs[h3] = {"zone_id": h3, "congestion_ratio": round(1.0 + rng.uniform(-0.01, 0.01), 4),
                   "is_exploration": False, "source": "synthetic_test"}
    report = build_calibration(artifact, obs, n_samples=500)
    assert report["method"] == "aborted_flat_variance"
    assert report["calibration_strength"] == "aborted"
    assert report["new_weights"] == WEIGHTS  # unchanged, no fit


def test_build_calibration_carries_ci_on_real_spread():
    from ml.congestion.calibrate_weights import build_calibration

    # Label increases with lane (CIS-independent), healthy spread -> CI present.
    rng = np.random.default_rng(1)
    artifact, obs = {}, {}
    n = 40
    for i in range(n):
        h3 = f"89spread{i:04d}f"
        c = rng.random(4)
        c[0] = i / (n - 1)
        artifact[h3] = {"all_day": {"components": {
            "lane_blockage": float(c[0]), "intersection_impact": float(c[1]),
            "access_blockage": float(c[2]), "vehicle_size": float(c[3]),
            "traffic_degradation": 0.5, "severity": 0.4}, "lat": 12.97, "lon": 77.59}}
        obs[h3] = {"zone_id": h3, "congestion_ratio": round(1.0 + 1.5 * (i / (n - 1)), 4),
                   "is_exploration": False, "source": "synthetic_test"}
    report = build_calibration(artifact, obs, n_samples=1000)
    assert report["method"] != "aborted_flat_variance"
    assert report["observations_sha256"] is not None
    ci = report.get("spearman_new_test_ci")
    assert isinstance(ci, dict) and "lo" in ci and "hi" in ci
