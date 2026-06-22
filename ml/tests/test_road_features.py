"""
Tests for the Task 8 road features + gap-filler seam.
==============================================================================

* road_geometry: free-flow speed -> road_class proxy; OSM stub raises;
* adjacency: budget-capped; driving-time k-NN over mocked distance-matrix calls;
* forecast v2: retrains with the two road-context features and reports
  Precision@10 old vs new (no improvement forced).

HTTP is mocked (no network). Forecast fixtures use valid H3 ids and synthetic,
CIS-independent daily counts.
"""

from __future__ import annotations

import json

import h3
import numpy as np
import pandas as pd
import pytest

from ml.enrichment import adjacency as adj
from ml.enrichment.adjacency import (
    BudgetExceededError,
    build_adjacency,
    candidate_indices,
    collect,
    estimate_adjacency_calls,
    neighbor_map,
    parse_matrix_row,
    select_zones,
)
from ml.enrichment.road_geometry import (
    MapMyIndiaRoadGeometry,
    OSMRoadGeometry,
    ROAD_CLASS_RANK,
    RoadGeometry,
    classify_road,
    road_size_proxy,
)


# ─── road_geometry ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("ffs, expected", [
    (55.0, "arterial"), (41.0, "arterial"),
    (40.0, "collector"), (30.0, "collector"), (20.0, "collector"),
    (19.0, "local"), (5.0, "local"),
    (None, "unknown"), (0.0, "unknown"), (float("nan"), "unknown"), (-3.0, "unknown"),
])
def test_classify_road(ffs, expected):
    assert classify_road(ffs) == expected


def test_road_size_proxy_ranks():
    assert road_size_proxy(55.0) == 3   # arterial
    assert road_size_proxy(30.0) == 2   # collector
    assert road_size_proxy(10.0) == 1   # local
    assert road_size_proxy(None) == 0   # unknown


def test_mapmyindia_provider_returns_valid_road_class():
    provider = MapMyIndiaRoadGeometry()
    geo = provider.geometry_for(lat=12.97, lon=77.59, free_flow_speed_kmph=35.0)
    assert isinstance(geo, RoadGeometry)
    assert geo.road_class == "collector"
    assert geo.road_size_proxy == ROAD_CLASS_RANK["collector"]
    assert geo.lane_count is None and geo.road_width_m is None  # MapMyIndia leaves the gap
    assert geo.source == "mapmyindia_free_flow_speed"


def test_osm_provider_is_a_documented_stub():
    with pytest.raises(NotImplementedError):
        OSMRoadGeometry().geometry_for(lat=12.97, lon=77.59, free_flow_speed_kmph=35.0)


# ─── adjacency ───────────────────────────────────────────────────────────────

