"""
Integration test for the self-validating agent over the REAL CIS artifact shape.
================================================================================

Task 9.2 equivalent — drives the production calibration path
(``ml.agent.validation_agent``) end to end over a small **fixture** CIS artifact
(a tiny in-test ``{h3_id: {time_bucket: breakdown}}`` dict — acceptable here
because it is test *input*, not the production run) and pins the contract the
backend wiring depends on:

  (a) every calibrated zone's ``calibrated_score`` (and the ``calibrated_impact``
      surfaced through the backend) is within [0, 100];
  (b) GUARD — only zones with ``is_traffic_degradation_defaulted == False`` AND a
      valid, strictly-positive ``mappls_travel_time_ratio`` are calibrated; every
      other ("no_data") zone produces NO entry in ``calibrated_scores`` and yields
      ``calibrated_impact = None`` when served by the backend;
  (c) determinism — running the agent twice over the same artifact yields
      byte-identical output (no randomness, no clock-dependence).

It also pins the canonical calibration formula exactly and checks that the served
breakdown validates against the typed ``backend.app.models.CongestionBreakdown``
contract.

Framework: pytest (example-based integration test).
"""

from __future__ import annotations

import json

import pytest

from backend.app.data_loader import DataStore
from backend.app.models import CongestionBreakdown
from ml.agent.validation_agent import (
    ALPHA,
    SCORE_TO_RATIO_GAIN,
    calibrate_artifact_zones,
    run_from_artifact,
)

# ─── Fixture artifact (tiny, valid CongestionBreakdown shape per zone) ───────

_CANONICAL_WEIGHTS = {
    "lane_blockage": 0.30,
    "intersection_impact": 0.25,
    "traffic_degradation": 0.25,
    "access_blockage": 0.10,
    "vehicle_size": 0.10,
}


def _breakdown(
    h3_id: str,
    congestion_impact: float,
    *,
    ratio,
    defaulted: bool,
    station: str = "Test PS",
    time_bucket: str = "all_day",
) -> dict:
    """Return one valid ``CongestionBreakdown``-shaped dict for the fixture artifact."""
    return {
        "zone_id": h3_id,
        "h3_id": h3_id,
        "time_bucket": time_bucket,
        "lat": 12.97,
        "lon": 77.59,
        "congestion_impact": congestion_impact,
        "impact_band": "MODERATE" if congestion_impact > 25 else "MINIMAL",
        "components": {
            "lane_blockage": 0.4,
            "intersection_impact": 0.3,
            "traffic_degradation": 0.5,
            "access_blockage": 0.2,
            "vehicle_size": 0.35,
            "severity": 0.45,
        },
        "weights": dict(_CANONICAL_WEIGHTS),
        "estimated_lane_hours_blocked": 12.5,
        "total_records": 42,
        "top_violations": ["WRONG PARKING"],
        "station": station,
        "junction": None,
        "mappls_travel_time_ratio": ratio,
        "is_traffic_degradation_defaulted": defaulted,
        "calibrated_impact": None,
    }


# Two measured zones (calibratable) + four no_data zones spanning every reason a
# zone is excluded by the GUARD.
MEASURED_HIGH = "89aaaaaaaa1ffff"   # high CIS, ratio below implied -> adjusted_down
MEASURED_LOW = "89aaaaaaaa2ffff"    # low CIS, ratio above implied  -> adjusted_up
NO_DATA_DEFAULTED = "89bbbbbbbb1ffff"  # flag True (used the 0.5 fallback)
NO_DATA_RATIO_NONE = "89bbbbbbbb2ffff"  # flag False but ratio missing
NO_DATA_RATIO_ZERO = "89bbbbbbbb3ffff"  # flag False but ratio not positive
NO_DATA_RATIO_NAN = "89bbbbbbbb4ffff"   # flag False but ratio NaN


def _fixture_artifact() -> dict:
    return {
        MEASURED_HIGH: {"all_day": _breakdown(MEASURED_HIGH, 80.0, ratio=1.10, defaulted=False)},
        MEASURED_LOW: {"all_day": _breakdown(MEASURED_LOW, 10.0, ratio=1.90, defaulted=False)},
        NO_DATA_DEFAULTED: {"all_day": _breakdown(NO_DATA_DEFAULTED, 30.0, ratio=None, defaulted=True)},
        NO_DATA_RATIO_NONE: {"all_day": _breakdown(NO_DATA_RATIO_NONE, 30.0, ratio=None, defaulted=False)},
        NO_DATA_RATIO_ZERO: {"all_day": _breakdown(NO_DATA_RATIO_ZERO, 30.0, ratio=0.0, defaulted=False)},
        NO_DATA_RATIO_NAN: {"all_day": _breakdown(NO_DATA_RATIO_NAN, 30.0, ratio=float("nan"), defaulted=False)},
    }


MEASURED_ZONES = {MEASURED_HIGH, MEASURED_LOW}
NO_DATA_ZONES = {
    NO_DATA_DEFAULTED,
    NO_DATA_RATIO_NONE,
    NO_DATA_RATIO_ZERO,
    NO_DATA_RATIO_NAN,
}


# ─── (b) GUARD: only measured zones calibrated; no_data omitted ──────────────

