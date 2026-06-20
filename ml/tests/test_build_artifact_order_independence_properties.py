"""
Property-based tests for order-independent aggregation in
``ml.congestion.build_artifact``.
==========================================================================

Task 5.2 — order-independent aggregation.

Covers one correctness property from the design's "Correctness Properties"
section, exercising the offline artifact builder's aggregation seam end to end
via ``build_aggregates`` (which composes ``prepare_violations`` ->
``aggregate_zone_buckets`` -> ``compute_corpus_maxima``):

  * **Property 9 — Aggregation is order-independent:** for any multiset of raw
    violation rows mapped to a zone, the resulting ``ZoneAggregate`` (and the
    ``CorpusMaxima`` taken across them, and therefore CIS) is invariant under
    permutation of the input rows. Concretely, building the aggregates from a
    DataFrame of rows and from a Hypothesis-permuted copy of those same rows
    yields equal results: the same set of ``(h3_id, time_bucket)`` keys, an equal
    ``ZoneAggregate`` for every key, and an equal ``CorpusMaxima``.

**Validates: Requirements 14.5**

Framework: Hypothesis (per design "Property Test Library: Hypothesis"), with a
minimum of 100 examples per property (configured to 150 here).

Why the vehicle pool is restricted to dyadic obstruction weights
----------------------------------------------------------------
Every per-group reduction the builder performs is logically order-independent —
counts, category-membership flags, an ``any`` over the named-junction flag, and
the deterministic (``-count``, then name) tie-breaks for ``top_violations`` and
the representative ``station``. The one floating-point reduction is
``mean_vehicle_obstruction`` (a pandas ``Series.mean()``), and IEEE-754 addition
is *not* associative, so for arbitrary real weights a permuted group can produce
a mean that differs in the last ULP — an artifact of float summation, not the
logical order-dependence Requirement 14.5 is about.

To keep the assertion exact (``==`` on the frozen dataclasses, as the property
states) and target the *logical* invariant, the generated vehicle types are
restricted to those whose obstruction weights are exact dyadic rationals
(``0.5`` / ``1.0`` / ``2.0`` — two-wheelers, cars/vans, buses, and unknown ->
the ``1.0`` default). Any partial sum of such values is itself an exactly
representable multiple of ``0.5`` (well under 2**53 for these row counts), so the
group sum is computed with no rounding regardless of order and the single final
division by the count rounds identically — making ``mean()`` bit-stable under
permutation. The test therefore checks order-independence of the aggregation
logic without conflating it with float-summation associativity.
"""

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from ml.congestion.build_artifact import (
    JUNCTION_NAME_COL,
    LAT_COL,
    LON_COL,
    STATION_COL,
    TIMESTAMP_COL,
    UPDATED_VEHICLE_TYPE_COL,
    VEHICLE_TYPE_COL,
    VIOLATION_TYPE_COL,
    build_aggregates,
)

import pandas as pd


# ─── Input-space pools (small, so rows collide into a few H3 cells/buckets) ──

# A SMALL pool of distinct Bengaluru lat/lon points. The first two are ~30 m
# apart and fall into the SAME H3 res-9 cell, so rows collide into a handful of
# zones (here: 4 distinct cells) — the regime where per-group reductions and the
# all_day rollup actually combine multiple rows.
LATLON_POOL: tuple[tuple[float, float], ...] = (
    (12.9716, 77.5946),
    (12.9719, 77.5948),  # collides with the first into one H3 res-9 cell
    (12.9352, 77.6245),
    (12.9698, 77.7500),
    (13.0298, 77.5400),
)

# Violation strings spanning every count bucket the builder recognizes (main
# road, double parking, junction x2, access x2) plus uncategorized "other"
# strings that still feed the top-violations ranking.
VIOLATION_VOCAB: tuple[str, ...] = (
    "PARKING IN A MAIN ROAD",                    # -> main_road
    "DOUBLE PARKING",                            # -> double_park
    "PARKING NEAR ROAD CROSSING",                # -> junction
    "PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS",  # -> junction
    "PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC",   # -> access
    "PARKING ON FOOTPATH",                       # -> access
    "WRONG PARKING",                             # uncategorized "other"
    "NO PARKING",                                # uncategorized "other"
)

