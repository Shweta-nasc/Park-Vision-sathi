"""
Property-based tests for empty-corpus / zero-record handling in
``ml.congestion.build_artifact``.
==========================================================================

Task 5.3 — empty-corpus handling.

Covers one correctness property from the design's "Correctness Properties"
section, exercised through the offline artifact builder's aggregation seam
``build_aggregates`` (which composes ``read_violations`` -> ``prepare_violations``
-> ``aggregate_zone_buckets`` -> ``compute_corpus_maxima``) and the
``aggregate_zone_buckets`` reducer directly:

  * **Property 11 — Empty corpus yields empty artifact:** for an empty violations
    input, ``build_aggregates`` produces no zones (an empty aggregates mapping and
    an all-zero ``CorpusMaxima``); and a ``(h3_id, time_bucket)`` cell with zero
    records is never emitted, so there are no "phantom MINIMAL" entries. The key
    set of the aggregates is *exactly* the observed ``(h3_id, time_bucket)``
    combinations plus one ``all_day`` rollup per observed zone — nothing more —
    and every emitted ``ZoneAggregate`` is backed by at least one real record
    (``total_records >= 1``).

The design's ``build_congestion_artifact`` (task 5.4) is not yet wired; per the
design, "Empty inputs to ``build_congestion_artifact`` therefore produce an empty
artifact, not phantom MINIMAL zones," and the omission decision is implemented at
the aggregation seam these tests target: only observed zones are aggregated, so
the artifact built on top of them inherits the empty/omitted behavior.

**Validates: Requirements 14.1**

Framework: Hypothesis (per design "Property Test Library: Hypothesis"), with a
minimum of 100 examples per generative property (configured to 200 here). The
pure-empty cases (an empty DataFrame, a zero-row DataFrame) are plain asserts,
since there is nothing to generate.

Determinism of inputs
---------------------
Generated timestamps carry an explicit ``+05:30`` (IST) offset, so a row's IST
hour — and therefore its time bucket — is exactly the drawn hour after the
builder's UTC-parse/IST-convert round-trip. "Valid" rows draw hours in ``[0, 16)``
(always a real bucket); "post-cliff" droppable rows draw hours in ``[16, 24)``
(always dropped by the 16:00 IST temporal-cliff guard). The H3 cell of each
generated point is taken from the builder's own ``h3_id_for`` when computing the
expected key set, so the assertion targets *which* zone-buckets are emitted (the
property), not the H3 math itself.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from ml.congestion.build_artifact import (
    ALL_DAY,
    JUNCTION_NAME_COL,
    LAT_COL,
    LON_COL,
    STATION_COL,
    TIMESTAMP_COL,
    UPDATED_VEHICLE_TYPE_COL,
    VEHICLE_TYPE_COL,
    VIOLATION_TYPE_COL,
    aggregate_zone_buckets,
    build_aggregates,
    h3_id_for,
    prepare_violations,
    time_bucket_for_hour,
)
from ml.congestion.impact_score import CorpusMaxima

# ─── Shared fixtures ─────────────────────────────────────────────────────────

# The eight columns ``prepare_violations`` reads from a cleaned-violations source.
EXPECTED_COLUMNS: tuple[str, ...] = (
    LAT_COL,
    LON_COL,
    TIMESTAMP_COL,
    VIOLATION_TYPE_COL,
    VEHICLE_TYPE_COL,
    UPDATED_VEHICLE_TYPE_COL,
    JUNCTION_NAME_COL,
    STATION_COL,
)

# An empty corpus normalizes to all-zero maxima (compute_corpus_maxima([])).
ZERO_MAXIMA = CorpusMaxima(
    max_lane_load=0.0,
    max_junction_load=0.0,
    max_access_count=0.0,
    max_mean_obstruction=0.0,
)

# A SMALL pool of Bengaluru points. The first two are ~30 m apart and fall into
# the SAME H3 res-9 cell (verified: 8960145b483ffff), so valid rows collide into
# a handful of zones and the "only observed buckets" key set is exercised against
# real multi-row groups and per-zone all_day rollups rather than singletons.
LATLON_POOL: tuple[tuple[float, float], ...] = (
    (12.9716, 77.5946),
    (12.9719, 77.5948),  # collides with the first into one H3 res-9 cell
    (12.9352, 77.6245),
    (12.9698, 77.7500),
)

# Violation strings spanning the builder's count buckets plus an uncategorized
# "other" string; the exact mix is irrelevant to record counts (total_records is
# a per-row count), so this only needs to be a non-empty, parseable cell.
VIOLATION_VOCAB: tuple[str, ...] = (
    "PARKING IN A MAIN ROAD",
    "DOUBLE PARKING",
    "PARKING NEAR ROAD CROSSING",
    "PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC",
    "PARKING ON FOOTPATH",
    "WRONG PARKING",
)

# Coordinate cells that ``pd.to_numeric(errors="coerce")`` turns into NaN, so the
# row is dropped at the coordinate stage.
BAD_COORD_VALUES: tuple[object, ...] = (None, float("nan"), "n/a", "", "NULL")

# Timestamp cells that ``pd.to_datetime(errors="coerce")`` turns into NaT, so the
# row is dropped at the timestamp stage.
UNPARSEABLE_TIMESTAMPS: tuple[object, ...] = (
    None,
    "",
    "not-a-date",
    "garbage",
    "31/31/2024 99:99",
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _valid_row(lat: float, lon: float, hour: int, minute: int) -> dict:
    """A builder-shaped row that survives every filter (valid coords + in-window ts)."""
    return {
        LAT_COL: lat,
        LON_COL: lon,
        TIMESTAMP_COL: f"2024-03-15T{hour:02d}:{minute:02d}:00+05:30",
        VIOLATION_TYPE_COL: ["WRONG PARKING"],
        VEHICLE_TYPE_COL: "CAR",
        UPDATED_VEHICLE_TYPE_COL: None,
        JUNCTION_NAME_COL: None,
        STATION_COL: "Upparpet",
    }


def _expected_keys_and_counts(
    specs: list[tuple[tuple[float, float], int, int]],
) -> dict[tuple[str, str], int]:
    """Independently derive the expected ``{(h3_id, bucket): record_count}`` map.

    For each valid spec ``((lat, lon), hour, minute)``: the row lands in
    ``h3_id_for(lat, lon)`` at bucket ``time_bucket_for_hour(hour)`` (never None
    for hours in [0, 16)). The expected artifact keys are exactly those observed
    ``(h3_id, bucket)`` cells plus one ``(h3_id, all_day)`` rollup per observed
    zone — and no others. This is what "zero-record buckets are omitted / no
    phantom entries" means concretely.
    """
    bucket_counts: Counter[tuple[str, str]] = Counter()
    zone_counts: Counter[str] = Counter()
    for (lat, lon), hour, _minute in specs:
        h3_id = h3_id_for(lat, lon)
        bucket = time_bucket_for_hour(hour)
        assert bucket is not None  # specs only draw in-window hours
        bucket_counts[(h3_id, bucket)] += 1
        zone_counts[h3_id] += 1

    expected: dict[tuple[str, str], int] = dict(bucket_counts)
    for h3_id, count in zone_counts.items():
        expected[(h3_id, ALL_DAY)] = count
    return expected


def _assert_empty_result(aggregates, maxima) -> None:
    """Assert the builder emitted no zones and all-zero corpus maxima."""
    assert aggregates == {}, f"expected no zones, got keys {set(aggregates)}"
    assert maxima == ZERO_MAXIMA, f"expected all-zero maxima, got {maxima!r}"


# ─── Hypothesis strategies ───────────────────────────────────────────────────

@st.composite
def _droppable_row(draw) -> dict:
    """Generate one row guaranteed to be dropped by ``prepare_violations``.

    A row is dropped for exactly one of the three reasons the builder filters on,
    drawn uniformly so a generated frame is an arbitrary mix of them (and any mix
    still filters down to empty):

    * ``bad_coords``     — coordinates coerce to NaN (dropped at the coord stage);
    * ``unparseable_ts`` — valid coords, timestamp coerces to NaT (ts stage);
    * ``post_cliff``     — valid coords + parseable timestamp at hour >= 16 IST,
                           which maps to no bucket (the temporal-cliff guard).
    """
    reason = draw(st.sampled_from(("bad_coords", "unparseable_ts", "post_cliff")))
    row: dict = {
        VIOLATION_TYPE_COL: ["WRONG PARKING"],
        VEHICLE_TYPE_COL: "CAR",
        UPDATED_VEHICLE_TYPE_COL: None,
        JUNCTION_NAME_COL: None,
        STATION_COL: None,
    }

    if reason == "bad_coords":
        row[LAT_COL] = draw(st.sampled_from(BAD_COORD_VALUES))
        row[LON_COL] = draw(st.sampled_from(BAD_COORD_VALUES))
        row[TIMESTAMP_COL] = "2024-03-15T08:30:00+05:30"  # valid; drop is on coords
    elif reason == "unparseable_ts":
        lat, lon = draw(st.sampled_from(LATLON_POOL))
        row[LAT_COL] = lat
        row[LON_COL] = lon
        row[TIMESTAMP_COL] = draw(st.sampled_from(UNPARSEABLE_TIMESTAMPS))
    else:  # post_cliff
        lat, lon = draw(st.sampled_from(LATLON_POOL))
        hour = draw(st.integers(min_value=16, max_value=23))
        minute = draw(st.integers(min_value=0, max_value=59))
        row[LAT_COL] = lat
        row[LON_COL] = lon
        row[TIMESTAMP_COL] = f"2024-03-15T{hour:02d}:{minute:02d}:00+05:30"

    return row


# A valid spec: a pooled point, an in-window hour (always a real bucket), minute.
_VALID_SPEC = st.tuples(
    st.sampled_from(LATLON_POOL),
    st.integers(min_value=0, max_value=15),
    st.integers(min_value=0, max_value=59),
)


# ─── Pure-empty cases (plain asserts) ────────────────────────────────────────

def test_empty_dataframe_yields_empty_aggregates_and_zero_maxima():
    """An empty DataFrame produces no zones and an all-zero CorpusMaxima.

    Validates: Requirements 14.1.
    """
    aggregates, maxima = build_aggregates(pd.DataFrame(), travel_time_ratios={})
    _assert_empty_result(aggregates, maxima)


def test_zero_row_dataframe_with_columns_yields_empty():
    """A DataFrame with the right columns but zero rows produces no zones.

    Validates: Requirements 14.1.
    """
    empty_with_cols = pd.DataFrame({col: [] for col in EXPECTED_COLUMNS})
    aggregates, maxima = build_aggregates(empty_with_cols, travel_time_ratios={})
    _assert_empty_result(aggregates, maxima)


def test_aggregate_zone_buckets_on_empty_prepared_frame_is_empty():
    """``aggregate_zone_buckets`` returns ``{}`` for an empty prepared frame.

    Exercises the reducer directly (both a bare empty frame and a prepared
    zero-row frame), independently of the ``build_aggregates`` wrapper.

    Validates: Requirements 14.1.
    """
    assert aggregate_zone_buckets(pd.DataFrame(), {}) == {}

    prepared = prepare_violations(pd.DataFrame({col: [] for col in EXPECTED_COLUMNS}))
    assert aggregate_zone_buckets(prepared, {}) == {}


# ─── Property 11: all-rows-dropped inputs yield an empty artifact ────────────

@settings(max_examples=200, deadline=None)
@given(st.lists(_droppable_row(), min_size=1, max_size=20))
def test_all_dropped_rows_yield_empty_aggregates(rows):
    """A frame whose every row is droppable (post-cliff / bad coords / unparseable
    timestamp) filters down to nothing, so the builder emits no zones and all-zero
    maxima — exactly the empty-corpus outcome, with no phantom entries.

    Validates: Requirements 14.1.
    """
    aggregates, maxima = build_aggregates(pd.DataFrame(rows), travel_time_ratios={})
    _assert_empty_result(aggregates, maxima)


# ─── Property 11: only observed zone-buckets are emitted (no phantom entries) ─

@settings(max_examples=200, deadline=None)
@given(st.lists(_VALID_SPEC, min_size=1, max_size=20))
def test_only_observed_zone_buckets_are_emitted(specs):
    """The aggregates' key set equals EXACTLY the observed ``(h3_id, time_bucket)``
    cells plus one ``all_day`` rollup per observed zone — never a bucket in which
    the zone had zero rows. Every emitted ``ZoneAggregate`` is backed by at least
    one real record, and its ``total_records`` equals the number of rows that
    actually landed in that cell (so no key is a phantom MINIMAL entry).

    Validates: Requirements 14.1.
    """
    rows = [_valid_row(lat, lon, hour, minute) for (lat, lon), hour, minute in specs]
    aggregates, _maxima = build_aggregates(pd.DataFrame(rows), travel_time_ratios={})

    expected = _expected_keys_and_counts(specs)

    # Exactly the observed zone-buckets + all_day rollups — no phantom keys, and
    # none of the observed ones missing.
    assert set(aggregates) == set(expected), (
        f"phantom or missing keys:\n"
        f"unexpected: {set(aggregates) - set(expected)}\n"
        f"missing:    {set(expected) - set(aggregates)}"
    )

    # Every emitted entry corresponds to >= 1 real record, matching the true count.
    for key, agg in aggregates.items():
        assert agg.total_records >= 1, f"phantom zero-record entry at {key!r}"
        assert agg.total_records == expected[key], (
            f"record count mismatch at {key!r}: "
            f"{agg.total_records} != {expected[key]}"
        )


# ─── Explicit, deterministic scenarios (pin the omission behavior) ───────────

def test_single_bucket_zone_omits_unobserved_buckets():
    """A zone with rows only in ``morning_peak`` emits exactly that bucket plus its
    ``all_day`` rollup — the three unobserved buckets are absent (not zero-record
    MINIMAL placeholders). Both rows collide into one H3 cell.

    Validates: Requirements 14.1.
    """
    rows = [
        _valid_row(12.9716, 77.5946, 8, 15),
        _valid_row(12.9719, 77.5948, 9, 45),  # same cell, same bucket
    ]
    aggregates, _ = build_aggregates(pd.DataFrame(rows), travel_time_ratios={})

    zone = h3_id_for(12.9716, 77.5946)
    assert set(aggregates) == {(zone, "morning_peak"), (zone, ALL_DAY)}
    for absent in ("night", "midday", "afternoon"):
        assert (zone, absent) not in aggregates
    assert aggregates[(zone, "morning_peak")].total_records == 2
    assert aggregates[(zone, ALL_DAY)].total_records == 2


def test_observed_buckets_only_across_multiple_zones():
    """Across two zones, only the buckets each zone actually has rows in are
    emitted (plus per-zone ``all_day``): zone A has night + midday, zone B has
    afternoon. No phantom cross-product of zones x buckets appears.

    Validates: Requirements 14.1.
    """
    rows = [
        _valid_row(12.9716, 77.5946, 2, 30),   # zone A, night
        _valid_row(12.9719, 77.5948, 12, 5),   # zone A (same cell), midday
        _valid_row(12.9352, 77.6245, 14, 30),  # zone B, afternoon
    ]
    aggregates, _ = build_aggregates(pd.DataFrame(rows), travel_time_ratios={})

    zone_a = h3_id_for(12.9716, 77.5946)
    zone_b = h3_id_for(12.9352, 77.6245)
    assert set(aggregates) == {
        (zone_a, "night"),
        (zone_a, "midday"),
        (zone_a, ALL_DAY),
        (zone_b, "afternoon"),
        (zone_b, ALL_DAY),
    }
    # Buckets neither zone observed must not appear for either zone.
    assert (zone_a, "morning_peak") not in aggregates
    assert (zone_a, "afternoon") not in aggregates
    assert (zone_b, "night") not in aggregates
    assert (zone_b, "midday") not in aggregates

    assert aggregates[(zone_a, ALL_DAY)].total_records == 2
    assert aggregates[(zone_b, ALL_DAY)].total_records == 1
    for agg in aggregates.values():
        assert agg.total_records >= 1


def test_all_post_cliff_rows_yield_empty_artifact():
    """An explicit all-post-16:00-IST corpus (a realistic temporal-cliff case)
    produces no zones — the deterministic companion to the generated drop test.

    Validates: Requirements 14.1.
    """
    rows = [
        _valid_row(12.9716, 77.5946, 17, 0),
        _valid_row(12.9352, 77.6245, 21, 30),
        _valid_row(12.9698, 77.7500, 23, 59),
    ]
    aggregates, maxima = build_aggregates(pd.DataFrame(rows), travel_time_ratios={})
    _assert_empty_result(aggregates, maxima)
