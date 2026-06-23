"""
Tests for the agent's offline calibration-loop block (Task 6).
==============================================================================

The agent evolves from "nudge N zones" to "refit weights + report its own
trustworthiness". The ``calibration_run`` block is assembled ENTIRELY from the
cached Task 2-4 sidecar reports — no network, deterministic, no timestamp.

Covers:
* ``build_calibration_run`` maps the three reports correctly;
* absent sidecars -> ``available: False`` with null fields (no fabricated numbers);
* ``run_from_artifact`` bakes the block into ``agent_log.json`` deterministically;
* ``DataStore.agent_report`` surfaces it additively (and degrades gracefully).

Fixtures are CIS-independent (the reports are plain dicts; the measured ratio in
the artifact zone is a raw value, not derived from the CIS score).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.data_loader import DataStore
from ml.agent.validation_agent import (
    build_calibration_run,
    load_calibration_run,
    run_from_artifact,
)
from ml.congestion.impact_score import WEIGHTS


# ─── build_calibration_run ───────────────────────────────────────────────────

def test_calibration_run_empty_reports_is_unavailable():
    block = build_calibration_run({}, {}, {})
    assert block["available"] is False
    assert block["weights_old"] is None
    assert block["weights_new"] is None
    assert block["spearman_old"] is None
    assert block["spearman_new"] is None
    assert block["n_zones_measured"] is None
    assert block["lozo_metrics"] == {"model": None, "lozo_r2": None, "lozo_spearman": None}


def test_calibration_run_maps_reports():
    validation = {"n_measured": 140, "n_exploration": 40}
    calibration = {
        "old_weights": dict(WEIGHTS),
        "new_weights": {**WEIGHTS, "lane_blockage": 0.45, "intersection_impact": 0.10},
        "spearman_old_test": 0.42,
        "spearman_new_test": 0.61,
        "method": "dirichlet_random_search+nelder_mead",
        "n_train": 100, "n_test": 40,
    }
    degradation = {"model": "ridge", "lozo_r2": 0.33, "lozo_spearman": 0.55, "n": 140}

    block = build_calibration_run(validation, calibration, degradation)
    assert block["available"] is True
    assert block["weights_old"] == dict(WEIGHTS)
    assert block["weights_new"]["lane_blockage"] == 0.45
    assert block["spearman_old"] == 0.42
    assert block["spearman_new"] == 0.61
    assert block["weights_method"] == "dirichlet_random_search+nelder_mead"
    assert block["n_zones_measured"] == 140
    assert block["n_exploration"] == 40
    assert block["lozo_metrics"] == {"model": "ridge", "lozo_r2": 0.33, "lozo_spearman": 0.55}


def test_calibration_run_n_falls_back_to_train_plus_test():
    block = build_calibration_run({}, {"n_train": 90, "n_test": 30}, {})
    assert block["available"] is True
    assert block["n_zones_measured"] == 120


def test_load_calibration_run_absent_files_unavailable(tmp_path):
    block = load_calibration_run(
        validation_path=tmp_path / "v.json",
        calibration_path=tmp_path / "c.json",
        degradation_path=tmp_path / "d.json",
    )
    assert block["available"] is False  # offline-safe, no crash, no numbers


# ─── run_from_artifact integration ───────────────────────────────────────────

def _artifact_with_measured_zone() -> dict:
    """One measured zone (calibratable) so the per-zone agent path runs too."""
    h3 = "8960145b483ffff"
    return {
        h3: {
            "all_day": {
                "zone_id": h3, "h3_id": h3, "time_bucket": "all_day",
                "lat": 12.97, "lon": 77.59,
                "congestion_impact": 60.0, "impact_band": "SEVERE",
                "components": {
                    "lane_blockage": 0.4, "intersection_impact": 0.3,
                    "traffic_degradation": 0.45, "access_blockage": 0.2,
                    "vehicle_size": 0.3, "severity": 0.4,
                },
                "weights": dict(WEIGHTS), "estimated_lane_hours_blocked": 10.0,
                "total_records": 200, "top_violations": ["WRONG PARKING"],
                "station": "Upparpet", "junction": None,
                "mappls_travel_time_ratio": 1.9,  # raw measured signal (CIS-independent)
                "is_traffic_degradation_defaulted": False, "calibrated_impact": None,
            }
        }
    }


def _write_artifact(tmp_path: Path) -> Path:
    p = tmp_path / "zone_congestion_impact.json"
    p.write_text(json.dumps(_artifact_with_measured_zone()), encoding="utf-8")
    return p


def test_run_from_artifact_injects_unavailable_block_when_sidecars_absent(tmp_path):
    artifact_path = _write_artifact(tmp_path)
    log_out = tmp_path / "agent_log.json"
    _, summary = run_from_artifact(
        artifact_path,
        calibrated_out=tmp_path / "calibrated.json",
        log_out=log_out,
        verbose=False,
        validation_path=tmp_path / "absent_v.json",
        calibration_path=tmp_path / "absent_c.json",
        degradation_path=tmp_path / "absent_d.json",
    )
    assert summary["calibration_run"]["available"] is False
    on_disk = json.loads(log_out.read_text(encoding="utf-8"))
    assert on_disk["calibration_run"]["available"] is False


def test_run_from_artifact_bakes_calibration_run_when_sidecars_present(tmp_path):
    artifact_path = _write_artifact(tmp_path)
    val = tmp_path / "v.json"
    cal = tmp_path / "c.json"
    deg = tmp_path / "d.json"
    val.write_text(json.dumps({"n_measured": 140, "n_exploration": 40}), encoding="utf-8")
    cal.write_text(json.dumps({
        "old_weights": dict(WEIGHTS),
        "new_weights": {**WEIGHTS, "lane_blockage": 0.45, "intersection_impact": 0.10},
        "spearman_old_test": 0.42, "spearman_new_test": 0.61,
        "method": "dirichlet_random_search+nelder_mead",
    }), encoding="utf-8")
    deg.write_text(json.dumps({"model": "ridge", "lozo_r2": 0.33, "lozo_spearman": 0.55}), encoding="utf-8")

    log_out = tmp_path / "agent_log.json"
    _, summary = run_from_artifact(
        artifact_path,
        calibrated_out=tmp_path / "calibrated.json",
        log_out=log_out, verbose=False,
        validation_path=val, calibration_path=cal, degradation_path=deg,
    )
    block = summary["calibration_run"]
    assert block["available"] is True
    assert block["spearman_old"] == 0.42 and block["spearman_new"] == 0.61
    assert block["weights_new"]["lane_blockage"] == 0.45
    assert block["n_zones_measured"] == 140


def test_run_from_artifact_calibration_run_is_deterministic(tmp_path):
    artifact_path = _write_artifact(tmp_path)
    kwargs = dict(
        validation_path=tmp_path / "absent_v.json",
        calibration_path=tmp_path / "absent_c.json",
        degradation_path=tmp_path / "absent_d.json",
        verbose=False,
    )
    log1 = tmp_path / "log1.json"
    log2 = tmp_path / "log2.json"
    run_from_artifact(artifact_path, calibrated_out=tmp_path / "c1.json", log_out=log1, **kwargs)
    run_from_artifact(artifact_path, calibrated_out=tmp_path / "c2.json", log_out=log2, **kwargs)
    assert log1.read_bytes() == log2.read_bytes()  # no timestamp in the block


# ─── DataStore.agent_report surfacing ────────────────────────────────────────

def test_agent_report_surfaces_calibration_run():
    store = DataStore()
    store.loaded = True
    store.calibrated = {}
    store.agent_summary = {
        "total_zones": 1, "calibrated": 1, "validated": 1, "accurate": 1,
        "adjusted_up": 0, "adjusted_down": 0,
        "calibration_run": {"available": True, "spearman_old": 0.4, "spearman_new": 0.6},
    }
    report = store.agent_report()
    assert report["calibration_run"]["available"] is True
    assert report["calibration_run"]["spearman_new"] == 0.6


def test_agent_report_degrades_when_no_calibration_run():
    store = DataStore()
    store.loaded = True
    store.calibrated = {}
    store.agent_summary = {"total_zones": 0}
    report = store.agent_report()
    assert report["calibration_run"] == {"available": False}
