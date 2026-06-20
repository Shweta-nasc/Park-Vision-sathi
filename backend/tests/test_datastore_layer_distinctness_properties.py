"""
Property-based tests for the two map layers being genuinely distinct.
=====================================================================

Task 6.3 — layer distinctness and ranking.

Covers one correctness property from the design's "Correctness Properties"
section, exercising the ``DataStore`` serving accessors added in task 6.2
(``backend.app.data_loader``):

  * **Property 12 — The two map layers are genuinely distinct:** for any CIS
    artifact, the Congestion Risk layer (:meth:`DataStore.congestion_points`)
    intensity equals the zone's ``congestion_impact`` (CIS) and the Violation
    Density layer (:meth:`DataStore.violation_density_points`) intensity equals
    the zone's raw violation count (``total_records``). CIS is NOT aliased to the
    count — the two intensities are read from *different* artifact fields — so the
    Congestion Risk ranking (:meth:`DataStore.congestion_hotspots`, descending
    CIS) can differ from the Violation Density ranking (descending count). This is
    the load-bearing "density != impact" thesis of the whole feature.

**Validates: Requirements 8.3, 8.4, 8.5, 10.1, 10.2**

  * Requirement 8.3 — the risk layer returns CIS values as point intensities.
  * Requirement 8.4 — the raw layer returns violation counts as point intensities.
  * Requirement 8.5 — hotspots are returned ranked in descending order of CIS.
  * Requirement 10.1 — ``congestion_impact`` is maintained as a value distinct
    from the (count-driven) violation density.
  * Requirement 10.2 — the Congestion Risk layer uses ``congestion_impact``, not
    the violation count.

Framework: Hypothesis (per the design's "Property Test Library: Hypothesis"),
with a minimum of 100 examples per property (configured to 200 here).

Approach
--------
Per the task, the test builds a *synthetic* in-memory CIS artifact
(``{h3_id: {time_bucket: breakdown}}``) directly with Hypothesis — it does NOT
run the offline scorer. Each generated breakdown carries exactly the fields the
accessors read (``zone_id`` / ``h3_id`` / ``lat`` / ``lon`` / ``congestion_impact``
/ ``impact_band`` / ``total_records`` / ``top_violations`` / ``station`` /
``estimated_lane_hours_blocked``) under an ``all_day`` bucket. Crucially,
``congestion_impact`` and ``total_records`` are drawn INDEPENDENTLY, so the two
layer orderings are free to diverge — and a targeted ``@example`` constructs an
explicit inversion (one high-count/low-CIS zone vs one low-count/high-CIS zone)
that guarantees the divergent case is exercised.

The synthetic artifact is installed straight onto a ``DataStore`` instance
(``store.congestion = artifact``; ``store.loaded = True`` so ``ensure()`` does not
reload from the committed ``data/`` dir and clobber it). A companion
example-based test instead writes the artifact to a temp
``processed/zone_congestion_impact.json`` and loads it through the real
``DataStore(data_dir=...).load()`` path, proving the distinctness survives the
actual on-disk load.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from hypothesis import example, given, settings
from hypothesis import strategies as st

from backend.app.data_loader import DataStore, _band

ALL_DAY = "all_day"


# ─── Synthetic zone spec + artifact assembly ─────────────────────────────────

@dataclass(frozen=True)
class _ZoneSpec:
    """A synthetic zone: its CIS and its violation count are INDEPENDENT.

    These two numbers are the whole point of Property 12 — ``congestion_impact``
    feeds the Congestion Risk layer, ``total_records`` feeds the Violation Density
    layer, and they are generated independently so the two layers' rankings can
    disagree.
    """

    h3_id: str
    congestion_impact: float        # CIS in [0, 100]  -> risk-layer intensity
    total_records: int              # raw violation count -> density-layer intensity
    lat: float
    lon: float
    station: str | None
    top_violations: tuple[str, ...]
    estimated_lane_hours_blocked: float


def _breakdown(spec: _ZoneSpec, time_bucket: str = ALL_DAY) -> dict:
    """Serialize one ``_ZoneSpec`` into the artifact breakdown shape the accessors read.

    Carries exactly the keys ``congestion_points`` / ``violation_density_points`` /
    ``congestion_hotspots`` consume. ``impact_band`` is derived from the CIS via the
    same right-closed thresholds the loader uses (``_band``), so the synthetic
    breakdown is internally consistent without running the scorer.
    """
    return {
        "zone_id": spec.h3_id,
        "h3_id": spec.h3_id,
        "time_bucket": time_bucket,
        "lat": spec.lat,
        "lon": spec.lon,
        "congestion_impact": spec.congestion_impact,
        "impact_band": _band(spec.congestion_impact),
        "total_records": spec.total_records,
        "top_violations": list(spec.top_violations),
        "station": spec.station,
        "estimated_lane_hours_blocked": spec.estimated_lane_hours_blocked,
    }


def _artifact(specs: list[_ZoneSpec]) -> dict[str, dict[str, dict]]:
    """Assemble ``{h3_id: {"all_day": breakdown}}`` from a list of zone specs."""
    return {spec.h3_id: {ALL_DAY: _breakdown(spec)} for spec in specs}


def _store_with_artifact(artifact: dict) -> DataStore:
    """Return a ``DataStore`` serving ``artifact`` directly from memory.

    ``store.loaded`` is forced True so the accessors' ``ensure()`` guard does NOT
    call ``load()`` — which would read the committed ``data/processed/...`` artifact
    and overwrite the synthetic one we just installed. The accessors under test read
    only ``self.congestion``, so this isolates them from every other artifact.
    """
    store = DataStore()
    store.congestion = artifact
    store.loaded = True
    return store


# ─── Hypothesis strategies ───────────────────────────────────────────────────

# H3-like keys (hex tokens). Real H3 format is irrelevant to the accessors (they
# key by the string); uniqueness is what matters for stable ranking/tie-breaks.
_h3_ids = st.text(alphabet="0123456789abcdef", min_size=4, max_size=15)

_zone_spec = st.builds(
    _ZoneSpec,
    h3_id=_h3_ids,
    # CIS and count are drawn from SEPARATE strategies (independent) so the two
    # layer orderings are free to diverge.
    congestion_impact=st.floats(0.0, 100.0, allow_nan=False, allow_infinity=False),
    total_records=st.integers(min_value=0, max_value=1_000_000),
    lat=st.floats(-90.0, 90.0, allow_nan=False, allow_infinity=False),
    lon=st.floats(-180.0, 180.0, allow_nan=False, allow_infinity=False),
    station=st.one_of(st.none(), st.text(max_size=12)),
    top_violations=st.lists(st.text(min_size=1, max_size=10), max_size=4).map(tuple),
    estimated_lane_hours_blocked=st.floats(
        0.0, 1_000_000.0, allow_nan=False, allow_infinity=False
    ),
)

# At least two distinct zones, so the two rankings have something to disagree about.
_zone_spec_lists = st.lists(_zone_spec, min_size=2, max_size=8, unique_by=lambda s: s.h3_id)


# ─── Targeted explicit examples (pin the distinct + the agreeing cases) ──────

# The inversion that proves "density != impact": a HIGH-volume / LOW-impact zone
# (a quiet street with thousands of footpath violations) vs a LOW-volume /
# HIGH-impact zone (a disruptive junction with a handful of main-road blockages).
# Ranking by CIS and ranking by count are exact REVERSALS of each other here.
_HIGH_VOLUME_ZONE = "a0a0a0"   # 1000 records, CIS 10  -> tops the density layer
_HIGH_IMPACT_ZONE = "b1b1b1"   # 5 records,    CIS 90  -> tops the risk layer
_INVERSION_SPECS = [
    _ZoneSpec(
        h3_id=_HIGH_VOLUME_ZONE,
        congestion_impact=10.0,
        total_records=1000,
        lat=12.9716,
        lon=77.5946,
        station="Quiet Street",
        top_violations=("PARKING ON FOOTPATH",),
        estimated_lane_hours_blocked=5.0,
    ),
    _ZoneSpec(
        h3_id=_HIGH_IMPACT_ZONE,
        congestion_impact=90.0,
        total_records=5,
        lat=12.9352,
        lon=77.6245,
        station="Major Junction",
        top_violations=("PARKING IN A MAIN ROAD",),
        estimated_lane_hours_blocked=42.0,
    ),
]

# A case where the two rankings AGREE (CIS and count both rise together), so the
# property must NOT over-assert divergence when the orders happen to coincide.
_AGREEING_SPECS = [
    _ZoneSpec("c2c2c2", 20.0, 50, 12.97, 77.59, "Low both", ("WRONG PARKING",), 2.0),
    _ZoneSpec("d3d3d3", 80.0, 900, 12.93, 77.62, "High both", ("DOUBLE PARKING",), 30.0),
]


# ─── Property 12: the two layers are distinct and independently sourced ──────

@settings(max_examples=200, deadline=None)
@given(specs=_zone_spec_lists)
@example(specs=_INVERSION_SPECS)
@example(specs=_AGREEING_SPECS)
def test_property_12_layers_are_distinct(specs):
    """Property 12: the risk layer tracks CIS, the density layer tracks the count,
    the two are sourced from different fields (not aliased), and hotspots rank by
    descending CIS.

    Validates: Requirements 8.3, 8.4, 8.5, 10.1, 10.2.
    """
    store = _store_with_artifact(_artifact(specs))
    expected = {s.h3_id: s for s in specs}

    risk_points = store.congestion_points(ALL_DAY)
    raw_points = store.violation_density_points(ALL_DAY)
    hotspots = store.congestion_hotspots(ALL_DAY)

    # Every layer covers the same zone universe (one point/row per zone).
    assert {p["h3_id"] for p in risk_points} == set(expected)
    assert {p["h3_id"] for p in raw_points} == set(expected)
    assert {h["h3_id"] for h in hotspots} == set(expected)
    assert len(risk_points) == len(raw_points) == len(hotspots) == len(expected)

    # Req 8.3 / 10.2: the Congestion Risk layer intensity IS the zone's CIS (the
    # accessor rounds to 3 dp), NOT the violation count.
    risk_intensity = {p["h3_id"]: p["intensity"] for p in risk_points}
    # Req 8.4: the Violation Density layer intensity IS the zone's raw count.
    raw_intensity = {p["h3_id"]: p["intensity"] for p in raw_points}
    for zid, spec in expected.items():
        assert risk_intensity[zid] == round(spec.congestion_impact, 3), (
            "risk-layer intensity must equal CIS"
        )
        assert raw_intensity[zid] == float(spec.total_records), (
            "density-layer intensity must equal the violation count"
        )

    # Req 10.1 / 10.2: the two layers are sourced INDEPENDENTLY — the risk layer
    # tracks CIS and the density layer tracks the count, per zone. (We do NOT
    # require them to be numerically unequal; we require each to track its own
    # field, which is what "not aliased" means.)
    for zid, spec in expected.items():
        assert risk_intensity[zid] == round(spec.congestion_impact, 3)
        assert raw_intensity[zid] == float(spec.total_records)

    # Req 8.5: hotspots are ranked in DESCENDING congestion impact.
    cis_sequence = [h["congestion_impact"] for h in hotspots]
    assert cis_sequence == sorted(cis_sequence, reverse=True)
    # The accessor's exact order is the canonical (-CIS, h3_id) sort, and each
    # hotspot surfaces the CIS and the count from their distinct source fields.
    expected_cis_order = [
        s.h3_id for s in sorted(specs, key=lambda s: (-s.congestion_impact, s.h3_id))
    ]
    assert [h["h3_id"] for h in hotspots] == expected_cis_order
    for h in hotspots:
        assert h["congestion_impact"] == expected[h["h3_id"]].congestion_impact
        assert h["violation_count"] == expected[h["h3_id"]].total_records

    # The density layer's order is the canonical (-count, h3_id) sort.
    cis_order = [h["h3_id"] for h in hotspots]
    count_order = [p["h3_id"] for p in raw_points]
    expected_count_order = [
        s.h3_id for s in sorted(specs, key=lambda s: (-s.total_records, s.h3_id))
    ]
    assert count_order == expected_count_order

    # Distinctness made explicit: whenever the CIS ranking and the count ranking
    # disagree, the two layer orderings the accessors produce ALSO disagree — only
    # possible because CIS is not aliased to the count. (When they happen to agree,
    # e.g. the _AGREEING_SPECS example, we correctly assert nothing here.)
    if expected_cis_order != expected_count_order:
        assert cis_order != count_order


# ─── Explicit inversion: the "density != impact" thesis, stated plainly ──────

def test_inversion_density_and_impact_disagree_on_the_worst_zone():
    """A high-volume/low-impact zone tops the density layer while a
    low-volume/high-impact zone tops the risk layer — the two layers disagree on
    the worst zone, which is only possible because CIS is not the violation count.

    Validates: Requirements 8.3, 8.4, 8.5, 10.1, 10.2.
    """
    store = _store_with_artifact(_artifact(_INVERSION_SPECS))

    risk_top = store.congestion_points(ALL_DAY)[0]["h3_id"]
    raw_top = store.violation_density_points(ALL_DAY)[0]["h3_id"]
    hotspot_top = store.congestion_hotspots(ALL_DAY)[0]["h3_id"]

    # Density layer's worst zone = the high-VOLUME one.
    assert raw_top == _HIGH_VOLUME_ZONE
    # Congestion Risk layer's (and hotspot ranking's) worst zone = the high-IMPACT one.
    assert risk_top == _HIGH_IMPACT_ZONE
    assert hotspot_top == _HIGH_IMPACT_ZONE
    # They disagree — the heart of the two-layer thesis (Req 10.1).
    assert raw_top != risk_top

    # And the intensities are read from the distinct fields (Req 8.3, 8.4).
    risk_intensity = {p["h3_id"]: p["intensity"] for p in store.congestion_points(ALL_DAY)}
    raw_intensity = {p["h3_id"]: p["intensity"] for p in store.violation_density_points(ALL_DAY)}
    assert risk_intensity[_HIGH_IMPACT_ZONE] == 90.0
    assert risk_intensity[_HIGH_VOLUME_ZONE] == 10.0
    assert raw_intensity[_HIGH_VOLUME_ZONE] == 1000.0
    assert raw_intensity[_HIGH_IMPACT_ZONE] == 5.0


# ─── The same distinctness through the real on-disk artifact load path ───────

def test_distinctness_survives_real_datastore_file_load(tmp_path):
    """Writing the synthetic artifact to ``processed/zone_congestion_impact.json``
    and loading it through ``DataStore(data_dir=...).load()`` preserves the layer
    distinctness — exercising the actual on-disk load path end to end.

    Validates: Requirements 8.3, 8.4, 8.5, 10.1, 10.2.
    """
    artifact = _artifact(_INVERSION_SPECS)
    processed = tmp_path / "processed"
    processed.mkdir(parents=True)
    (processed / "zone_congestion_impact.json").write_text(
        json.dumps(artifact), encoding="utf-8"
    )

    store = DataStore(data_dir=tmp_path).load()

    # The artifact was loaded from disk (and only those zones exist).
    assert set(store.congestion) == {_HIGH_VOLUME_ZONE, _HIGH_IMPACT_ZONE}

    cis_order = [h["h3_id"] for h in store.congestion_hotspots(ALL_DAY)]
    count_order = [p["h3_id"] for p in store.violation_density_points(ALL_DAY)]

    # CIS ranking and count ranking are exact reversals -> the orders differ.
    assert cis_order == [_HIGH_IMPACT_ZONE, _HIGH_VOLUME_ZONE]
    assert count_order == [_HIGH_VOLUME_ZONE, _HIGH_IMPACT_ZONE]
    assert cis_order != count_order

    # Risk intensity == CIS; density intensity == count (read from disk).
    risk_intensity = {p["h3_id"]: p["intensity"] for p in store.congestion_points(ALL_DAY)}
    raw_intensity = {p["h3_id"]: p["intensity"] for p in store.violation_density_points(ALL_DAY)}
    assert risk_intensity[_HIGH_IMPACT_ZONE] == 90.0
    assert raw_intensity[_HIGH_VOLUME_ZONE] == 1000.0