# Vehicle types whose obstruction weights are EXACT dyadic rationals so the
# group mean is order-stable at the bit level (see module docstring):
#   SCOOTER -> 0.5, CAR/VAN -> 1.0, BUS -> 2.0, SPACESHIP (unknown) -> 1.0 default.
VEHICLE_POOL: tuple[str, ...] = ("SCOOTER", "CAR", "VAN", "BUS", "SPACESHIP")

# The validator-corrected column: same dyadic vehicles, plus None / "NULL" which
# make the builder fall back to the (also-dyadic) base vehicle_type. The effective
# weight is therefore always in {0.5, 1.0, 2.0}.
UPDATED_VEHICLE_POOL: tuple[object, ...] = ("SCOOTER", "CAR", "VAN", "BUS", None, "NULL")

# Named junctions plus the sentinels the builder treats as "no junction".
JUNCTION_POOL: tuple[object, ...] = (
    "Trinity Circle",
    "Silk Board Junction",
    "",
    "NO JUNCTION",
    "NULL",
    None,
)

# Police stations (with repeats likely, so the most-frequent tie-break is hit)
# plus null-like values that the representative-station reducer must ignore.
STATION_POOL: tuple[object, ...] = ("Upparpet", "Cubbon Park", "Halasuru", None, "NULL")


# ─── Hypothesis strategies ───────────────────────────────────────────────────

@st.composite
def _violation_row(draw) -> dict:
    """Generate one synthetic cleaned-violation row as a builder-shaped dict.

    Carries the eight columns ``prepare_violations`` reads. The IST hour spans
    0-23 so roughly a third of rows land at/after the 16:00 temporal cliff and are
    dropped — exercising that the cliff filter is order-independent too. The
    timestamp is written with an explicit ``+05:30`` offset so its IST hour (and
    therefore its time bucket) is exactly the drawn hour. ``violation_type`` is
    emitted as a real list for some rows and a JSON-encoded list string for
    others, covering both shapes ``parse_violation_list`` accepts.
    """
    lat, lon = draw(st.sampled_from(LATLON_POOL))

    hour = draw(st.integers(min_value=0, max_value=23))
    minute = draw(st.integers(min_value=0, max_value=59))
    second = draw(st.integers(min_value=0, max_value=59))
    created = f"2024-03-15T{hour:02d}:{minute:02d}:{second:02d}+05:30"

    violations = draw(
        st.lists(st.sampled_from(VIOLATION_VOCAB), min_size=1, max_size=3, unique=True)
    )
    as_json = draw(st.booleans())
    violation_cell = json.dumps(violations) if as_json else list(violations)

    return {
        LAT_COL: lat,
        LON_COL: lon,
        TIMESTAMP_COL: created,
        VIOLATION_TYPE_COL: violation_cell,
        VEHICLE_TYPE_COL: draw(st.sampled_from(VEHICLE_POOL)),
        UPDATED_VEHICLE_TYPE_COL: draw(st.sampled_from(UPDATED_VEHICLE_POOL)),
        JUNCTION_NAME_COL: draw(st.sampled_from(JUNCTION_POOL)),
        STATION_COL: draw(st.sampled_from(STATION_POOL)),
    }


