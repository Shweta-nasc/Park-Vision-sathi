"""
Property-based tests for ``ml.congestion.impact_score.estimate_lane_hours``.
============================================================================

Task 2.8 — lane-hours.

Covers one correctness property from the design's "Correctness Properties"
section, testing the pure ``estimate_lane_hours(z)`` scoring core:

  * **Property 8 — Lane-hours are non-negative and monotonic:** for any zone,
    ``estimate_lane_hours(z) >= 0`` (and is a finite float), and increasing any
    single contributing count — ``main_road_count``, ``double_park_count``,
    ``junction_violation_count``, or ``total_records`` — while holding the others
    fixed never decreases the estimate.

The estimate is::

    main_road·0.5 + double_park·1.0 + junction·0.75 + other·0.25

    other = max(total_records − main_road − double_park − junction, 0)

The ``other`` term ties the estimate to ``total_records`` AND (negatively) to the
three named category counts, and it is floored at 0 because the named counts come
from overlapping source categories and may over-count past ``total_records``.
Monotonicity therefore has to survive that floor: incrementing a named count adds
its own coefficient (0.5 / 1.0 / 0.75) while removing at most 0.25 from the
``other`` term (and strictly less once ``other`` hits the floor), so the net move
is always ``>= 0``; incrementing ``total_records`` only ever raises the floored
``other``. These tests pin both regimes and the crossing of the floor boundary.

**Validates: Requirements 5.1, 5.2, 5.3**

Framework: Hypothesis (per design "Property Test Library: Hypothesis"), with a
minimum of 100 examples per property (configured to 200 here).
"""

from __future__ import annotations

import math
from dataclasses import replace

from hypothesis import example, given, settings
from hypothesis import strategies as st

from ml.congestion.impact_score import (
    ZoneAggregate,
    estimate_lane_hours,
)

TIME_BUCKETS = ("all_day", "night", "morning_peak", "midday", "afternoon")

# The four counts that contribute to the estimate; Property 8 requires the result
# to be non-decreasing when any ONE of these increases with the others held fixed.
CONTRIBUTING_FIELDS = (
    "main_road_count",
    "double_park_count",
    "junction_violation_count",
    "total_records",
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _assert_non_negative_finite(value):
    """Assert ``value`` is a finite, non-negative ``float`` (Requirement 5.2)."""
    assert isinstance(value, float), f"lane-hours is not a float: {value!r}"
    assert math.isfinite(value), f"lane-hours is not finite (NaN/inf): {value!r}"
    assert value >= 0.0, f"lane-hours is negative: {value!r}"


def _make_zone(
    *,
    total,
    main,
    double,
    junction,
    access=0,
    obstruction=1.0,
    named_junction=False,
    ratio=None,
):
    """Build a ``ZoneAggregate`` from just the counts that drive lane-hours.

    Only ``total_records`` and the three named category counts affect
    ``estimate_lane_hours``; the remaining fields are fixed to inert defaults so
    the explicit ``@example`` cases below read as the count scenario they pin.
    """
    return ZoneAggregate(
        h3_id="lanehours",
        time_bucket="all_day",
        total_records=total,
        main_road_count=main,
        double_park_count=double,
        junction_violation_count=junction,
        access_violation_count=access,
        mean_vehicle_obstruction=obstruction,
        has_named_junction=named_junction,
        travel_time_ratio=ratio,
        station=None,
        top_violations=(),
    )


# ─── Hypothesis strategies ───────────────────────────────────────────────────

# Counts are drawn INDEPENDENTLY of total_records (deliberately NOT bounded by it,
# unlike the other property suites) so that main + double + junction can exceed
# total_records — exercising the ``other = max(total − categories, 0)`` floor. The
# ranges overlap (all 0..5000) so ``inner = total − categories`` lands on both
# sides of, and right at, the floor boundary across the generated examples.
_count = st.integers(min_value=0, max_value=5000)


@st.composite
def _zone_aggregates(draw):
    """Generate an arbitrary ``ZoneAggregate`` for lane-hours testing.

    Every field is generated freely (category counts independent of
    ``total_records``) so the property holds "for any zone"; only the four
    contributing counts influence the estimate.
    """
    return ZoneAggregate(
        h3_id=draw(st.text(max_size=16)),
        time_bucket=draw(st.sampled_from(TIME_BUCKETS)),
        total_records=draw(_count),
        main_road_count=draw(_count),
        double_park_count=draw(_count),
        junction_violation_count=draw(_count),
        access_violation_count=draw(_count),
        mean_vehicle_obstruction=draw(
            st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False)
        ),
        has_named_junction=draw(st.booleans()),
        travel_time_ratio=draw(
            st.one_of(
                st.none(),
                st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
            )
        ),
        station=draw(st.one_of(st.none(), st.text(max_size=12))),
        top_violations=draw(st.lists(st.text(max_size=24), max_size=5).map(tuple)),
    )