class FakeMatrixApi:
    """Returns a distance-matrix whose durations are the haversine-like order of
    the passed points, so nearest-by-driving-time == nearest-by-coordinate."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, params, label):
        self.calls.append((url, dict(params), label))
        # Parse the coords from the URL: ".../driving/lon,lat;lon,lat;..."
        coords_str = url.rsplit("/", 1)[-1]
        pts = []
        for pair in coords_str.split(";"):
            lon, lat = pair.split(",")
            pts.append((float(lat), float(lon)))
        src = pts[0]
        row = [0.0]
        for (lat, lon) in pts[1:]:
            # crude planar distance in "seconds" (monotone in real distance)
            d = ((lat - src[0]) ** 2 + (lon - src[1]) ** 2) ** 0.5
            row.append(d * 100000.0)
        return {"results": {"code": "Ok", "durations": [row]}}


def _artifact(n=12):
    """Valid-H3 artifact with descending volume, spread out geographically."""
    art = {}
    for i in range(n):
        cell = h3.latlng_to_cell(12.95 + i * 0.01, 77.55 + i * 0.01, 9)
        art[cell] = {"all_day": {"lat": 12.95 + i * 0.01, "lon": 77.55 + i * 0.01,
                                 "total_records": (n - i) * 10, "congestion_impact": float(n - i)}}
    return art


def test_parse_matrix_row():
    data = {"results": {"code": "Ok", "durations": [[0.0, 12.0, 30.0]]}}
    assert parse_matrix_row(data) == [0.0, 12.0, 30.0]
    assert parse_matrix_row({"results": {"code": "NoRoute"}}) is None
    assert parse_matrix_row(None) is None


def test_estimate_calls_one_per_zone():
    assert estimate_adjacency_calls(60) == 60


def test_candidate_indices_are_nearest():
    zones = [(f"z{i}", 12.95 + i * 0.01, 77.55 + i * 0.01) for i in range(8)]
    # Zone 0's nearest candidates should be 1, 2, 3 (closest indices).
    cand = candidate_indices(zones, 0, max_candidates=3)
    assert cand == [1, 2, 3]


def test_build_adjacency_picks_k_nearest_by_driving_time():
    art = _artifact(12)
    zones = select_zones(art, top_n=12)
    fake = FakeMatrixApi()
    adjacency = build_adjacency(zones, fake, token="SECRET", k=6, max_candidates=10)
    assert len(adjacency) == 12
    for h3_id, entry in adjacency.items():
        assert len(entry["neighbors"]) <= 6
        # driving times are sorted ascending
        times = entry["driving_times_s"]
        assert times == sorted(times)
    # one matrix call per zone
    assert len([c for c in fake.calls if c[2] == "distance_matrix"]) == 12
    # token never leaks into the adjacency structure
    assert "SECRET" not in json.dumps(adjacency)


def test_collect_budget_cap_aborts(tmp_path):
    art = _artifact(12)
    p = tmp_path / "cis.json"
    p.write_text(json.dumps(art), encoding="utf-8")
    fake = FakeMatrixApi()
    with pytest.raises(BudgetExceededError):
        collect(artifact_path=p, output_path=tmp_path / "adj.json", top_n=12, budget=5,
                get_json=fake, token="SECRET", verbose=False)
    assert fake.calls == []  # refused before any call


def test_collect_writes_adjacency(tmp_path):
    art = _artifact(10)
    p = tmp_path / "cis.json"
    p.write_text(json.dumps(art), encoding="utf-8")
    out = tmp_path / "adj.json"
    report = collect(artifact_path=p, output_path=out, top_n=10, k=6, budget=50,
                     get_json=FakeMatrixApi(), token="SECRET",
                     sleep_between_calls=0.0, verbose=False)
    assert out.exists()
    assert report["k"] == 6 and report["n_zones"] == 10
    nm = neighbor_map(report)
    assert len(nm) == 10
    assert all(isinstance(v, list) for v in nm.values())


def test_neighbor_map_ignores_reserved_keys():
    report = {"zones": {"z1": {"neighbors": ["z2", "z3"]}, "_meta": {"x": 1}}}
    nm = neighbor_map(report)
    assert nm == {"z1": ["z2", "z3"]}


# ─── forecast v2 ─────────────────────────────────────────────────────────────

def _synthetic_daily(seed=0, n_zones=14):
    """Valid-H3 synthetic daily counts spanning Jan-Apr 2024 (so the split works)."""
    rng = np.random.default_rng(seed)
    cells = [h3.latlng_to_cell(12.95 + i * 0.01, 77.55 + i * 0.01, 9) for i in range(n_zones)]
    dates = pd.date_range("2024-01-01", "2024-04-15", freq="D")
    rows = []
    for zi, cell in enumerate(cells):
        base = 2 + zi % 5
        for d in dates:
            count = int(rng.poisson(base))
            rows.append({"h3_id": cell, "date": d, "violation_count": count})
    return pd.DataFrame(rows), cells


def test_forecast_v2_retrains_and_reports_old_vs_new(tmp_path):
    from ml.forecast.build_h3_forecast_v2 import FEATURES_V2, build_h3_forecast_v2

    daily, cells = _synthetic_daily(seed=1)
    # Adjacency among the synthetic zones (k=3 ring) + road speeds for some zones.
    adjacency = {"zones": {c: {"neighbors": [cells[(i + 1) % len(cells)], cells[(i + 2) % len(cells)]]}
                           for i, c in enumerate(cells)}}
    observations = {c: {"free_flow_speed_kmph": 15.0 + (i % 4) * 12.0} for i, c in enumerate(cells)}

    out = tmp_path / "forecasts_v2.json"
    artifact = build_h3_forecast_v2(
        daily=daily, adjacency=adjacency, observations=observations, out_path=out,
    )
    assert out.exists()
    assert artifact["features"] == FEATURES_V2
    assert "neighbor_spatial_lag" in artifact["features"]
    assert "road_size_proxy" in artifact["features"]
    m = artifact["metrics"]
    # Both old and new Precision@10 are reported (improvement NOT asserted).
    assert "precision_at_10" in m and "precision_at_10_baseline" in m
    assert 0.0 <= m["precision_at_10"] <= 1.0
    assert m["spatial_features_active"] is True
    assert m["road_proxy_active"] is True
    assert artifact["n_zones"] == 14


def test_forecast_v2_without_inputs_matches_baseline(tmp_path):
    """No adjacency/observations -> both new features are 0 -> v2 == v1 metrics."""
    from ml.forecast.build_h3_forecast_v2 import build_h3_forecast_v2

    daily, _ = _synthetic_daily(seed=2)
    out = tmp_path / "forecasts_v2.json"
    artifact = build_h3_forecast_v2(
        daily=daily, adjacency={}, observations={}, out_path=out,
    )
    m = artifact["metrics"]
    assert m["spatial_features_active"] is False
    assert m["road_proxy_active"] is False
    # With both spatial features identically 0, the model has the same usable
    # signal as the baseline -> equal held-out Precision@10 (honest "no change").
    assert m["precision_at_10"] == pytest.approx(m["precision_at_10_baseline"])
