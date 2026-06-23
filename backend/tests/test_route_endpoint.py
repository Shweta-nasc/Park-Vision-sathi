"""
Tests for the /route endpoint + route helpers (Route now feature).
===================================================================

The /route endpoint serves a DRIVABLE road-following polyline for the "Route
now" button with a strict cache-first, offline-safe contract:

  * CACHE HIT  -> the cached geometry + ``source: "cache"`` (no network);
  * MISS while offline / keyless / disabled -> ``{geometry: null, source: "none"}``
    with a 200 status (NEVER a 5xx, so the map falls back to a straight line);
  * dual-mount equivalence (bare path + ``/api`` prefix);
  * the pure helpers: deterministic cache key + GeoJSON ``[lng,lat]`` ->
    ``{lat,lon}`` parsing, with malformed/HTTP-error inputs degrading to None.

No test makes a real network call: cache-hit injects geometry, the miss tests
return before any HTTP call (disabled / no key), and the fetch-parsing tests
monkeypatch ``httpx.get`` with a fake response. All values are illustrative.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.data_loader import DataStore, store
from backend.app.main import app
from backend.app.routers import route as route_mod
from backend.app.routers.route import (
    fetch_route_geometry,
    route_cache_key,
    routing_enabled,
)

SAMPLE_GEOMETRY = [
    {"lat": 12.9716, "lon": 77.5946},
    {"lat": 12.9740, "lon": 77.5850},
    {"lat": 12.9773, "lon": 77.5750},
]

# A from→to pair used across the endpoint tests.
PARAMS = {"from_lat": 12.9716, "from_lon": 77.5946, "to_lat": 12.9773, "to_lon": 77.5750}


@pytest.fixture
def install_routes():
    """Install a route cache on the shared ``store`` and yield a TestClient maker.

    Snapshots/restores ``store.routes`` and ``store.loaded`` so the suite stays
    order-independent. The client is created WITHOUT its context manager so the
    app's startup ``store.load()`` never overwrites the injection.
    """
    saved = (store.routes, store.loaded)

    def _make(routes: dict) -> TestClient:
        store.routes = routes
        store.loaded = True
        return TestClient(app)

    try:
        yield _make
    finally:
        store.routes, store.loaded = saved


# ─── cache hit ───────────────────────────────────────────────────────────────

def test_route_cache_hit_returns_geometry(install_routes):
    key = route_cache_key(**PARAMS)
    client = install_routes({key: SAMPLE_GEOMETRY})
    body = client.get("/route", params=PARAMS).json()

    assert body["source"] == "cache"
    assert body["geometry"] == SAMPLE_GEOMETRY


def test_route_cache_hit_dual_mount_equivalent(install_routes):
    key = route_cache_key(**PARAMS)
    client = install_routes({key: SAMPLE_GEOMETRY})
    bare = client.get("/route", params=PARAMS)
    api = client.get("/api/route", params=PARAMS)
    assert bare.status_code == api.status_code == 200
    assert bare.json() == api.json()


def test_route_cache_hit_tolerates_nearby_coords(install_routes):
    """A click a few metres off the cached pair still hits (4-dp rounding)."""
    key = route_cache_key(**PARAMS)
    client = install_routes({key: SAMPLE_GEOMETRY})
    nudged = {k: v + 0.00001 for k, v in PARAMS.items()}  # ~1 m
    body = client.get("/route", params=nudged).json()
    assert body["source"] == "cache"
    assert body["geometry"] == SAMPLE_GEOMETRY


# ─── offline / disabled / keyless miss: graceful null (never 500) ─────────────

def test_route_miss_disabled_returns_null(install_routes, monkeypatch):
    monkeypatch.setenv("MAPPLS_STATIC_KEY", "dummy-key")
    monkeypatch.setenv("MAPPLS_ROUTING_DISABLED", "1")
    client = install_routes({})  # empty cache -> miss
    resp = client.get("/route", params=PARAMS)
    assert resp.status_code == 200  # never 5xx
    assert resp.json() == {"geometry": None, "source": "none"}


def test_route_miss_no_key_returns_null(install_routes, monkeypatch):
    monkeypatch.delenv("MAPPLS_STATIC_KEY", raising=False)
    monkeypatch.delenv("MAPPLS_ROUTING_DISABLED", raising=False)
    client = install_routes({})
    resp = client.get("/route", params=PARAMS)
    assert resp.status_code == 200
    assert resp.json() == {"geometry": None, "source": "none"}


def test_route_rejects_out_of_range_coords(install_routes):
    """Invalid lat/lon is a 422 validation error, not a 500."""
    client = install_routes({})
    resp = client.get("/route", params={**PARAMS, "from_lat": 999})
    assert resp.status_code == 422


# ─── routing_enabled toggle ──────────────────────────────────────────────────

def test_routing_enabled_requires_key_and_not_disabled(monkeypatch):
    monkeypatch.delenv("MAPPLS_ROUTING_DISABLED", raising=False)
    monkeypatch.setenv("MAPPLS_STATIC_KEY", "k")
    assert routing_enabled() is True

    monkeypatch.setenv("MAPPLS_ROUTING_DISABLED", "true")
    assert routing_enabled() is False

    monkeypatch.delenv("MAPPLS_ROUTING_DISABLED", raising=False)
    monkeypatch.delenv("MAPPLS_STATIC_KEY", raising=False)
    assert routing_enabled() is False


# ─── cache-key helper ────────────────────────────────────────────────────────

def test_route_cache_key_is_deterministic_and_rounded():
    a = route_cache_key(12.97161, 77.59462, 12.97734, 77.57501)
    b = route_cache_key(12.97162, 77.59463, 12.97733, 77.57502)  # within 4 dp
    assert a == b
    # Distinct destinations produce distinct keys.
    assert route_cache_key(12.97, 77.59, 12.98, 77.57) != route_cache_key(
        12.97, 77.59, 12.99, 77.57)


# ─── fetch parsing (monkeypatched httpx, no real network) ────────────────────

class _FakeResp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_route_geometry_parses_geojson(monkeypatch):
    payload = {"routes": [{"geometry": {"coordinates": [
        [77.5946, 12.9716], [77.5850, 12.9740], [77.5750, 12.9773]]}}]}
    monkeypatch.setattr(route_mod.httpx, "get", lambda *a, **k: _FakeResp(200, payload))
    geom = fetch_route_geometry(12.9716, 77.5946, 12.9773, 77.5750, "tok")
    assert geom == SAMPLE_GEOMETRY  # [lng,lat] -> {lat,lon}


def test_fetch_route_geometry_http_error_returns_none(monkeypatch):
    monkeypatch.setattr(route_mod.httpx, "get", lambda *a, **k: _FakeResp(401, {}))
    assert fetch_route_geometry(12.97, 77.59, 12.98, 77.57, "tok") is None


def test_fetch_route_geometry_empty_geometry_returns_none(monkeypatch):
    payload = {"routes": [{"geometry": {"coordinates": [[77.59, 12.97]]}}]}  # < 2 pts
    monkeypatch.setattr(route_mod.httpx, "get", lambda *a, **k: _FakeResp(200, payload))
    assert fetch_route_geometry(12.97, 77.59, 12.98, 77.57, "tok") is None


# ─── DataStore load() wiring ─────────────────────────────────────────────────

def test_datastore_loads_routes_cache_from_disk(tmp_path, monkeypatch):
    monkeypatch.delenv("CIS_ARTIFACT_PATH", raising=False)
    data_dir = tmp_path / "data"
    enriched = data_dir / "enriched"
    enriched.mkdir(parents=True)
    key = route_cache_key(**PARAMS)
    (enriched / "routes.json").write_text(json.dumps({key: SAMPLE_GEOMETRY}), encoding="utf-8")

    s = DataStore(data_dir=data_dir).load()
    assert s.routes.get(key) == SAMPLE_GEOMETRY


def test_datastore_routes_empty_when_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("CIS_ARTIFACT_PATH", raising=False)
    data_dir = tmp_path / "data"
    (data_dir / "enriched").mkdir(parents=True)
    s = DataStore(data_dir=data_dir).load()
    assert s.routes == {}
