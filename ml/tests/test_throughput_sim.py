"""
Tests for the before/after throughput simulation (``ml.game.throughput_sim``,
Task 7).
==============================================================================

Covers the Task 7 acceptance criteria:
* monotonic: more teams -> >= modeled reduction (up to coverage saturation);
* reproducible (deterministic, no randomness);
* all constants documented in the output ``constants`` block;
* guarded edge cases (empty / all-zero CIS) and the DataStore/endpoint wiring.

Fixtures use raw CIS values (the simulation operates on CIS the calibration
pipeline produces; the model itself adds no circular signal).
"""

from __future__ import annotations

import json

import pytest

from ml.game.throughput_sim import (
    CONSTANTS,
    ENFORCEMENT_EFFECTIVENESS,
    congestion_index,
    run,
    select_top_cis,
    simulate_throughput,
    stackelberg_probabilities,
    zone_coverage_probability,
)


# ─── Pure helpers ────────────────────────────────────────────────────────────

def test_stackelberg_probabilities_sum_to_one():
    probs = stackelberg_probabilities([80.0, 60.0, 40.0, 20.0])
    assert sum(probs) == pytest.approx(1.0)
    # Higher CIS -> higher probability (CIS^1.5 is increasing).
    assert probs[0] > probs[1] > probs[2] > probs[3]


