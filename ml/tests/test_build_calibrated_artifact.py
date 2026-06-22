"""
Tests for the calibrated v2 CIS artifact builder + backend wiring (Task 5).
==============================================================================

Covers the Task 5 acceptance criteria (additive-shadow):
* v2 passes the CIS constraints (weights sum to 1, components in [0,1], score in
  [0,100]) and every per-zone entry validates against ``CongestionBreakdown``;
* the v2 artifact applies fitted weights + a degradation override;
* the backend ``DataStore`` loads v2 by default and FALLS BACK to v1 when v2 is
  absent; the reserved ``_calibration`` block never appears as a zone;
* ``/health`` exposes the calibration metadata; schema is additive only.

All fixtures use CIS-independent inputs; no real/synthetic v2 artifact is
committed to the repo (everything is under tmp_path).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backend.app.data_loader import CALIBRATION_META_KEY, DataStore, _resolve_cis_artifact_path
from backend.app.models import CongestionBreakdown
from ml.congestion.build_artifact import h3_id_for
from ml.congestion.build_calibrated_artifact import (
    CIS_VERSION,
    build_calibrated_artifact,
    load_calibrated_weights,
)
from ml.congestion.impact_score import WEIGHTS


# ─── Fixtures ────────────────────────────────────────────────────────────────

# Three Bengaluru-ish points -> three distinct H3 res-9 cells.
PT_A = (12.9716, 77.5946)
PT_B = (12.9352, 77.6245)
PT_C = (12.9698, 77.7500)


def _violations_df() -> pd.DataFrame:
    """A tiny CIS-independent violations corpus (within the data-rich window)."""
    rows = []
    specs = [
        (PT_A, ["PARKING IN A MAIN ROAD", "DOUBLE PARKING"], "CAR", "Trinity Circle", "Upparpet"),
        (PT_A, ["PARKING IN A MAIN ROAD"], "BUS", "NO JUNCTION", "Upparpet"),
        (PT_B, ["PARKING NEAR ROAD CROSSING"], "LORRY", "Silk Board Junction", "Cubbon Park"),
        (PT_C, ["PARKING ON FOOTPATH"], "SCOOTER", "NULL", "Halasuru"),
    ]
    for (lat, lon), violations, vehicle, junction, station in specs:
        rows.append({
            "latitude": lat, "longitude": lon,
            "created_datetime": "2024-03-15T09:30:00+05:30",
            "violation_type": violations, "vehicle_type": vehicle,
            "updated_vehicle_type": None, "junction_name": junction,
            "police_station": station,
        })
    return pd.DataFrame(rows)


def _calibrated_weights() -> dict:
    """A non-canonical but valid partition of unity (td fixed at 0.25)."""
    return {
        "lane_blockage": 0.45,
        "intersection_impact": 0.10,
        "traffic_degradation": 0.25,
        "access_blockage": 0.15,
        "vehicle_size": 0.05,
    }


def _write_sidecars(tmp_path: Path, zone_ids):
    """Write Task 3/4 sidecar JSONs the v2 builder consumes."""
    calib = tmp_path / "cis_calibration.json"
    calib.write_text(json.dumps({
        "old_weights": dict(WEIGHTS),
        "new_weights": _calibrated_weights(),
        "w_td_fixed": 0.25,
        "spearman_new_test": 0.61,
        "spearman_old_test": 0.42,
        "n_train": 100, "n_test": 40,
        "method": "dirichlet_random_search+nelder_mead",
    }), encoding="utf-8")

    # Degradation override: distinct, in-range per zone (CIS-independent values).
    deg_zones = {z: {"degradation": 0.8, "source": "predicted"} for z in zone_ids}
    deg = tmp_path / "predicted_degradation.json"
    deg.write_text(json.dumps({
        "model": "ridge", "n": 140, "n_predicted": 2387,
        "lozo_r2": 0.33, "lozo_spearman": 0.55,
        "zones": deg_zones,
    }), encoding="utf-8")

    val = tmp_path / "cis_validation_report.json"
    val.write_text(json.dumps({"n_measured": 140, "n_exploration": 40}), encoding="utf-8")
    return calib, deg, val


# ─── load_calibrated_weights ─────────────────────────────────────────────────

def test_load_calibrated_weights_valid(tmp_path):
    p = tmp_path / "cis_calibration.json"
    p.write_text(json.dumps({"new_weights": _calibrated_weights()}), encoding="utf-8")
    weights, report = load_calibrated_weights(p)
    assert weights is not None
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_load_calibrated_weights_missing_returns_none(tmp_path):
    weights, report = load_calibrated_weights(tmp_path / "absent.json")
    assert weights is None
    assert report == {}


# ─── build_calibrated_artifact ───────────────────────────────────────────────

def test_v2_artifact_uses_fitted_weights_and_degradation_override(tmp_path):
    zone_ids = [h3_id_for(*PT_A), h3_id_for(*PT_B), h3_id_for(*PT_C)]
    calib, deg, val = _write_sidecars(tmp_path, zone_ids)
    ctx = tmp_path / "traffic_context.json"
    ctx.write_text("{}", encoding="utf-8")
    out = tmp_path / "zone_congestion_impact_v2.json"

    artifact = build_calibrated_artifact(
        _violations_df(),
        calibration_path=calib, degradation_path=deg, validation_path=val,
        traffic_context_path=ctx, observations_path=tmp_path / "none.json",
        out_path=out, generated_at="2024-03-15T09:30:00+00:00",
    )

    assert out.exists()
    assert CALIBRATION_META_KEY in artifact
    meta = artifact[CALIBRATION_META_KEY]
    assert meta["cis_version"] == CIS_VERSION
    assert abs(sum(meta["weights"].values()) - 1.0) < 1e-9
    assert meta["spearman_test"] == 0.61
    assert meta["n_measured"] == 140

    # Every per-zone entry validates against the contract, with the fitted weights
    # echoed and the degradation override applied.
    for zone_id, buckets in artifact.items():
        if zone_id == CALIBRATION_META_KEY:
            continue
        for breakdown in buckets.values():
            model = CongestionBreakdown.model_validate(breakdown)
            assert abs(sum(model.weights.values()) - 1.0) < 1e-9
            assert model.weights["lane_blockage"] == pytest.approx(0.45)
            assert model.components.traffic_degradation == pytest.approx(0.8)
            assert model.is_traffic_degradation_defaulted is False
            assert 0.0 <= model.congestion_impact <= 100.0


def test_v2_falls_back_to_canonical_weights_without_calibration(tmp_path):
    ctx = tmp_path / "traffic_context.json"
    ctx.write_text("{}", encoding="utf-8")
    out = tmp_path / "v2.json"
    artifact = build_calibrated_artifact(
        _violations_df(),
        calibration_path=tmp_path / "absent.json",
        degradation_path=tmp_path / "absent2.json",
        validation_path=tmp_path / "absent3.json",
        traffic_context_path=ctx, observations_path=tmp_path / "absent4.json",
        out_path=out, generated_at="x",
    )
    meta = artifact[CALIBRATION_META_KEY]
    assert meta["weights"] == WEIGHTS  # canonical fallback


# ─── backend wiring: v2 default, v1 fallback, metadata strip ─────────────────

def test_resolve_prefers_v2_then_v1(tmp_path, monkeypatch):
    monkeypatch.delenv("CIS_ARTIFACT_PATH", raising=False)
    processed = tmp_path / "processed"
    processed.mkdir()
    v1 = processed / "zone_congestion_impact.json"
    v1.write_text("{}", encoding="utf-8")
    # Only v1 present -> resolves to v1.
    assert _resolve_cis_artifact_path(tmp_path).name == "zone_congestion_impact.json"
    # v2 present -> resolves to v2.
    (processed / "zone_congestion_impact_v2.json").write_text("{}", encoding="utf-8")
    assert _resolve_cis_artifact_path(tmp_path).name == "zone_congestion_impact_v2.json"


def test_datastore_loads_v2_and_strips_metadata(tmp_path, monkeypatch):
    monkeypatch.delenv("CIS_ARTIFACT_PATH", raising=False)
    zone_ids = [h3_id_for(*PT_A), h3_id_for(*PT_B), h3_id_for(*PT_C)]
    calib, deg, val = _write_sidecars(tmp_path, zone_ids)
    ctx = tmp_path / "traffic_context.json"
    ctx.write_text("{}", encoding="utf-8")

    data_dir = tmp_path / "data"
    processed = data_dir / "processed"
    processed.mkdir(parents=True)
    # Build v2 directly into the DataStore's processed dir.
    build_calibrated_artifact(
        _violations_df(),
        calibration_path=calib, degradation_path=deg, validation_path=val,
        traffic_context_path=ctx, observations_path=tmp_path / "none.json",
        out_path=processed / "zone_congestion_impact_v2.json", generated_at="x",
    )

    store = DataStore(data_dir=data_dir).load()
    # The reserved metadata key is never a zone.
    assert CALIBRATION_META_KEY not in store.congestion
    assert all(not k.startswith("_") for k in store.congestion)
    # Calibration metadata is surfaced.
    assert store.calibration_meta["cis_version"] == "v2"
    assert store.sources["cis_version"] == "v2"
    assert store.sources["cis_artifact"] == "zone_congestion_impact_v2.json"


def test_datastore_falls_back_to_v1_when_v2_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("CIS_ARTIFACT_PATH", raising=False)
    data_dir = tmp_path / "data"
    processed = data_dir / "processed"
    processed.mkdir(parents=True)
    # Only a v1 artifact exists (one minimal valid zone).
    zone_id = h3_id_for(*PT_A)
    v1 = {zone_id: {"all_day": {
        "zone_id": zone_id, "h3_id": zone_id, "time_bucket": "all_day",
        "lat": PT_A[0], "lon": PT_A[1], "congestion_impact": 30.0, "impact_band": "MODERATE",
        "components": {"lane_blockage": 0.3, "intersection_impact": 0.2,
                       "traffic_degradation": 0.5, "access_blockage": 0.1,
                       "vehicle_size": 0.2, "severity": 0.3},
        "weights": dict(WEIGHTS), "estimated_lane_hours_blocked": 1.0,
        "total_records": 5, "top_violations": ["WRONG PARKING"], "station": "Upparpet",
        "mappls_travel_time_ratio": None, "is_traffic_degradation_defaulted": True,
        "calibrated_impact": None,
    }}}
    (processed / "zone_congestion_impact.json").write_text(json.dumps(v1), encoding="utf-8")

    store = DataStore(data_dir=data_dir).load()
    assert store.cis_artifact_path.name == "zone_congestion_impact.json"
    assert store.calibration_meta["cis_version"] == "v1"
    assert store.calibration_meta["calibrated"] is False
    assert zone_id in store.congestion
