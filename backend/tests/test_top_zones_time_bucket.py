"""
Tests for bucket-aware re-scoring/re-ranking of the served zone universe.
=========================================================================

``DataStore.top_zones(n, time_bucket)`` and ``DataStore.station_zones(station,
time_bucket)`` keep the served zone SET stable (no zone appears/disappears) but,
for a specific time bucket, RE-SCORE each zone's ``congestion_impact`` (+
``impact_band``) from the full CIS artifact and RE-RANK by it — so the map
markers / priority strip become time-aware in step with the heatmap.

Pinned behavior:
  * default / ``all_day`` returns the legacy enforcement-ranked slice UNCHANGED
    (existing simulate/game callers must be byte-for-byte stable);
  * a specific bucket re-scores congestion_impact and re-ranks by it;
  * a zone missing that bucket falls back to its ``all_day`` value (set stable);
  * enforcement ``risk_score`` is NEVER bucketed (time-stable by design);
  * the in-memory universe is not mutated (re-score returns copies).

These build a synthetic universe + artifact and install them directly on a
``DataStore`` (``loaded = True`` so ``ensure()`` won't reload the on-disk data),
mirroring the sibling DataStore tests. Values are illustrative.
"""

from __future__ import annotations

from backend.app.data_loader import DataStore

ALL_DAY = "all_day"
PEAK = "morning_peak"


def _zone(h3: str, risk: float, cis_all_day: float, station: str = "S") -> dict:
    """A served zone shaped like the universe build (carries the all_day CIS)."""
    return {
        "grid_cell_id": h3,
        "h3_id": h3,
        "grid_lat": 12.97,
        "grid_lon": 77.59,
        "risk_score": risk,
        "congestion_impact": cis_all_day,
        "impact_band": "MINIMAL",
        "station": station,
        "violation_count": 100,
    }


def _artifact_entry(cis: float, band: str | None = None) -> dict:
    e = {"congestion_impact": cis}
    if band is not None:
        e["impact_band"] = band
    return e


def _make_store() -> DataStore:
    """A universe of 3 zones ranked by risk_score, with a per-bucket artifact.

    risk order:  A(90) > B(80) > C(70)
    all_day CIS: A=10,  B=50,  C=30
    morning_peak CIS: A=80, B=20  (C has NO peak entry -> all_day fallback = 30)
    So peak re-ranking by CIS is A(80) > C(30) > B(20) — different from risk order.
    """
    store = DataStore()
    store.zones = [_zone("A", 90, 10.0), _zone("B", 80, 50.0), _zone("C", 70, 30.0)]
    store.zones_by_id = {z["grid_cell_id"]: z for z in store.zones}
    store.congestion = {
        "A": {ALL_DAY: _artifact_entry(10.0), PEAK: _artifact_entry(80.0)},  # band omitted -> computed
        "B": {ALL_DAY: _artifact_entry(50.0), PEAK: _artifact_entry(20.0, "MINIMAL")},
        "C": {ALL_DAY: _artifact_entry(30.0)},  # no peak entry -> all_day fallback
    }
    store.loaded = True
    return store


# ─── default / all_day is unchanged ──────────────────────────────────────────

def test_top_zones_default_is_legacy_all_day_order():
    store = _make_store()
    default = store.top_zones(3)
    all_day = store.top_zones(3, ALL_DAY)
    # Both return the legacy risk-ranked slice, identical and unchanged.
    assert [z["grid_cell_id"] for z in default] == ["A", "B", "C"]
    assert default == all_day
    assert [z["congestion_impact"] for z in default] == [10.0, 50.0, 30.0]


# ─── bucket re-scores + re-ranks by congestion_impact ────────────────────────

def test_top_zones_bucket_rescored_and_reranked():
    store = _make_store()
    peak = store.top_zones(3, PEAK)
    # Re-ranked by morning_peak CIS: A(80) > C(30 fallback) > B(20).
    assert [z["grid_cell_id"] for z in peak] == ["A", "C", "B"]
    assert [z["congestion_impact"] for z in peak] == [80.0, 30.0, 20.0]
    # Band recomputed where the artifact omitted it: CIS 80 -> SEVERE (51..75? no -> >75 CRITICAL).
    a = next(z for z in peak if z["grid_cell_id"] == "A")
    assert a["impact_band"] == "CRITICAL"  # _band(80) -> CRITICAL


def test_top_zones_bucket_keeps_risk_score_stable():
    store = _make_store()
    peak = {z["grid_cell_id"]: z for z in store.top_zones(3, PEAK)}
    # Enforcement priority is NOT bucketed — stays the all_day value.
    assert peak["A"]["risk_score"] == 90
    assert peak["B"]["risk_score"] == 80
    assert peak["C"]["risk_score"] == 70


def test_top_zones_does_not_mutate_universe():
    store = _make_store()
    store.top_zones(3, PEAK)
    # The in-memory universe still carries the all_day values (copies were re-scored).
    assert [z["congestion_impact"] for z in store.zones] == [10.0, 50.0, 30.0]


def test_top_zones_missing_bucket_falls_back_to_all_day():
    store = _make_store()
    # 'afternoon' exists for no zone -> every zone falls back to its all_day CIS,
    # so the result equals the all_day scores (re-ranked by them).
    aft = store.top_zones(3, "afternoon")
    by_id = {z["grid_cell_id"]: z["congestion_impact"] for z in aft}
    assert by_id == {"A": 10.0, "B": 50.0, "C": 30.0}
    # Ranked by CIS desc: B(50) > C(30) > A(10).
    assert [z["grid_cell_id"] for z in aft] == ["B", "C", "A"]


# ─── station_zones mirrors the same behavior ─────────────────────────────────

def test_station_zones_default_unchanged_bucket_reranks():
    store = _make_store()
    default = store.station_zones("S")
    assert [z["grid_cell_id"] for z in default] == ["A", "B", "C"]
    assert [z["congestion_impact"] for z in default] == [10.0, 50.0, 30.0]

    peak = store.station_zones("S", PEAK)
    assert [z["grid_cell_id"] for z in peak] == ["A", "C", "B"]
    assert [z["congestion_impact"] for z in peak] == [80.0, 30.0, 20.0]
    # risk_score stays stable.
    assert {z["grid_cell_id"]: z["risk_score"] for z in peak} == {"A": 90, "B": 80, "C": 70}