def test_stackelberg_probabilities_all_zero_guarded():
    assert stackelberg_probabilities([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]
    assert stackelberg_probabilities([]) == []


def test_zone_coverage_probability_monotonic_in_teams():
    p = 0.3
    cov = [zone_coverage_probability(p, n) for n in range(0, 11)]
    assert cov[0] == 0.0
    assert all(cov[i] <= cov[i + 1] for i in range(len(cov) - 1))
    assert cov[-1] < 1.0  # never fully saturates for p < 1
    assert zone_coverage_probability(1.0, 1) == 1.0


def test_congestion_index_formula():
    # C = sum(CIS/100 * w); uniform w=1.
    assert congestion_index([100.0, 50.0]) == pytest.approx(1.5)
    assert congestion_index([100.0, 50.0], weights=[1.0, 0.0]) == pytest.approx(1.0)


# ─── simulate_throughput ─────────────────────────────────────────────────────

def _cis_values():
    return [90.0, 75.0, 60.0, 45.0, 30.0, 20.0, 10.0]


def test_pct_reduction_is_monotonic_non_decreasing():
    result = simulate_throughput(_cis_values(), max_teams=20)
    pct = [result["teams"][str(n)]["pct_reduction"] for n in range(1, 21)]
    assert all(pct[i] <= pct[i + 1] + 1e-9 for i in range(len(pct) - 1)), pct
    assert pct[0] > 0.0           # one team already helps
    assert pct[-1] > pct[0]       # more teams help more


def test_minutes_saved_monotonic_and_labeled():
    result = simulate_throughput(_cis_values(), max_teams=20)
    mins = [result["teams"][str(n)]["modeled_minutes_saved"] for n in range(1, 21)]
    assert all(mins[i] <= mins[i + 1] + 1e-9 for i in range(len(mins) - 1))
    assert "modeled estimate" in result["constants"]["disclaimer"].lower()


def test_reduction_bounded_by_effectiveness():
    # Even with many teams, no zone loses more than ENFORCEMENT_EFFECTIVENESS of
    # its blockage, so the index can never drop below (1 - eff) * C_before.
    result = simulate_throughput(_cis_values(), max_teams=20)
    c_before = result["congestion_index_before"]
    c_after_max_teams = result["teams"]["20"]["congestion_index_after"]
    assert c_after_max_teams >= (1.0 - ENFORCEMENT_EFFECTIVENESS) * c_before - 1e-9


def test_constants_block_is_documented():
    result = simulate_throughput(_cis_values(), max_teams=5)
    c = result["constants"]
    for key in ("enforcement_effectiveness", "patrol_alpha", "max_teams",
                "minutes_per_index_unit", "coverage_model", "weight_model", "disclaimer"):
        assert key in c, f"missing documented constant: {key}"
    assert c["enforcement_effectiveness"] == ENFORCEMENT_EFFECTIVENESS
    assert set(CONSTANTS).issubset(set(c))


def test_simulate_is_deterministic():
    a = simulate_throughput(_cis_values(), max_teams=20, generated_at="x")
    b = simulate_throughput(_cis_values(), max_teams=20, generated_at="x")
    assert a == b


def test_empty_and_zero_cis_guarded():
    empty = simulate_throughput([], max_teams=5, generated_at="x")
    assert empty["congestion_index_before"] == 0.0
    assert all(t["pct_reduction"] == 0.0 for t in empty["teams"].values())

    zeros = simulate_throughput([0.0, 0.0], max_teams=5, generated_at="x")
    assert zeros["congestion_index_before"] == 0.0
    assert all(t["pct_reduction"] == 0.0 for t in zeros["teams"].values())


# ─── select_top_cis ──────────────────────────────────────────────────────────

def test_select_top_cis_takes_highest_and_ignores_reserved_keys():
    artifact = {
        "z1": {"all_day": {"congestion_impact": 30.0}},
        "z2": {"all_day": {"congestion_impact": 90.0}},
        "z3": {"all_day": {"congestion_impact": 60.0}},
        "_calibration": {"cis_version": "v2"},  # reserved — must be ignored
    }
    vals = select_top_cis(artifact, top_n=2)
    assert vals == [90.0, 60.0]


# ─── runner ──────────────────────────────────────────────────────────────────

def test_run_writes_output_and_is_deterministic(tmp_path):
    artifact = {f"z{i:02d}": {"all_day": {"congestion_impact": float(100 - i)}} for i in range(70)}
    cis_path = tmp_path / "cis.json"
    cis_path.write_text(json.dumps(artifact), encoding="utf-8")

    out1 = tmp_path / "thr1.json"
    out2 = tmp_path / "thr2.json"
    r1 = run(cis_path, out1, top_n=60, max_teams=20, generated_at="x", verbose=False)
    r2 = run(cis_path, out2, top_n=60, max_teams=20, generated_at="x", verbose=False)

    assert out1.exists()
    assert out1.read_bytes() == out2.read_bytes()
    assert r1 == r2
    assert r1["n_zones"] == 60
    assert r1["teams"]["20"]["pct_reduction"] >= r1["teams"]["1"]["pct_reduction"]


# ─── backend wiring ──────────────────────────────────────────────────────────

def test_datastore_and_endpoint_throughput(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app.data_loader import DataStore
    from backend.app.main import app

    # DataStore over a fixture CIS artifact.
    data_dir = tmp_path / "data"
    processed = data_dir / "processed"
    processed.mkdir(parents=True)
    artifact = {
        f"z{i:02d}": {"all_day": {
            "zone_id": f"z{i:02d}", "h3_id": f"z{i:02d}", "time_bucket": "all_day",
            "lat": 12.9 + i * 0.001, "lon": 77.5 + i * 0.001,
            "congestion_impact": float(90 - i), "impact_band": "SEVERE",
            "components": {"lane_blockage": 0.3, "intersection_impact": 0.2,
                           "traffic_degradation": 0.5, "access_blockage": 0.1,
                           "vehicle_size": 0.2, "severity": 0.3},
            "weights": {"lane_blockage": 0.3, "intersection_impact": 0.25,
                        "traffic_degradation": 0.25, "access_blockage": 0.1,
                        "vehicle_size": 0.1},
            "estimated_lane_hours_blocked": 1.0, "total_records": 100 - i,
            "top_violations": ["WRONG PARKING"], "station": "PS",
            "mappls_travel_time_ratio": None, "is_traffic_degradation_defaulted": True,
            "calibrated_impact": None,
        }} for i in range(10)
    }
    (processed / "zone_congestion_impact.json").write_text(json.dumps(artifact), encoding="utf-8")

    store = DataStore(data_dir=data_dir).load()
    sim = store.throughput_simulation(max_teams=10, top_n=10)
    assert sim["n_zones"] == 10
    assert sim["teams"]["10"]["pct_reduction"] >= sim["teams"]["1"]["pct_reduction"]
    assert "disclaimer" in sim["constants"]

    # Endpoint smoke test over the committed (v1) artifact.
    with TestClient(app) as client:
        r = client.get("/simulate/throughput?max_teams=5")
        assert r.status_code == 200
        body = r.json()
        assert "teams" in body and "constants" in body
        assert body["teams"]["5"]["pct_reduction"] >= body["teams"]["1"]["pct_reduction"]