# Positive deltas spanning small steps (which crawl across the floor boundary) and
# large jumps (which leap far past it).
_positive_delta = st.integers(min_value=1, max_value=10_000)


# ─── Property 8a: lane-hours are non-negative and finite ─────────────────────

@settings(max_examples=200, deadline=None)
@given(z=_zone_aggregates())
@example(z=_make_zone(total=0, main=0, double=0, junction=0))            # empty -> exactly 0.0
@example(z=_make_zone(total=5, main=100, double=100, junction=100))     # categories >> total (floor active)
@example(z=_make_zone(total=10_000, main=0, double=0, junction=0))      # all weight in the `other` term
@example(z=_make_zone(total=30, main=10, double=10, junction=10))       # total == categories (inner == 0)
def test_property_8_lane_hours_non_negative_and_finite(z):
    """Property 8 (non-negativity): ``estimate_lane_hours(z) >= 0`` and finite for
    any zone, including when the named counts over-count past ``total_records``
    and drive the raw ``other`` term negative (it is floored at 0).

    Validates: Requirements 5.1, 5.2.
    """
    _assert_non_negative_finite(estimate_lane_hours(z))


# ─── Property 8b: lane-hours are monotonic non-decreasing in each count ──────

@settings(max_examples=200, deadline=None)
@given(z=_zone_aggregates(), delta=_positive_delta)
# empty zone, smallest possible bump:
@example(z=_make_zone(total=0, main=0, double=0, junction=0), delta=1)
# `other` strictly positive and stays positive after the bump (no floor crossing):
@example(z=_make_zone(total=1000, main=10, double=10, junction=10), delta=5)
# `other` positive (== 1) and a category bump CROSSES the floor to 0, while the
# same total bump grows `other` — the key boundary case:
@example(z=_make_zone(total=20, main=15, double=2, junction=2), delta=5)
# floor already active (categories exceed total): a total bump leaves `other` at 0
# (no change -> non-decrease holds with equality), category bumps still rise:
@example(z=_make_zone(total=5, main=100, double=100, junction=100), delta=10)
# inner exactly 0 at the boundary; a unit bump tips it either way:
@example(z=_make_zone(total=30, main=10, double=10, junction=10), delta=1)
# inner exactly 0 with a large bump that leaps far across the boundary:
@example(z=_make_zone(total=30, main=10, double=10, junction=10), delta=1000)
def test_property_8_monotonic_non_decreasing_in_each_contributing_count(z, delta):
    """Property 8 (monotonicity): incrementing any ONE contributing count by a
    positive delta, holding the others fixed, never decreases the estimate.

    Checks all four of ``{main_road_count, double_park_count,
    junction_violation_count, total_records}`` against the same baseline ``z`` —
    so each comparison varies exactly one field. The explicit examples pin the
    floor-boundary behaviour (``other`` positive, exactly zero, already floored,
    and crossings in both directions) that a naive monotonicity argument could
    miss.

    Validates: Requirements 5.1, 5.2, 5.3.
    """
    base = estimate_lane_hours(z)
    _assert_non_negative_finite(base)

    for field in CONTRIBUTING_FIELDS:
        z2 = replace(z, **{field: getattr(z, field) + delta})
        bumped = estimate_lane_hours(z2)

        # The bumped zone must itself be a valid (non-negative, finite) estimate.
        _assert_non_negative_finite(bumped)

        # Coefficients are exact in binary floating point (0.5, 1.0, 0.75, 0.25),
        # so the comparison needs no tolerance.
        assert bumped >= base, (
            f"increasing {field} by {delta} decreased lane-hours: "
            f"{bumped!r} < {base!r} (base zone={z!r})"
        )