def test_guard_calibrates_only_measured_zones():
    """Only the two measured zones are calibrated; all four no_data zones are omitted."""
    calibrated, summary = calibrate_artifact_zones(_fixture_artifact())

    assert set(calibrated) == MEASURED_ZONES
    for zone_id in NO_DATA_ZONES:
        assert zone_id not in calibrated, f"{zone_id} should have NO calibrated entry"

    assert summary["total_zones"] == 6
    assert summary["calibrated"] == 2
    assert summary["no_data"] == 4
    # The counts partition every input zone.
    assert summary["calibrated"] + summary["no_data"] == summary["total_zones"]


# ─── (a) calibrated_score within [0, 100] ────────────────────────────────────

def test_calibrated_scores_within_bounds():
    """Every calibrated zone's calibrated_score stays within [0, 100]."""
    calibrated, _ = calibrate_artifact_zones(_fixture_artifact())
    assert calibrated, "expected at least one calibrated zone"
    for zone_id, record in calibrated.items():
        assert 0.0 <= record["calibrated_score"] <= 100.0, zone_id
        assert 0.0 <= record["raw_score"] <= 100.0, zone_id


# ─── Canonical formula is implemented exactly ────────────────────────────────

def test_calibration_matches_canonical_formula():
    """The agent's per-zone maths equals the canonical formula bit-for-bit.

    expected_ratio = 1 + (CIS/100)*2.0 ; discrepancy = actual - expected ;
    adjustment = 0.3*(discrepancy/max(expected,1)) ; calibrated = clamp(CIS*(1+adj),0,100).
    """
    assert ALPHA == 0.3
    assert SCORE_TO_RATIO_GAIN == 2.0

    raw, ratio = 80.0, 1.10  # MEASURED_HIGH
    expected_ratio = 1.0 + (raw / 100.0) * 2.0
    discrepancy = ratio - expected_ratio
    adjustment = 0.3 * (discrepancy / max(expected_ratio, 1.0))
    calibrated_score = max(0.0, min(100.0, raw * (1.0 + adjustment)))

    calibrated, _ = calibrate_artifact_zones(_fixture_artifact())
    rec = calibrated[MEASURED_HIGH]
    assert rec["expected_ratio"] == pytest.approx(round(expected_ratio, 3))
    assert rec["discrepancy"] == pytest.approx(round(discrepancy, 3))
    assert rec["adjustment"] == pytest.approx(round(adjustment, 4))
    assert rec["calibrated_score"] == pytest.approx(round(calibrated_score, 1))


# ─── (c) determinism: run twice -> identical output ──────────────────────────

def test_determinism_in_memory():
    """Calibrating the same artifact twice yields equal, equally-ordered output."""
    artifact = _fixture_artifact()
    cal1, sum1 = calibrate_artifact_zones(artifact)
    cal2, sum2 = calibrate_artifact_zones(artifact)

    assert cal1 == cal2
    assert sum1 == sum2
    # Insertion order (worst CIS first) and serialization are identical too.
    assert list(cal1) == list(cal2)
    assert json.dumps(cal1) == json.dumps(cal2)
    assert json.dumps(sum1) == json.dumps(sum2)


def test_determinism_written_files(tmp_path):
    """run_from_artifact writes byte-identical files across runs (no committed I/O)."""
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(_fixture_artifact()), encoding="utf-8")
    out1 = tmp_path / "calibrated_1.json"
    out2 = tmp_path / "calibrated_2.json"
    log1 = tmp_path / "log_1.json"
    log2 = tmp_path / "log_2.json"

    run_from_artifact(artifact_path, out1, log1, verbose=False)
    run_from_artifact(artifact_path, out2, log2, verbose=False)

    assert out1.read_bytes() == out2.read_bytes()
    assert log1.read_bytes() == log2.read_bytes()

    written = json.loads(out1.read_text(encoding="utf-8"))
    assert set(written) == MEASURED_ZONES


# ─── Backend wiring: breakdown conforms + calibrated_impact number vs None ───

def test_backend_breakdown_conforms_and_calibrated_impact_number_vs_none():
    """DataStore.congestion_breakdown returns a valid CongestionBreakdown with
    ``calibrated_impact`` a number for a calibrated zone and ``None`` for a
    no_data zone."""
    artifact = _fixture_artifact()
    calibrated, _ = calibrate_artifact_zones(artifact)

    # Wire a DataStore directly to the fixture artifact + agent output (no disk).
    store = DataStore()
    store.loaded = True
    store.congestion = artifact
    store.calibrated = calibrated

    # Calibrated zone -> calibrated_impact is a number, and the dict validates.
    measured = store.congestion_breakdown(MEASURED_HIGH)
    assert measured is not None
    assert isinstance(measured["calibrated_impact"], (int, float))
    assert 0.0 <= measured["calibrated_impact"] <= 100.0
    model = CongestionBreakdown.model_validate(measured)
    assert model.calibrated_impact == pytest.approx(calibrated[MEASURED_HIGH]["calibrated_score"])

    # no_data zone -> present in the CIS artifact but calibrated_impact is None.
    no_data = store.congestion_breakdown(NO_DATA_DEFAULTED)
    assert no_data is not None
    assert no_data["calibrated_impact"] is None
    model_nd = CongestionBreakdown.model_validate(no_data)
    assert model_nd.calibrated_impact is None

    # A zone absent from the artifact resolves to None (caller falls back).
    assert store.congestion_breakdown("89zzzzzzzzz0ffff") is None