@st.composite
def _rows_and_permutation(draw) -> tuple[list[dict], list[dict]]:
    """Draw a list of violation rows plus a Hypothesis-chosen permutation of it.

    Returns ``(rows, permuted)`` where ``permuted`` is the SAME multiset of rows
    in a drawn order, so building from each and comparing isolates the effect of
    input ordering.
    """
    rows = draw(st.lists(_violation_row(), min_size=1, max_size=24))
    permuted = draw(st.permutations(rows))
    return rows, list(permuted)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _build(rows: list[dict]):
    """Build aggregates + corpus maxima from ``rows`` with a fixed (empty) ratio map.

    Passing an explicit ``travel_time_ratios={}`` keeps the MapMyIndia enrichment
    file out of the picture (every zone's ``travel_time_ratio`` is ``None``), so
    the only variable under test is the row ORDER. ``pd.DataFrame(rows)`` assigns a
    fresh ``RangeIndex``, so the second frame is a genuine reordering, not an
    index-aligned view.
    """
    df = pd.DataFrame(rows)
    return build_aggregates(df, travel_time_ratios={})


def _assert_same_aggregation(rows_a: list[dict], rows_b: list[dict]) -> None:
    """Assert two row orderings produce identical aggregates AND corpus maxima."""
    agg_a, max_a = _build(rows_a)
    agg_b, max_b = _build(rows_b)

    # Same set of (h3_id, time_bucket) keys (Requirement 14.1/14.5 — only observed
    # zone-buckets are emitted, and which ones are emitted cannot depend on order).
    assert set(agg_a) == set(agg_b), (
        f"different (h3_id, time_bucket) keys under permutation:\n"
        f"only in A: {set(agg_a) - set(agg_b)}\nonly in B: {set(agg_b) - set(agg_a)}"
    )

    # Equal ZoneAggregate for every key (frozen dataclass value equality).
    for key in agg_a:
        assert agg_a[key] == agg_b[key], (
            f"ZoneAggregate differs for {key!r} under permutation:\n"
            f"{agg_a[key]!r}\n{agg_b[key]!r}"
        )

    # Whole-mapping equality (subsumes the per-key check; kept as a final guard)
    # and equal corpus maxima (which feed normalization and thus CIS).
    assert agg_a == agg_b, "aggregate mapping differs under permutation"
    assert max_a == max_b, (
        f"CorpusMaxima differs under permutation:\n{max_a!r}\n{max_b!r}"
    )


# ─── Property 9: aggregation is order-independent ────────────────────────────

@settings(max_examples=150, deadline=None)
@given(_rows_and_permutation())
def test_property_9_aggregation_is_order_independent(rows_and_permutation):
    """Property 9: aggregating a multiset of violation rows is invariant under
    permutation of the rows — identical ``(h3_id, time_bucket)`` keys, identical
    ``ZoneAggregate`` per key, and identical ``CorpusMaxima``.

    Validates: Requirements 14.5.
    """
    rows, permuted = rows_and_permutation
    _assert_same_aggregation(rows, permuted)


# ─── Explicit, deterministic scenario (pins the tricky tie-breaks/rollup) ────

