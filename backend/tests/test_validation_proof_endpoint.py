"""
Tests for the /validation/proof endpoint + DataStore.validation_proof (Task 13).
==============================================================================

The endpoint serves the offline ``cis_validation_report.json`` (Task 2/10) as a
stable, additive "density ≠ impact" proof payload. These tests pin:

* the served SHAPE (the three test-split Spearman correlations + CIs, the
  baseline_beaten flag, the per-zone scatter points, and the forward-compatible
  ``calibration_strength`` passthrough);
* the graceful PENDING state when no report exists (``available: False`` with no
  points — never fabricated numbers);
* dual-mount equivalence (bare path + ``/api`` prefix);
* the ``DataStore`` load() wiring (report read from disk; absent -> pending).

All fixtures are CIS-INDEPENDENT illustrative dicts (arbitrary correlation values
in a temp/in-memory report) — no real artifact is committed, and the values here
are never derived from a CIS score.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.data_loader import DataStore, store
from backend.app.main import app

POINT_KEYS = {"h3_id", "cis", "cis_honest", "count", "measured_ratio",
              "is_exploration", "split"}


def _sample_report(**overrides) -> dict:
    """An illustrative validation report (CIS-independent values)."""
    report = {
        "n_measured": 6, "n_test": 3, "n_exploration": 2, "n_proof": 3,
        "spearman_cis_honest_test": 0.72,
        "spearman_cis_honest_test_ci": {"rho": 0.72, "lo": 0.41, "hi": 0.93,
                                        "p_approx": 0.01, "n": 3, "n_boot": 2000},
        "spearman_count_test": 0.18,
        "spearman_count_test_ci": {"rho": 0.18, "lo": -0.30, "hi": 0.60,
                                   "p_approx": 0.5, "n": 3, "n_boot": 2000},
        "spearman_cis_full_test": 0.95,
        "spearman_cis_full_test_ci": {"rho": 0.95, "lo": 0.80, "hi": 0.99,
                                      "p_approx": 0.001, "n": 3, "n_boot": 2000},
        "cis_full_note": "circular / upper bound — contains the measured ratio",
        "baseline_beaten": True,
        "honest_weights": {"lane_blockage": 0.4, "intersection_impact": 0.3,
                           "access_blockage": 0.2, "vehicle_size": 0.1},
        "honest_excludes": "traffic_degradation",
        "split_seed": 1337, "time_bucket": "all_day",
        "generated_at": "2026-06-22T00:00:00+00:00",
        "points": [
            {"h3_id": "z1", "cis": 80.0, "cis_honest": 0.7, "count": 50,
             "measured_ratio": 1.8, "is_exploration": False, "split": "test"},
            {"h3_id": "z2", "cis": 40.0, "cis_honest": 0.3, "count": 900,
             "measured_ratio": 1.2, "is_exploration": True, "split": "test"},
            {"h3_id": "z3", "cis": 60.0, "cis_honest": 0.5, "count": 300,
             "measured_ratio": 1.5, "is_exploration": False, "split": "train"},
        ],
    }
    report.update(overrides)
    return report


@pytest.fixture
def install_proof():
    """Install a given report on the shared ``store`` and yield a TestClient maker.

    Snapshots and restores ``store.validation_report`` / ``store.loaded`` so the
    suite stays order-independent. The client is created WITHOUT its context
    manager so the app's startup ``store.load()`` never overwrites the injection.
    """
    saved = (store.validation_report, store.loaded)

    def _make(report: dict) -> TestClient:
        store.validation_report = report
        store.loaded = True
        return TestClient(app)

    try:
        yield _make
    finally:
        store.validation_report, store.loaded = saved


# ─── populated report: served shape ──────────────────────────────────────────

def test_proof_endpoint_serves_three_correlations_and_points(install_proof):
    client = install_proof(_sample_report())
    body = client.get("/validation/proof").json()

    assert body["available"] is True
    assert body["spearman_cis_honest"] == 0.72
    assert body["spearman_count"] == 0.18
    assert body["spearman_cis_full"] == 0.95
    assert body["baseline_beaten"] is True
    # CIs are passed through intact.
    assert body["spearman_cis_honest_ci"]["lo"] == 0.41
    assert body["spearman_cis_honest_ci"]["hi"] == 0.93
    assert body["spearman_count_ci"]["lo"] == -0.30
    # The full CIS is flagged as the circular upper bound.
    assert "circular" in body["cis_full_note"]
    assert body["honest_excludes"] == "traffic_degradation"
    # Scatter points carry exactly the expected keys (and nothing private).
    assert len(body["points"]) == 3
    for p in body["points"]:
        assert set(p) == POINT_KEYS
    assert "_components4" not in body["points"][0]


def test_proof_endpoint_calibration_strength_passthrough(install_proof):
    # Absent in the report -> surfaced as None (Task 15 populates it later).
    body = install_proof(_sample_report()).get("/validation/proof").json()
    assert body["calibration_strength"] is None

    # Present -> passed straight through.
    body2 = install_proof(
        _sample_report(calibration_strength="strong")
    ).get("/validation/proof").json()
    assert body2["calibration_strength"] == "strong"


def test_proof_endpoint_dual_mount_equivalent(install_proof):
    client = install_proof(_sample_report())
    bare = client.get("/validation/proof")
    api = client.get("/api/validation/proof")
    assert bare.status_code == api.status_code == 200
    assert bare.json() == api.json()


# ─── pending state: no report on disk ────────────────────────────────────────

def test_proof_endpoint_pending_when_report_absent(install_proof):
    body = install_proof({}).get("/validation/proof").json()
    assert body["available"] is False
    assert body["points"] == []
    assert body["spearman_cis_honest"] is None
    assert body["spearman_count"] is None
    assert body["baseline_beaten"] is None
    assert body["calibration_strength"] is None


# ─── DataStore load() wiring ─────────────────────────────────────────────────

def test_datastore_loads_validation_report_from_disk(tmp_path, monkeypatch):
    monkeypatch.delenv("CIS_ARTIFACT_PATH", raising=False)
    data_dir = tmp_path / "data"
    processed = data_dir / "processed"
    processed.mkdir(parents=True)
    (processed / "cis_validation_report.json").write_text(
        json.dumps(_sample_report()), encoding="utf-8")

    s = DataStore(data_dir=data_dir).load()
    proof = s.validation_proof()
    assert proof["available"] is True
    assert proof["spearman_cis_honest"] == 0.72
    assert proof["n_proof"] == 3
    assert len(proof["points"]) == 3


def test_datastore_validation_proof_pending_when_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("CIS_ARTIFACT_PATH", raising=False)
    data_dir = tmp_path / "data"
    (data_dir / "processed").mkdir(parents=True)

    s = DataStore(data_dir=data_dir).load()
    proof = s.validation_proof()
    assert proof["available"] is False
    assert proof["points"] == []
    assert proof["spearman_cis_honest"] is None
