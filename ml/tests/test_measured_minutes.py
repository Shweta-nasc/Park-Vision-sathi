"""
Tests for the MapMyIndia-grounded real-minutes-saved estimate on measured
corridors (Task 7 extension, ``ml.game.throughput_sim``).
==============================================================================

Fixtures are CIS-independent and use a FAKE degradation model (so no real
calibration/network is needed). Covers:
* ``minutes_i`` never exceeds the measured excess ``E_i`` (the clamp holds);
* monotonic in team count N;
* zero when coverage is 0 (N=0) or effectiveness is 0;
* deterministic;
* the pending block when there is no model / no observations.
"""

from __future__ import annotations

import pytest

from ml.game.throughput_sim import (
    ENFORCEMENT_EFFECTIVENESS,
    MeasuredZone,
    _feature_vector,
    build_measured_zones,
    compute_measured_minutes,
    estimate_measured_minutes_saved,
    stackelberg_probabilities,
    zone_coverage_probability,
)


class FakeModel:
    """Linear degradation model in the 3 reducible components (CIS-independent)."""

    def __init__(self, scale: float = 0.2):
        self.scale = scale

    def predict(self, X):
        # X: list of [lane, intersection, access, vehicle, poi, ffs]; depends only
        # on the three enforcement-reducible components (lane/intersection/access).
        return [self.scale * (row[0] + row[1] + row[2]) for row in X]


def _zones():
    # Three measured corridors. Raw values (t_ff, ratio, components) are arbitrary
    # and CIS-independent. components in COMPONENTS_4 order.
    return [
        MeasuredZone("z1", t_ff_s=120.0, ratio_measured=1.8,
                     components=(0.6, 0.4, 0.3, 0.5), poi_count=2.0, free_flow_speed_kmph=18.0, cis=80.0),
        MeasuredZone("z2", t_ff_s=90.0, ratio_measured=1.4,
                     components=(0.4, 0.2, 0.5, 0.3), poi_count=1.0, free_flow_speed_kmph=25.0, cis=55.0),
        MeasuredZone("z3", t_ff_s=200.0, ratio_measured=2.2,
                     components=(0.8, 0.6, 0.2, 0.7), poi_count=3.0, free_flow_speed_kmph=12.0, cis=92.0),
    ]


def test_feature_vector_order():
    assert _feature_vector((0.6, 0.4, 0.3, 0.5), 2.0, 18.0) == [0.6, 0.4, 0.3, 0.5, 2.0, 18.0]


def test_minutes_never_exceed_measured_excess():
    # A huge-scale model forces d_ratio >> excess, so the clamp must bind: each
    # zone's saved minutes == its excess minutes, and D == M (pct == 100).
    zones = _zones()
    result = estimate_measured_minutes_saved(zones, FakeModel(scale=1000.0), n_teams=20)
    assert result["available"] is True
    assert result["estimated_minutes_saved"] <= result["total_excess_delay_min"] + 1e-6
    assert result["pct_of_measured_delay"] <= 100.0 + 1e-9
    # With the clamp binding everywhere and full coverage, saved ~= excess.
    assert result["estimated_minutes_saved"] == pytest.approx(result["total_excess_delay_min"], rel=1e-6)


def test_per_zone_clamp_holds_against_excess():
    # Verify the per-zone invariant minutes_i <= E_i/60 directly.
    zones = _zones()
    model = FakeModel(scale=1000.0)
    probs = stackelberg_probabilities([z.cis for z in zones])
    n_teams = 5
    for z, p in zip(zones, probs):
        single = estimate_measured_minutes_saved([z], model, n_teams=n_teams, patrol_probs=[p])
        excess_min = z.t_ff_s * max(0.0, z.ratio_measured - 1.0) / 60.0
        assert single["estimated_minutes_saved"] <= excess_min + 1e-6


def test_monotonic_in_team_count():
    zones = _zones()
    model = FakeModel(scale=0.2)
    saved = [
        estimate_measured_minutes_saved(zones, model, n_teams=n)["estimated_minutes_saved"]
        for n in range(0, 21)
    ]
    assert all(saved[i] <= saved[i + 1] + 1e-9 for i in range(len(saved) - 1)), saved
    assert saved[0] == 0.0   # N=0 -> coverage 0 -> nothing saved
    assert saved[-1] > 0.0


def test_zero_when_coverage_zero():
    zones = _zones()
    result = estimate_measured_minutes_saved(zones, FakeModel(0.5), n_teams=0)
    assert result["estimated_minutes_saved"] == 0.0
    assert result["pct_of_measured_delay"] == 0.0


def test_zero_when_effectiveness_zero():
    zones = _zones()
    result = estimate_measured_minutes_saved(zones, FakeModel(0.5), n_teams=20, effectiveness=0.0)
    assert result["estimated_minutes_saved"] == 0.0


def test_deterministic():
    zones = _zones()
    a = estimate_measured_minutes_saved(zones, FakeModel(0.3), n_teams=10)
    b = estimate_measured_minutes_saved(zones, FakeModel(0.3), n_teams=10)
    assert a == b


def test_caveats_present_and_specific():
    result = estimate_measured_minutes_saved(_zones(), FakeModel(0.2), n_teams=5)
    text = " ".join(result["caveats"]).lower()
    assert "350" in text                       # local-segment caveat
    assert "assumption" in text                # effectiveness caveat
    assert "model" in text                     # attribution caveat
    assert result["effectiveness"] == ENFORCEMENT_EFFECTIVENESS


def test_pending_when_no_model_or_no_zones():
    assert estimate_measured_minutes_saved([], FakeModel(0.2), n_teams=5)["available"] is False
    assert estimate_measured_minutes_saved(_zones(), None, n_teams=5)["available"] is False


def test_compute_measured_minutes_pending_when_no_observations():
    block = compute_measured_minutes({"z": {"all_day": {"components": {}}}}, {})
    assert block["available"] is False
    assert "pending" in block["reason"].lower()


# ─── build_measured_zones from artifact + observations ───────────────────────

def test_build_measured_zones_from_observations():
    artifact = {
        "z1": {"all_day": {"congestion_impact": 80.0, "components": {
            "lane_blockage": 0.6, "intersection_impact": 0.4,
            "access_blockage": 0.3, "vehicle_size": 0.5,
            "traffic_degradation": 0.4, "severity": 0.3}}},
    }
    observations = {
        "z1": {
            "zone_id": "z1", "congestion_ratio": 1.8,
            "raw_legs": [{"baseline_s": 100.0}, {"baseline_s": 140.0}, {"baseline_s": 120.0}],
            "pois": [{"name": "a"}, {"name": "b"}], "free_flow_speed_kmph": 18.0,
        },
        "z2_no_legs": {"zone_id": "z2_no_legs", "congestion_ratio": 1.5, "raw_legs": []},  # skipped
    }
    zones = build_measured_zones(artifact, observations)
    assert len(zones) == 1
    z = zones[0]
    assert z.zone_id == "z1"
    assert z.t_ff_s == 120.0       # median(100,140,120)
    assert z.ratio_measured == 1.8
    assert z.components == (0.6, 0.4, 0.3, 0.5)
    assert z.poi_count == 2.0
