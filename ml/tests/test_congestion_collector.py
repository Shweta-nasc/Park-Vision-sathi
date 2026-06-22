"""
Tests for the MapMyIndia local-segment congestion collector v2
(``ml.enrichment.congestion_collector``).
==============================================================================

These are example-based unit/integration tests (plain pytest). They never touch
the network: the HTTP layer is injected as a fake ``get_json`` callable that
records every call and returns canned Mappls-shaped responses. They cover the
Task 1 acceptance criteria:

* dry-run cost estimate matches a hand count (and makes zero calls);
* ratio math is correct on mocked responses (median of per-leg eta/baseline);
* the budget cap raises/aborts when the estimate exceeds the budget;
* the cache prevents re-calls for already-collected zones;
* offset -> distance sanity (legs are ~350 m);
* zone selection is deterministic and tags exploration zones;
* free-flow speed prefers API distances and falls back to haversine (flagged);
* the API token never leaks into the written artifact.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from ml.enrichment import congestion_collector as cc
from ml.enrichment.congestion_collector import (
    BudgetExceededError,
    LEG_OFFSETS,
    ZoneSpec,
    collect,
    compute_congestion_ratio,
    compute_free_flow_speed,
    estimate_calls,
    estimate_rupees,
    haversine_m,
    is_peak_ist,
    leg_endpoints,
    parse_distance_matrix,
    select_zones,
)

# A peak IST moment (09:30) so the off-peak warning path isn't taken in tests
# that don't care about it.
PEAK_NOW = datetime(2024, 3, 15, 9, 30, tzinfo=cc.IST)


# ─── Fake HTTP layer ─────────────────────────────────────────────────────────

class FakeApi:
    """Records calls and returns canned Mappls responses keyed by the label."""

    def __init__(self, baseline_s=100.0, eta_s=200.0, distance_m=400.0, with_distances=True):
        self.baseline_s = baseline_s
        self.eta_s = eta_s
        self.distance_m = distance_m
        self.with_distances = with_distances
        self.calls: list[tuple[str, dict, str]] = []

    def __call__(self, url, params, label):
        self.calls.append((url, dict(params), label))
        if label == "distance_matrix":
            results = {"code": "Ok", "durations": [[0.0, self.baseline_s]]}
            if self.with_distances:
                results["distances"] = [[0.0, self.distance_m]]
            return {"results": results}
        if label == "distance_matrix_eta":
            return {"results": {"code": "Ok", "durations": [[0.0, self.eta_s]]}}
        if label == "reverse_geocode":
            return {"results": [{"street": "Test St", "locality": "Testville"}]}
        if label == "nearby_poi":
            return {"suggestedLocations": [{"placeName": "Bus Stop", "distance": 120, "keywords": ["TRNBUS"]}]}
        return None

    @property
    def dm_calls(self) -> int:
        return sum(1 for _, _, lbl in self.calls if lbl in ("distance_matrix", "distance_matrix_eta"))


def _artifact(n: int = 5) -> dict:
    """Synthetic CIS artifact: n zones, descending total_records."""
    art = {}
    for i in range(n):
        zid = f"89000000{i:03d}ffff"
        art[zid] = {
            "all_day": {
                "lat": 12.97 + i * 0.001,
                "lon": 77.59 + i * 0.001,
                "total_records": (n - i) * 10,
                "station": f"PS{i}",
            }
        }
    return art


def _write_artifact(tmp_path: Path, n: int = 5) -> Path:
    p = tmp_path / "zone_congestion_impact.json"
    p.write_text(json.dumps(_artifact(n)), encoding="utf-8")
    return p


# ─── Pure helpers ────────────────────────────────────────────────────────────

def test_offset_legs_are_about_350_metres():
    """Each N/E/S/W leg from a Bengaluru centroid is ~350 m (within tolerance)."""
    lat, lon = 12.9716, 77.5946
    for _direction, dlat, dlon in LEG_OFFSETS:
        dist = haversine_m(lat, lon, lat + dlat, lon + dlon)
        assert 300.0 <= dist <= 420.0, f"leg distance {dist:.1f} m outside ~350 m band"


def test_leg_endpoints_returns_four_directions():
    eps = leg_endpoints(12.97, 77.59)
    assert [d for d, _, _ in eps] == ["N", "E", "S", "W"]


def test_parse_distance_matrix_reads_duration_and_distance():
    data = {"results": {"code": "Ok", "durations": [[0, 141.0]], "distances": [[0, 880.0]]}}
    dur, dist = parse_distance_matrix(data)
    assert dur == 141.0 and dist == 880.0


def test_parse_distance_matrix_missing_distances_is_none():
    data = {"results": {"code": "Ok", "durations": [[0, 141.0]]}}
    dur, dist = parse_distance_matrix(data)
    assert dur == 141.0 and dist is None


def test_parse_distance_matrix_non_ok_returns_none():
    assert parse_distance_matrix({"results": {"code": "NoRoute"}}) == (None, None)
    assert parse_distance_matrix(None) == (None, None)


def test_compute_congestion_ratio_is_median():
    legs = [{"ratio": 1.0}, {"ratio": 2.0}, {"ratio": 3.0}, {"ratio": 5.0}]
    assert compute_congestion_ratio(legs) == 2.5  # median of [1,2,3,5]


def test_compute_congestion_ratio_ignores_invalid():
    legs = [{"ratio": None}, {"ratio": 2.0}, {"ratio": -1.0}, {"ratio": 4.0}]
    assert compute_congestion_ratio(legs) == 3.0  # median of [2,4]
    assert compute_congestion_ratio([{"ratio": None}]) is None


def test_free_flow_speed_prefers_api_distance():
    legs = [{"baseline_s": 100.0, "distance_m": 400.0, "haversine_m": 350.0}]
    speed, approx = compute_free_flow_speed(legs)
    assert speed == pytest.approx(400.0 / 100.0 * 3.6)  # 14.4 km/h
    assert approx is False


def test_free_flow_speed_falls_back_to_haversine_and_flags():
    legs = [{"baseline_s": 100.0, "distance_m": None, "haversine_m": 360.0}]
    speed, approx = compute_free_flow_speed(legs)
    assert speed == pytest.approx(360.0 / 100.0 * 3.6)
    assert approx is True


def test_estimate_calls_and_rupees_hand_count():
    # 4 legs -> 4*2 + 1 + 1 = 10 calls/zone.
    assert estimate_calls(1) == 10
    assert estimate_calls(150) == 1500
    assert estimate_rupees(1500, 0.03) == pytest.approx(45.0)


def test_is_peak_ist():
    assert is_peak_ist(9) is True
    assert is_peak_ist(19) is True
    assert is_peak_ist(13) is False
    assert is_peak_ist(23) is False


# ─── Zone selection ──────────────────────────────────────────────────────────

def test_select_zones_top_by_volume_then_exploration():
    art = _artifact(10)
    zones = select_zones(art, top_n=3, explore_n=2, seed=42)
    core = [z for z in zones if not z.is_exploration]
    explore = [z for z in zones if z.is_exploration]

    assert len(core) == 3 and len(explore) == 2
    # Core are the three highest-volume zones, in descending order.
    assert [z.total_records for z in core] == [100, 90, 80]
    # Exploration zones are drawn from the lower-volume remainder only.
    assert all(z.total_records <= 70 for z in explore)


def test_select_zones_is_deterministic_for_seed():
    art = _artifact(20)
    a = select_zones(art, top_n=5, explore_n=5, seed=7)
    b = select_zones(art, top_n=5, explore_n=5, seed=7)
    assert [z.zone_id for z in a] == [z.zone_id for z in b]


def test_select_zones_different_seed_changes_exploration():
    art = _artifact(40)
    a = {z.zone_id for z in select_zones(art, top_n=5, explore_n=5, seed=1) if z.is_exploration}
    b = {z.zone_id for z in select_zones(art, top_n=5, explore_n=5, seed=999) if z.is_exploration}
    assert a != b


# ─── Collection / orchestration ──────────────────────────────────────────────

def test_dry_run_makes_no_calls(tmp_path):
    art_path = _write_artifact(tmp_path, n=5)
    out_path = tmp_path / "obs.json"
    fake = FakeApi()
    result = collect(
        artifact_path=art_path, output_path=out_path,
        top_n=5, explore_n=0, dry_run=True,
        get_json=fake, now_ist=PEAK_NOW, token="SECRET", verbose=False,
    )
    assert fake.calls == []          # zero API calls
    assert result == {}              # nothing collected
    assert not out_path.exists()     # no file written on dry-run


def test_ratio_math_end_to_end_on_mocked_responses(tmp_path):
    art_path = _write_artifact(tmp_path, n=1)
    out_path = tmp_path / "obs.json"
    fake = FakeApi(baseline_s=100.0, eta_s=250.0, distance_m=420.0)  # ratio 2.5/leg

    result = collect(
        artifact_path=art_path, output_path=out_path,
        top_n=1, explore_n=0, get_json=fake, now_ist=PEAK_NOW,
        token="SECRET", sleep_between_apis=0.0, sleep_between_zones=0.0, verbose=False,
    )
    obs = next(iter(result.values()))
    assert obs["congestion_ratio"] == pytest.approx(2.5)
    assert obs["n_legs"] == len(LEG_OFFSETS)
    assert obs["free_flow_speed_approx"] is False
    assert obs["free_flow_speed_kmph"] == pytest.approx(420.0 / 100.0 * 3.6)
    assert obs["method"] == "local_segment_v2"
    assert obs["source"] == "mapmyindia"
    assert obs["road_name"] == "Test St, Testville"
    assert obs["pois"] and obs["pois"][0]["category"] == "TRNBUS"


def test_budget_cap_aborts_before_any_call(tmp_path):
    art_path = _write_artifact(tmp_path, n=5)
    out_path = tmp_path / "obs.json"
    fake = FakeApi()
    # 5 zones * 10 calls = 50 > budget 30.
    with pytest.raises(BudgetExceededError):
        collect(
            artifact_path=art_path, output_path=out_path,
            top_n=5, explore_n=0, budget=30,
            get_json=fake, now_ist=PEAK_NOW, token="SECRET", verbose=False,
        )
    assert fake.calls == []          # refused before calling
    assert not out_path.exists()


def test_cache_prevents_recalls(tmp_path):
    art_path = _write_artifact(tmp_path, n=3)
    out_path = tmp_path / "obs.json"

    # Seed the cache with the top zone's observation (highest total_records).
    zones = select_zones(_artifact(3), top_n=3, explore_n=0)
    cached_id = zones[0].zone_id
    out_path.write_text(json.dumps({cached_id: {"zone_id": cached_id, "cached": True}}), encoding="utf-8")

    fake = FakeApi()
    result = collect(
        artifact_path=art_path, output_path=out_path,
        top_n=3, explore_n=0, get_json=fake, now_ist=PEAK_NOW,
        token="SECRET", sleep_between_apis=0.0, sleep_between_zones=0.0, verbose=False,
    )
    # Only 2 uncached zones collected -> 2 * 10 = 20 calls; cached zone untouched.
    assert len(result) == 3
    assert result[cached_id] == {"zone_id": cached_id, "cached": True}
    assert len(fake.calls) == 20


def test_token_never_leaks_into_artifact(tmp_path):
    art_path = _write_artifact(tmp_path, n=2)
    out_path = tmp_path / "obs.json"
    collect(
        artifact_path=art_path, output_path=out_path,
        top_n=2, explore_n=0, get_json=FakeApi(), now_ist=PEAK_NOW,
        token="SUPER_SECRET_KEY", sleep_between_apis=0.0, sleep_between_zones=0.0, verbose=False,
    )
    written = out_path.read_text(encoding="utf-8")
    assert "SUPER_SECRET_KEY" not in written


def test_incremental_save_after_each_zone(tmp_path):
    art_path = _write_artifact(tmp_path, n=2)
    out_path = tmp_path / "obs.json"
    collect(
        artifact_path=art_path, output_path=out_path,
        top_n=2, explore_n=0, get_json=FakeApi(), now_ist=PEAK_NOW,
        token="SECRET", sleep_between_apis=0.0, sleep_between_zones=0.0, verbose=False,
    )
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(on_disk) == 2
    for obs in on_disk.values():
        assert obs["method"] == "local_segment_v2"
