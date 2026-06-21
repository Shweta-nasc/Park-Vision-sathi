"""
Integration tests for the CIS HTTP endpoints (tasks 7.1 / 7.2).
================================================================

Task 7.3 — integration tests for the endpoints.

Where the unit / property tests exercise the scoring core, the contract, and the
``DataStore`` accessors in isolation, this module drives the wired-up FastAPI
endpoints **end to end** through a ``TestClient`` against the real application
(``backend.app.main:app``). It proves the routers from tasks 7.1 (``risk.py``)
and 7.2 (``heatmap.py``) return the typed contract, that the Congestion Risk and
raw Violation Density layers carry genuinely different intensities, and that
unknown ids / unknown time buckets degrade gracefully.

**Validates: Requirements 8.3, 8.4, 8.6, 12.3, 14.4**

  * Requirement 8.3 — ``/heatmap?type=risk`` returns CIS values as point intensities.
  * Requirement 8.4 — ``/heatmap?type=raw`` returns violation counts as point intensities.
  * Requirement 8.6 — ``/risk/{zone_id}`` returns the ``CongestionBreakdown`` for the zone.
  * Requirement 12.3 — an unknown ``time_bucket`` falls back to the zone's ``all_day`` rollup.
  * Requirement 14.4 — an unknown ``zone_id`` yields a structured not-found (HTTP 404) response.

Req 8.5 (hotspots ranked by descending CIS) is already covered at the DataStore
layer by the task 6.3 property test; it is re-asserted here over the HTTP boundary.

Hermetic setup
--------------
The endpoints are served from the module-level ``DataStore`` singleton
(``backend.app.data_loader.store``) that every router imports. The canonical CIS
artifact is materialized offline and is NOT present in the test environment, so
to make these tests hermetic a small in-memory artifact is installed directly on
the shared ``store`` before each test and the original values are restored in
teardown — keeping the suite order-independent (no other test sees the fixture
artifact). The ``TestClient`` is created WITHOUT its context manager on purpose:
that skips the app's startup ``store.load()`` so it cannot clobber (or be clobbered
by) the injected artifact, and ``store.loaded = True`` makes every accessor's
``ensure()`` guard a no-op so it serves the injected ``store.congestion`` as-is.

The fixture artifact carries three zones whose CIS ranking and violation-count
ranking are deliberate *reversals* of each other (a high-impact/low-volume zone, a
mid zone, and a low-impact/high-volume zone), so the two heatmap layers must order
the zones differently — the load-bearing "density != impact" thesis. One zone also
carries an ``afternoon`` bucket but no ``morning_peak`` bucket, so requesting the
missing bucket exercises the ``all_day`` fallback (Requirement 12.3).

Framework: pytest with FastAPI's ``TestClient`` (Starlette/httpx). Example-based,
not Hypothesis — this validates endpoint wiring and the serialized contract.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.data_loader import store
from backend.app.main import app
from backend.app.models import (
    CongestionBreakdown,
    CongestionHeatmapResponse,
    HotspotItem,
)

ALL_DAY = "all_day"

# Canonical component weights (a partition of unity), echoed on every breakdown.
# Declared locally so the test stays independent of the scoring core.
_CANONICAL_WEIGHTS = {
    "lane_blockage": 0.30,
    "intersection_impact": 0.25,
    "traffic_degradation": 0.25,
    "access_blockage": 0.10,
    "vehicle_size": 0.10,
}

# ─── Fixture zones: CIS ranking and count ranking are exact reversals ────────
#
# h3-like ids (the models/accessors key by the string; H3 format is irrelevant).
# CIS and total_records are chosen so the two layers' orderings diverge:
#   CIS   desc -> HIGH_IMPACT (90) > MID (55) > HIGH_VOLUME (20)
#   count desc -> HIGH_VOLUME (1000) > MID (300) > HIGH_IMPACT (5)
ZONE_HIGH_IMPACT = "8960145b483ffff"   # disruptive junction: low volume, high CIS
ZONE_MID = "8960145b487ffff"           # mid zone; also carries an `afternoon` bucket
ZONE_HIGH_VOLUME = "8960145b48bffff"   # quiet street: high volume, low CIS

# Expected all_day CIS / counts per zone.
CIS_ALL_DAY = {ZONE_HIGH_IMPACT: 90.0, ZONE_MID: 55.0, ZONE_HIGH_VOLUME: 20.0}
COUNT_ALL_DAY = {ZONE_HIGH_IMPACT: 5, ZONE_MID: 300, ZONE_HIGH_VOLUME: 1000}

# ZONE_MID's afternoon bucket (distinct from its all_day so the fallback is provable).
MID_AFTERNOON_CIS = 70.0
MID_AFTERNOON_COUNT = 120

# A zone id guaranteed absent from the fixture (and not a `/risk/...` sub-route).
UNKNOWN_ZONE = "deadbeefdeadbeef0000"

# Descending-CIS / descending-count orderings the accessors must produce.
EXPECTED_CIS_ORDER = [ZONE_HIGH_IMPACT, ZONE_MID, ZONE_HIGH_VOLUME]
EXPECTED_COUNT_ORDER = [ZONE_HIGH_VOLUME, ZONE_MID, ZONE_HIGH_IMPACT]


def _band(score: float) -> str:
    """Right-closed impact band (matches data_loader._band / impact_score thresholds)."""
    if score <= 25:
        return "MINIMAL"
    if score <= 50:
        return "MODERATE"
    if score <= 75:
        return "SEVERE"
    return "CRITICAL"


def _breakdown(
    h3_id: str,
    cis: float,
    total_records: int,
    *,
    lat: float,
    lon: float,
    time_bucket: str = ALL_DAY,
    station: str | None = None,
    top_violations: tuple[str, ...] = (),
    lane_hours: float = 0.0,
    ratio: float | None = None,
    traffic_degradation: float = 0.5,
    defaulted: bool = True,
) -> dict:
    """Build one artifact breakdown dict in the ``CongestionBreakdown`` contract shape.

    Carries every field the offline builder serializes (``model_dump()`` of a
    ``CongestionBreakdown`` with ``lat``/``lon`` attached), so ``/risk/{zone_id}``
    can validate it via ``CongestionBreakdown.model_validate(...)``. ``cis`` and
    ``total_records`` are supplied independently (the contract does not recompute
    CIS from the components), which is what lets the two map layers diverge. The
    component values are fixed, valid placeholders in [0, 1]; ``impact_band`` is
    derived from ``cis`` so the breakdown is internally consistent.
    """
    return {
        "zone_id": h3_id,
        "h3_id": h3_id,
        "time_bucket": time_bucket,
        "lat": lat,
        "lon": lon,
        "congestion_impact": cis,
        "impact_band": _band(cis),
        "components": {
            "lane_blockage": 0.5,
            "intersection_impact": 0.5,
            "traffic_degradation": traffic_degradation,
            "access_blockage": 0.4,
            "vehicle_size": 0.3,
            "severity": 0.45,
        },
        "weights": dict(_CANONICAL_WEIGHTS),
        "estimated_lane_hours_blocked": lane_hours,
        "total_records": total_records,
        "top_violations": list(top_violations),
        "station": station,
        "junction": None,
        "mappls_travel_time_ratio": ratio,
        "is_traffic_degradation_defaulted": defaulted,
        "calibrated_impact": None,
    }


def _fixture_artifact() -> dict[str, dict[str, dict]]:
    """Assemble the ``{h3_id: {time_bucket: breakdown}}`` fixture artifact.

    Three zones with divergent CIS-vs-count rankings; ZONE_MID additionally carries
    an ``afternoon`` bucket but deliberately NO ``morning_peak`` bucket, so a request
    for ``morning_peak`` must fall back to its ``all_day`` rollup (Requirement 12.3).
    ZONE_HIGH_IMPACT uses the *measured* MapMyIndia branch (ratio present, flag
    False); the others use the deterministic defaulted branch (flag True).
    """
    return {
        ZONE_HIGH_IMPACT: {
            ALL_DAY: _breakdown(
                ZONE_HIGH_IMPACT, CIS_ALL_DAY[ZONE_HIGH_IMPACT],
                COUNT_ALL_DAY[ZONE_HIGH_IMPACT],
                lat=12.9716, lon=77.5946, station="Major Junction",
                top_violations=("PARKING IN A MAIN ROAD",), lane_hours=42.0,
                ratio=1.8, traffic_degradation=0.4, defaulted=False,
            ),
        },
        ZONE_MID: {
            ALL_DAY: _breakdown(
                ZONE_MID, CIS_ALL_DAY[ZONE_MID], COUNT_ALL_DAY[ZONE_MID],
                lat=12.9352, lon=77.6245, station="Midtown",
                top_violations=("DOUBLE PARKING",), lane_hours=18.0,
            ),
            "afternoon": _breakdown(
                ZONE_MID, MID_AFTERNOON_CIS, MID_AFTERNOON_COUNT,
                time_bucket="afternoon", lat=12.9352, lon=77.6245, station="Midtown",
                top_violations=("DOUBLE PARKING",), lane_hours=9.0,
            ),
        },
        ZONE_HIGH_VOLUME: {
            ALL_DAY: _breakdown(
                ZONE_HIGH_VOLUME, CIS_ALL_DAY[ZONE_HIGH_VOLUME],
                COUNT_ALL_DAY[ZONE_HIGH_VOLUME],
                lat=12.9698, lon=77.7500, station="Quiet Street",
                top_violations=("PARKING ON FOOTPATH",), lane_hours=5.0,
            ),
        },
    }


def _install_artifact(artifact: dict):
    """Install ``artifact`` on the shared ``store`` and return the saved originals.

    Forces ``loaded = True`` so the accessors' ``ensure()`` does NOT call ``load()``
    (which would read the committed ``data/`` artifacts and clobber the injection).
    """
    saved = (store.congestion, store.loaded)
    store.congestion = artifact
    store.loaded = True
    return saved


def _restore(saved):
    """Restore ``store.congestion`` / ``store.loaded`` so the suite stays order-independent."""
    store.congestion, store.loaded = saved


@pytest.fixture
def cis_client():
    """A ``TestClient`` serving the fixture CIS artifact from the shared ``store``.

    The artifact is installed before the test and the original store state is
    restored afterwards (teardown), so no other test is affected. The client is
    created without its context manager so the app's startup ``store.load()`` never
    runs and cannot overwrite the injected artifact.
    """
    saved = _install_artifact(_fixture_artifact())
    try:
        yield TestClient(app)
    finally:
        _restore(saved)


@pytest.fixture
def empty_cis_client():
    """A ``TestClient`` serving an EMPTY CIS artifact (the un-materialized case).

    Pins the designed graceful, offline-safe behavior when no artifact exists.
    """
    saved = _install_artifact({})
    try:
        yield TestClient(app)
    finally:
        _restore(saved)


# ─── /risk/{zone_id}: full breakdown validates + matches the fixture (Req 8.6) ─

def test_risk_zone_detail_validates_against_contract_and_matches_fixture(cis_client):
    """``GET /risk/{zone_id}`` returns HTTP 200 and a body that validates via
    ``CongestionBreakdown.model_validate(...)`` with fields matching the fixture.

    Validates: Requirement 8.6.
    """
    resp = cis_client.get(f"/risk/{ZONE_HIGH_IMPACT}")
    assert resp.status_code == 200

    model = CongestionBreakdown.model_validate(resp.json())
    assert model.zone_id == ZONE_HIGH_IMPACT
    assert model.h3_id == ZONE_HIGH_IMPACT
    assert model.time_bucket == ALL_DAY
    assert model.congestion_impact == CIS_ALL_DAY[ZONE_HIGH_IMPACT]
    assert model.impact_band == "CRITICAL"
    assert model.total_records == COUNT_ALL_DAY[ZONE_HIGH_IMPACT]
    assert model.station == "Major Junction"
    assert model.estimated_lane_hours_blocked == 42.0
    assert model.top_violations == ["PARKING IN A MAIN ROAD"]
    # Measured MapMyIndia branch passed through faithfully.
    assert model.mappls_travel_time_ratio == 1.8
    assert model.is_traffic_degradation_defaulted is False
    assert model.components.traffic_degradation == 0.4
    # The echoed weights are a partition of unity (the contract validator enforces it).
    assert abs(sum(model.weights.values()) - 1.0) < 1e-9


def test_risk_zone_detail_default_bucket_is_all_day(cis_client):
    """With no ``time_bucket`` query param, ``/risk/{zone_id}`` returns the
    ``all_day`` rollup (Requirement 12.4, exercised over HTTP)."""
    resp = cis_client.get(f"/risk/{ZONE_MID}")
    assert resp.status_code == 200
    model = CongestionBreakdown.model_validate(resp.json())
    assert model.time_bucket == ALL_DAY
    assert model.congestion_impact == CIS_ALL_DAY[ZONE_MID]


# ─── /risk/{zone_id}?time_bucket=...: all_day fallback (Req 12.3) ─────────────

def test_risk_unknown_bucket_falls_back_to_all_day(cis_client):
    """A ``time_bucket`` the zone does not have falls back to its ``all_day`` rollup.

    ZONE_MID carries ``all_day`` + ``afternoon`` but NOT ``morning_peak``; requesting
    ``morning_peak`` must return the ``all_day`` breakdown (CIS 55), NOT the
    ``afternoon`` one (CIS 70) — proving the fallback targets ``all_day`` specifically.

    Validates: Requirement 12.3.
    """
    resp = cis_client.get(f"/risk/{ZONE_MID}", params={"time_bucket": "morning_peak"})
    assert resp.status_code == 200

    model = CongestionBreakdown.model_validate(resp.json())
    assert model.time_bucket == ALL_DAY, "missing bucket should fall back to all_day"
    assert model.congestion_impact == CIS_ALL_DAY[ZONE_MID]
    assert model.congestion_impact != MID_AFTERNOON_CIS


def test_risk_present_bucket_returns_that_bucket(cis_client):
    """A ``time_bucket`` the zone DOES have is returned as-is (no fallback).

    Complements the fallback test: requesting ZONE_MID's ``afternoon`` bucket
    returns the afternoon breakdown (CIS 70), confirming the fallback only triggers
    for a genuinely missing bucket.

    Validates: Requirement 12.3.
    """
    resp = cis_client.get(f"/risk/{ZONE_MID}", params={"time_bucket": "afternoon"})
    assert resp.status_code == 200

    model = CongestionBreakdown.model_validate(resp.json())
    assert model.time_bucket == "afternoon"
    assert model.congestion_impact == MID_AFTERNOON_CIS
    assert model.total_records == MID_AFTERNOON_COUNT


# ─── /risk/{unknown_zone}: structured 404 (Req 14.4) ─────────────────────────

def test_risk_unknown_zone_returns_structured_404(cis_client):
    """An unknown ``zone_id`` yields HTTP 404 with the structured not-found detail.

    Validates: Requirement 14.4.
    """
    resp = cis_client.get(f"/risk/{UNKNOWN_ZONE}")
    assert resp.status_code == 404

    detail = resp.json()["detail"]
    assert detail["error"] == f"No data for zone {UNKNOWN_ZONE}"
    assert detail["zone_id"] == UNKNOWN_ZONE


# ─── /hotspots: list validates + descending-CIS ranking (Req 8.5 over HTTP) ──

def test_hotspots_validate_and_ranked_by_descending_cis(cis_client):
    """``GET /hotspots`` returns HTTP 200 and a list that validates via
    ``HotspotItem``, ordered by descending CIS with 1-based ranks. Re-asserts
    Req 8.5 over the HTTP boundary (covered at the DataStore layer in task 6.3).

    Validates: Requirement 8.5.
    """
    resp = cis_client.get("/hotspots")
    assert resp.status_code == 200

    items = [HotspotItem.model_validate(x) for x in resp.json()]
    assert [i.h3_id for i in items] == EXPECTED_CIS_ORDER

    cis_sequence = [i.congestion_impact for i in items]
    assert cis_sequence == sorted(cis_sequence, reverse=True)
    assert [i.rank for i in items] == [1, 2, 3]

    # violation_count is sourced from the zone's raw count (total_records), distinct
    # from the CIS that drives the ranking.
    by_id = {i.h3_id: i for i in items}
    assert by_id[ZONE_HIGH_IMPACT].violation_count == COUNT_ALL_DAY[ZONE_HIGH_IMPACT]
    assert by_id[ZONE_HIGH_VOLUME].violation_count == COUNT_ALL_DAY[ZONE_HIGH_VOLUME]


# ─── /heatmap: risk == CIS, raw == counts, orderings DIFFER (Req 8.3, 8.4) ───

def test_heatmap_risk_layer_intensities_equal_cis(cis_client):
    """``GET /heatmap?type=risk`` validates via ``CongestionHeatmapResponse`` and
    every point intensity equals the zone's CIS.

    Validates: Requirement 8.3.
    """
    resp = cis_client.get("/heatmap", params={"type": "risk"})
    assert resp.status_code == 200

    body = CongestionHeatmapResponse.model_validate(resp.json())
    assert body.layer == "risk"
    intensity_by_zone = {p.h3_id: p.intensity for p in body.points}
    assert intensity_by_zone == CIS_ALL_DAY
    assert body.max_intensity == max(CIS_ALL_DAY.values())
    assert body.min_intensity == min(CIS_ALL_DAY.values())


def test_heatmap_raw_layer_intensities_equal_counts(cis_client):
    """``GET /heatmap?type=raw`` validates via ``CongestionHeatmapResponse`` and
    every point intensity equals the zone's raw violation count.

    Validates: Requirement 8.4.
    """
    resp = cis_client.get("/heatmap", params={"type": "raw"})
    assert resp.status_code == 200

    body = CongestionHeatmapResponse.model_validate(resp.json())
    assert body.layer == "raw"
    intensity_by_zone = {p.h3_id: p.intensity for p in body.points}
    assert intensity_by_zone == {z: float(c) for z, c in COUNT_ALL_DAY.items()}
    assert body.max_intensity == float(max(COUNT_ALL_DAY.values()))


def test_heatmap_risk_and_raw_layer_orderings_differ(cis_client):
    """The Congestion Risk (CIS) and Violation Density (count) layers order the
    same zones DIFFERENTLY — the "density != impact" thesis, asserted over HTTP.

    Validates: Requirements 8.3, 8.4.
    """
    risk = CongestionHeatmapResponse.model_validate(
        cis_client.get("/heatmap", params={"type": "risk"}).json()
    )
    raw = CongestionHeatmapResponse.model_validate(
        cis_client.get("/heatmap", params={"type": "raw"}).json()
    )

    risk_order = [p.h3_id for p in risk.points]
    raw_order = [p.h3_id for p in raw.points]

    assert risk_order == EXPECTED_CIS_ORDER
    assert raw_order == EXPECTED_COUNT_ORDER
    assert risk_order != raw_order, "the two layers must order the zones differently"


# ─── Dual-path: bare path AND /api-prefixed path (main.py mounts both) ───────

def test_dual_path_bare_and_api_prefixed_are_equivalent(cis_client):
    """Endpoints are mounted twice (bare + ``/api``); both paths return identical
    payloads. Exercises the dual-path wiring for ``/risk/{zone_id}`` and ``/hotspots``.
    """
    bare_detail = cis_client.get(f"/risk/{ZONE_HIGH_IMPACT}")
    api_detail = cis_client.get(f"/api/risk/{ZONE_HIGH_IMPACT}")
    assert bare_detail.status_code == api_detail.status_code == 200
    assert bare_detail.json() == api_detail.json()

    bare_hot = cis_client.get("/hotspots")
    api_hot = cis_client.get("/api/hotspots")
    assert bare_hot.status_code == api_hot.status_code == 200
    assert bare_hot.json() == api_hot.json()

    bare_heat = cis_client.get("/heatmap", params={"type": "risk"})
    api_heat = cis_client.get("/api/heatmap", params={"type": "risk"})
    assert bare_heat.status_code == api_heat.status_code == 200
    assert bare_heat.json() == api_heat.json()


# ─── Empty artifact: graceful, offline-safe behavior (optional) ──────────────

def test_empty_artifact_endpoints_degrade_gracefully(empty_cis_client):
    """With an EMPTY CIS artifact: ``/hotspots`` -> ``200 []``, ``/risk/{id}`` -> 404,
    and ``/heatmap?type=risk`` -> a valid response with no points (min/max 0.0).

    Pins the designed graceful behavior when the artifact is not yet materialized.
    """
    hotspots = empty_cis_client.get("/hotspots")
    assert hotspots.status_code == 200
    assert hotspots.json() == []

    detail = empty_cis_client.get(f"/risk/{ZONE_HIGH_IMPACT}")
    assert detail.status_code == 404
    assert detail.json()["detail"]["zone_id"] == ZONE_HIGH_IMPACT

    heatmap = empty_cis_client.get("/heatmap", params={"type": "risk"})
    assert heatmap.status_code == 200
    body = CongestionHeatmapResponse.model_validate(heatmap.json())
    assert body.points == []
    assert body.min_intensity == 0.0
    assert body.max_intensity == 0.0
