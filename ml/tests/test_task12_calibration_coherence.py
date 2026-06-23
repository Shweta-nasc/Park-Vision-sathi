"""
Task 12 — calibration coherence + serving the calibrated bucket.
==============================================================================

Two failures this task fixes, both verified here (additive-shadow, offline,
deterministic — no network, no committed real numbers):

1. **Double calibration.** Once Task 3 has fitted the CIS weights against the
   measured MapMyIndia ratio, the self-validating agent must NOT nudge the score
   a *second* time against the same ratio. So:
     * when a REAL weight calibration is present, the agent runs *report-only*
       (zero nudge, ``calibrated_score == raw_score``) and only reports how the
       CIS compares to reality;
     * when no calibration exists (or it flat-aborted), the legacy α=0.3 nudge
       survives as the fallback (existing behaviour preserved).

2. **Headline bucket.** A calibrated v2 artifact is served with the calibrated
   "peak window" (``calibrated_bucket``, default ``morning_peak``) as the
   ``headline_bucket``; the served breakdown carries ``time_regime`` —
   ``"calibrated"`` for the peak window, ``"uncalibrated"`` for ``all_day`` and
   everything else. ``/health`` and the additive ``/risk/calibration`` endpoint
   expose the bucket/regime info so the frontend can LABEL the peak.

All fixtures are CIS-INDEPENDENT: the measured ratio is a raw value, never
derived from the CIS score, and the served breakdowns are hand-built valid
contract shapes — so nothing here is circular.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.data_loader import CIS_CALIBRATION_META_FILENAME, DataStore, store
from backend.app.main import app
from backend.app.models import CongestionBreakdown
from ml.agent.validation_agent import calibrate_artifact_zones, run_from_artifact
from ml.congestion.impact_score import WEIGHTS

ZONE = "8960145b483ffff"


# ─── shared CIS-independent fixtures ─────────────────────────────────────────

def _valid_breakdown(h3: str, time_bucket: str, *, cis: float = 60.0,
                     count: int = 100) -> dict:
    """One valid ``CongestionBreakdown``-shaped dict (CIS-independent values).

    The measured ratio (1.9) is a raw signal, NOT derived from ``cis``.
    """
    return {
        "zone_id": h3, "h3_id": h3, "time_bucket": time_bucket,
        "lat": 12.97, "lon": 77.59,
        "congestion_impact": cis,
        "impact_band": "SEVERE" if 50 < cis <= 75 else ("CRITICAL" if cis > 75 else "MODERATE"),
        "components": {
            "lane_blockage": 0.4, "intersection_impact": 0.3,
            "traffic_degradation": 0.45, "access_blockage": 0.2,
            "vehicle_size": 0.3, "severity": 0.4,
        },
        "weights": dict(WEIGHTS), "estimated_lane_hours_blocked": 10.0,
        "total_records": count, "top_violations": ["WRONG PARKING"],
        "station": "Upparpet", "junction": None,
        "mappls_travel_time_ratio": 1.9, "is_traffic_degradation_defaulted": False,
        "calibrated_impact": None,
    }


def _measured_artifact(*, cis: float = 60.0, ratio: float = 1.9) -> dict:
    """A one-zone artifact whose single zone is genuinely measured (calibratable)."""
    bd = _valid_breakdown(ZONE, "all_day", cis=cis)
    bd["mappls_travel_time_ratio"] = ratio
    return {ZONE: {"all_day": bd}}


def _real_calibration_report() -> dict:
    """A Task-3 calibration report where the fit ACTUALLY changed the weights."""
    return {
        "old_weights": dict(WEIGHTS),
        "new_weights": {**WEIGHTS, "lane_blockage": 0.45, "intersection_impact": 0.10},
        "spearman_old_test": 0.42, "spearman_new_test": 0.61,
        "method": "dirichlet_random_search+nelder_mead",
    }


# ═════════════════════════════════════════════════════════════════════════════
# A. Agent coherence — report-only (zero nudge) vs legacy nudge
# ═════════════════════════════════════════════════════════════════════════════

def test_calibrate_artifact_zones_report_only_is_zero_nudge():
    """``apply_nudge=False`` leaves the score unchanged but still REPORTS the
    comparison (status / expected ratio), and tags the run ``report_only``."""
    calibrated, summary = calibrate_artifact_zones(_measured_artifact(), apply_nudge=False)
    rec = calibrated[ZONE]
    assert summary["coherence_mode"] == "report_only"
    # Zero nudge: the score is preserved exactly.
    assert rec["adjustment"] == 0.0
    assert rec["calibrated_score"] == rec["raw_score"]
    # The comparison is still computed and surfaced (the trust story is intact).
    assert rec["status"] in {"adjusted_up", "adjusted_down", "validated_accurate"}
    assert rec["validated"] is True
    assert "no nudge" in rec["reasoning"].lower()


def test_calibrate_artifact_zones_legacy_nudge_changes_score():
    """``apply_nudge=True`` (the default) nudges the score toward the measured
    ratio — the legacy fallback when no weight calibration exists."""
    calibrated, summary = calibrate_artifact_zones(_measured_artifact(cis=60.0, ratio=1.9))
    rec = calibrated[ZONE]
    assert summary["coherence_mode"] == "legacy_nudge"
    # cis=60 -> expected 2.2x, measured 1.9x -> a real (non-zero) downward nudge.
    assert rec["adjustment"] != 0.0
    assert rec["calibrated_score"] != rec["raw_score"]


def test_report_only_and_legacy_agree_on_status_disagree_on_score():
    """Both modes classify the zone identically; only the SCORE differs."""
    art = _measured_artifact()
    rep, _ = calibrate_artifact_zones(art, apply_nudge=False)
    leg, _ = calibrate_artifact_zones(art, apply_nudge=True)
    assert rep[ZONE]["status"] == leg[ZONE]["status"]
    assert rep[ZONE]["calibrated_score"] == rep[ZONE]["raw_score"]
    assert leg[ZONE]["calibrated_score"] != leg[ZONE]["raw_score"]


# ═════════════════════════════════════════════════════════════════════════════
# B. run_from_artifact picks the mode from the calibration sidecar
# ═════════════════════════════════════════════════════════════════════════════

def _run(tmp_path: Path, calibration: dict | None):
    artifact_path = tmp_path / "zone_congestion_impact.json"
    artifact_path.write_text(json.dumps(_measured_artifact()), encoding="utf-8")
    cal = tmp_path / "c.json"
    if calibration is not None:
        cal.write_text(json.dumps(calibration), encoding="utf-8")
    return run_from_artifact(
        artifact_path,
        calibrated_out=tmp_path / "calibrated.json",
        log_out=tmp_path / "log.json",
        verbose=False,
        validation_path=tmp_path / "absent_v.json",
        calibration_path=cal,  # absent on disk when `calibration is None`
        degradation_path=tmp_path / "absent_d.json",
    )


def test_run_from_artifact_report_only_when_real_calibration_present(tmp_path):
    """A real weight fit on disk -> the agent runs report-only (zero nudge)."""
    calibrated, summary = _run(tmp_path, _real_calibration_report())
    assert summary["coherence_mode"] == "report_only"
    rec = calibrated[ZONE]
    assert rec["adjustment"] == 0.0
    assert rec["calibrated_score"] == rec["raw_score"]


def test_run_from_artifact_legacy_nudge_when_calibration_absent(tmp_path):
    """No calibration sidecar -> legacy α=0.3 nudge survives (fallback)."""
    calibrated, summary = _run(tmp_path, None)
    assert summary["coherence_mode"] == "legacy_nudge"
    assert calibrated[ZONE]["calibrated_score"] != calibrated[ZONE]["raw_score"]


def test_run_from_artifact_legacy_nudge_when_calibration_flat_aborted(tmp_path):
    """A flat-variance ABORT is not a real fit -> legacy nudge fallback."""
    aborted = {
        "old_weights": dict(WEIGHTS), "new_weights": dict(WEIGHTS),
        "method": "aborted_flat_variance",
    }
    calibrated, summary = _run(tmp_path, aborted)
    assert summary["coherence_mode"] == "legacy_nudge"
    assert calibrated[ZONE]["calibrated_score"] != calibrated[ZONE]["raw_score"]


# ═════════════════════════════════════════════════════════════════════════════
# C. DataStore — headline_bucket + time_regime (load() wiring)
# ═════════════════════════════════════════════════════════════════════════════

def _write_v2(data_dir: Path, *, with_sidecar: bool,
              calibrated_bucket: str = "morning_peak") -> None:
    processed = data_dir / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    artifact = {
        ZONE: {
            "all_day": _valid_breakdown(ZONE, "all_day", cis=60.0),
            "morning_peak": _valid_breakdown(ZONE, "morning_peak", cis=80.0),
        }
    }
    (processed / "zone_congestion_impact_v2.json").write_text(
        json.dumps(artifact), encoding="utf-8")
    if with_sidecar:
        meta = {
            "cis_version": "v2", "calibrated": True,
            "calibrated_bucket": calibrated_bucket,
            "weights": dict(WEIGHTS), "spearman_test": 0.61, "n_measured": 140,
        }
        (processed / CIS_CALIBRATION_META_FILENAME).write_text(
            json.dumps(meta), encoding="utf-8")


def test_load_sets_headline_bucket_to_calibrated_bucket(tmp_path, monkeypatch):
    """A calibrated v2 + sidecar -> headline_bucket == calibrated_bucket."""
    monkeypatch.delenv("CIS_ARTIFACT_PATH", raising=False)
    data_dir = tmp_path / "data"
    _write_v2(data_dir, with_sidecar=True)
    s = DataStore(data_dir=data_dir).load()

    assert s.calibration_meta["calibrated"] is True
    assert s.calibration_meta["calibrated_bucket"] == "morning_peak"
    assert s.headline_bucket == "morning_peak"
    assert s.headline_bucket == s.calibration_meta["calibrated_bucket"]


def test_load_time_regime_peak_calibrated_all_day_uncalibrated(tmp_path, monkeypatch):
    """The served breakdown is labelled calibrated for the peak window only."""
    monkeypatch.delenv("CIS_ARTIFACT_PATH", raising=False)
    data_dir = tmp_path / "data"
    _write_v2(data_dir, with_sidecar=True)
    s = DataStore(data_dir=data_dir).load()

    peak = s.congestion_breakdown(ZONE, "morning_peak")
    allday = s.congestion_breakdown(ZONE, "all_day")
    assert peak["time_regime"] == "calibrated"
    assert allday["time_regime"] == "uncalibrated"
    # The serving copy never mutated the in-memory artifact.
    assert "time_regime" not in s.congestion[ZONE]["morning_peak"]
    # Both still validate against the contract (time_regime is additive/optional).
    assert CongestionBreakdown.model_validate(peak).time_regime == "calibrated"
    assert CongestionBreakdown.model_validate(allday).time_regime == "uncalibrated"


def test_load_v2_without_sidecar_is_uncalibrated_all_day(tmp_path, monkeypatch):
    """v2 present but sidecar absent -> honest uncalibrated, headline all_day."""
    monkeypatch.delenv("CIS_ARTIFACT_PATH", raising=False)
    data_dir = tmp_path / "data"
    _write_v2(data_dir, with_sidecar=False)
    s = DataStore(data_dir=data_dir).load()

    assert s.calibration_meta == {"cis_version": "v2", "calibrated": False}
    assert s.headline_bucket == "all_day"
    # Even requesting the would-be peak bucket reads uncalibrated (no calibration).
    assert s.congestion_breakdown(ZONE, "morning_peak")["time_regime"] == "uncalibrated"


def test_load_v1_fallback_is_uncalibrated_all_day(tmp_path, monkeypatch):
    """v1 fallback (no v2) -> headline all_day, every bucket uncalibrated."""
    monkeypatch.delenv("CIS_ARTIFACT_PATH", raising=False)
    data_dir = tmp_path / "data"
    processed = data_dir / "processed"
    processed.mkdir(parents=True)
    v1 = {ZONE: {"all_day": _valid_breakdown(ZONE, "all_day", cis=30.0)}}
    (processed / "zone_congestion_impact.json").write_text(
        json.dumps(v1), encoding="utf-8")
    s = DataStore(data_dir=data_dir).load()

    assert s.cis_artifact_path.name == "zone_congestion_impact.json"
    assert s.headline_bucket == "all_day"
    assert s.congestion_breakdown(ZONE, "all_day")["time_regime"] == "uncalibrated"
    assert s.congestion_breakdown(ZONE, "morning_peak")["time_regime"] == "uncalibrated"


# ═════════════════════════════════════════════════════════════════════════════
# D. HTTP — /health and the additive /risk/calibration endpoint
# ═════════════════════════════════════════════════════════════════════════════

# These exercise the module-level `store` singleton that every router imports, so
# they snapshot and restore its state to stay order-independent (mirrors the
# approach in backend/tests/test_cis_endpoints_integration.py). The TestClient is
# created WITHOUT its context manager so the app's startup `store.load()` never
# runs and cannot clobber the injected state.

_SNAPSHOT_FIELDS = (
    "congestion", "calibrated", "calibration_meta", "headline_bucket",
    "loaded", "zones", "agent_summary", "sources",
)


def _install(meta: dict, headline_bucket: str):
    saved = {f: getattr(store, f) for f in _SNAPSHOT_FIELDS}
    store.congestion = {
        ZONE: {
            "all_day": _valid_breakdown(ZONE, "all_day", cis=60.0),
            "morning_peak": _valid_breakdown(ZONE, "morning_peak", cis=80.0),
        }
    }
    store.calibrated = {}
    store.calibration_meta = dict(meta)
    store.headline_bucket = headline_bucket
    store.loaded = True
    store.zones = []
    store.agent_summary = {}
    store.sources = {}
    return saved


def _restore(saved: dict):
    for f, v in saved.items():
        setattr(store, f, v)


@pytest.fixture
def calibrated_client():
    saved = _install(
        {"cis_version": "v2", "calibrated": True, "calibrated_bucket": "morning_peak",
         "weights": dict(WEIGHTS), "spearman_test": 0.61, "n_measured": 140},
        headline_bucket="morning_peak",
    )
    try:
        yield TestClient(app)
    finally:
        _restore(saved)


@pytest.fixture
def uncalibrated_client():
    saved = _install({"cis_version": "v1", "calibrated": False}, headline_bucket="all_day")
    try:
        yield TestClient(app)
    finally:
        _restore(saved)


def test_health_exposes_headline_and_calibrated_bucket(calibrated_client):
    body = calibrated_client.get("/health").json()
    assert body["headline_bucket"] == "morning_peak"
    assert body["calibrated_bucket"] == "morning_peak"
    assert body["calibration"]["calibrated"] is True


def test_health_uncalibrated_has_all_day_headline_and_null_bucket(uncalibrated_client):
    body = uncalibrated_client.get("/health").json()
    assert body["headline_bucket"] == "all_day"
    assert body["calibrated_bucket"] is None
    assert body["calibration"]["calibrated"] is False


def test_risk_calibration_endpoint_exposes_bucket_regime(calibrated_client):
    resp = calibrated_client.get("/risk/calibration")
    assert resp.status_code == 200
    body = resp.json()
    assert body["calibrated"] is True
    assert body["cis_version"] == "v2"
    assert body["headline_bucket"] == "morning_peak"
    assert body["calibrated_bucket"] == "morning_peak"
    assert body["spearman_test"] == 0.61
    assert body["n_measured"] == 140
    # Dual-mount (bare + /api) returns the identical payload.
    assert calibrated_client.get("/api/risk/calibration").json() == body


def test_risk_calibration_endpoint_uncalibrated(uncalibrated_client):
    body = uncalibrated_client.get("/risk/calibration").json()
    assert body["calibrated"] is False
    assert body["cis_version"] == "v1"
    assert body["headline_bucket"] == "all_day"
    assert body["calibrated_bucket"] is None


def test_risk_calibration_does_not_shadow_zone_route(calibrated_client):
    """`/risk/calibration` resolves to the calibration endpoint, while a real
    zone id still resolves to the per-zone breakdown — no route collision."""
    calib = calibrated_client.get("/risk/calibration").json()
    assert "headline_bucket" in calib and "zone_id" not in calib

    zone = calibrated_client.get(f"/risk/{ZONE}", params={"time_bucket": "morning_peak"})
    assert zone.status_code == 200
    assert zone.json()["zone_id"] == ZONE


def test_risk_zone_detail_time_regime_over_http(calibrated_client):
    """The per-zone breakdown carries the regime label end-to-end over HTTP."""
    peak = calibrated_client.get(f"/risk/{ZONE}", params={"time_bucket": "morning_peak"})
    assert peak.json()["time_regime"] == "calibrated"
    # Default bucket (all_day) is honestly uncalibrated.
    allday = calibrated_client.get(f"/risk/{ZONE}")
    assert allday.json()["time_regime"] == "uncalibrated"