# A hand-built corpus that forces every order-sensitive code path to actually
# matter: several rows collide into one H3 cell across two buckets (so the
# per-bucket groups AND the all_day rollup each combine multiple rows), a
# station tie broken by name, a top-violations tie broken by name, a named +
# sentinel junction in the same group, and a post-16:00 row that must be dropped.
_EXPLICIT_ROWS: list[dict] = [
    {  # cell A, morning_peak
        LAT_COL: 12.9716, LON_COL: 77.5946,
        TIMESTAMP_COL: "2024-03-15T08:15:00+05:30",
        VIOLATION_TYPE_COL: ["PARKING IN A MAIN ROAD", "DOUBLE PARKING"],
        VEHICLE_TYPE_COL: "CAR", UPDATED_VEHICLE_TYPE_COL: None,
        JUNCTION_NAME_COL: "Trinity Circle", STATION_COL: "Upparpet",
    },
    {  # cell A (collides with row 0), morning_peak
        LAT_COL: 12.9719, LON_COL: 77.5948,
        TIMESTAMP_COL: "2024-03-15T08:45:00+05:30",
        VIOLATION_TYPE_COL: '["PARKING IN A MAIN ROAD"]',  # JSON-string shape
        VEHICLE_TYPE_COL: "SCOOTER", UPDATED_VEHICLE_TYPE_COL: "NULL",
        JUNCTION_NAME_COL: "NO JUNCTION", STATION_COL: "Halasuru",
    },
    {  # cell A, morning_peak; updated_vehicle_type (CAR) overrides base (BUS)
        LAT_COL: 12.9716, LON_COL: 77.5946,
        TIMESTAMP_COL: "2024-03-15T08:50:00+05:30",
        VIOLATION_TYPE_COL: ["WRONG PARKING"],
        VEHICLE_TYPE_COL: "BUS", UPDATED_VEHICLE_TYPE_COL: "CAR",
        JUNCTION_NAME_COL: "", STATION_COL: "Halasuru",
    },
    {  # cell A, midday
        LAT_COL: 12.9719, LON_COL: 77.5948,
        TIMESTAMP_COL: "2024-03-15T12:05:00+05:30",
        VIOLATION_TYPE_COL: ["PARKING ON FOOTPATH", "WRONG PARKING"],
        VEHICLE_TYPE_COL: "VAN", UPDATED_VEHICLE_TYPE_COL: None,
        JUNCTION_NAME_COL: "NULL", STATION_COL: "Upparpet",
    },
    {  # cell B (different zone), night
        LAT_COL: 12.9352, LON_COL: 77.6245,
        TIMESTAMP_COL: "2024-03-15T02:30:00+05:30",
        VIOLATION_TYPE_COL: ["DOUBLE PARKING"],
        VEHICLE_TYPE_COL: "SCOOTER", UPDATED_VEHICLE_TYPE_COL: None,
        JUNCTION_NAME_COL: "Silk Board Junction", STATION_COL: "Cubbon Park",
    },
    {  # cell A, POST-CLIFF (18:00 IST) -> must be dropped from buckets AND all_day
        LAT_COL: 12.9716, LON_COL: 77.5946,
        TIMESTAMP_COL: "2024-03-15T18:20:00+05:30",
        VIOLATION_TYPE_COL: ["NO PARKING"],
        VEHICLE_TYPE_COL: "BUS", UPDATED_VEHICLE_TYPE_COL: None,
        JUNCTION_NAME_COL: "Trinity Circle", STATION_COL: "Upparpet",
    },
]


def test_order_independence_explicit_scenario():
    """Original vs reversed vs a fixed rotation of a rich, colliding corpus all
    produce identical aggregates and corpus maxima.

    Also asserts the scenario is genuinely non-trivial (multiple buckets, an
    all_day rollup, and a multi-row group), so the equality is exercised against
    real per-group reductions rather than singleton cells.

    Validates: Requirements 14.5.
    """
    reversed_rows = list(reversed(_EXPLICIT_ROWS))
    rotated_rows = _EXPLICIT_ROWS[3:] + _EXPLICIT_ROWS[:3]

    _assert_same_aggregation(_EXPLICIT_ROWS, reversed_rows)
    _assert_same_aggregation(_EXPLICIT_ROWS, rotated_rows)

    # Sanity: the corpus actually exercises grouping (not all singletons/empties).
    aggregates, _ = _build(_EXPLICIT_ROWS)
    buckets = {bucket for _, bucket in aggregates}
    assert "all_day" in buckets, "expected an all_day rollup entry"
    assert {"night", "morning_peak", "midday"} <= buckets, (
        f"expected multiple data-rich buckets, got {buckets}"
    )
    assert any(agg.total_records >= 2 for agg in aggregates.values()), (
        "expected at least one multi-row group to exercise the reductions"
    )
    # The post-16:00 row was dropped, so cell A's all_day total is 4 (rows 0-3),
    # not 5 — confirming the cliff filter ran and is part of what stays stable.
    assert all(agg.total_records <= 4 for agg in aggregates.values())
