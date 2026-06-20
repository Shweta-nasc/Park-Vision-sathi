"""
Property-based tests for ``ml.congestion.impact_score.compute_components``.
===========================================================================

Task 2.2 — component normalization & zero-maxima guard.

Covers two correctness properties from the design's "Correctness Properties"
section, testing the pure ``compute_components(z, m)`` scoring core:

  * **Property 3 — Components are normalized to [0, 1]:** every scored
    component returned by ``compute_components`` and the reported ``severity``
    diagnostic lies in the closed interval [0, 1]. (The "changing only severity
    does not change CIS" half of Property 3 depends on ``compute_score``, which
    is implemented in a later task; here we assert all returned component values
    are within [0, 1].)

  * **Property 7 — Normalization is bounded and never divides by zero:** for ANY
    ``CorpusMaxima`` — including maxima that are exactly 0 — each count-based
    component (``lane_blockage``, ``intersection_impact``, ``access_blockage``,
    ``vehicle_size``) is computed via guarded denominators and yields a finite
    value in [0, 1] with no ``ZeroDivisionError`` and no NaN/inf.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 14.2**

Framework: Hypothesis (per design "Property Test Library: Hypothesis"), with a
minimum of 100 examples per property (configured to 200 here).
"""

from __future__ import annotations

import math

from hypothesis import example, given, settings
from hypothesis import strategies as st

from ml.congestion.impact_score import (
    CorpusMaxima,
    ZoneAggregate,
    compute_components,
)

# Keys returned by ``compute_components``, grouped by what each property checks.
SCORED_COMPONENT_KEYS = (
    "lane_blockage",
    "intersection_impact",
    "traffic_degradation",
    "access_blockage",
    "vehicle_size",
)
# Property 3 additionally bounds the reported (non-weighted) severity diagnostic.
BOUNDED_KEYS = SCORED_COMPONENT_KEYS + ("severity",)
# Property 7 targets the count-based components whose denominators are guarded.
COUNT_BASED_KEYS = (
    "lane_blockage",
    "intersection_impact",
    "access_blockage",
    "vehicle_size",
)

TIME_BUCKETS = ("all_day", "night", "morning_peak", "midday", "afternoon")


# ─── Hypothesis strategies ───────────────────────────────────────────────────

# travel_time_ratio: None (missing -> deterministic fallback) OR a positive ratio
# spanning below-1 "free flow" (clamps the degradation at 0) through heavy
# congestion (clamps at 1).
_travel_time_ratio = st.one_of(
    st.none(),
    st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
)

# Non-negative corpus maxima that EXPLICITLY include exactly 0.0 — the Property 7
# edge case — sampled alongside arbitrary positive maxima so the guarded
# denominators are exercised on both sides of the guard.
_non_negative_maximum = st.one_of(
    st.just(0.0),
    st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
)


@st.composite
def _zone_aggregates(draw):
    """Generate an arbitrary VALID ``ZoneAggregate``.

    ``total_records`` is drawn first; each category count is then bounded to
    ``[0, total_records]`` to honor the design precondition that no category
    count exceeds the zone total. The corpus maxima are drawn independently and
    may be smaller than these counts (or zero) — precisely what stresses the
    normalization caps and the zero-maxima guard.
    """
    total = draw(st.integers(min_value=0, max_value=100_000))
    bounded_count = st.integers(min_value=0, max_value=total)
    return ZoneAggregate(
        h3_id=draw(st.text(max_size=16)),
        time_bucket=draw(st.sampled_from(TIME_BUCKETS)),
        total_records=total,
        main_road_count=draw(bounded_count),
        double_park_count=draw(bounded_count),
        junction_violation_count=draw(bounded_count),
        access_violation_count=draw(bounded_count),
        mean_vehicle_obstruction=draw(
            st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False)
        ),
        has_named_junction=draw(st.booleans()),
        travel_time_ratio=draw(_travel_time_ratio),
        station=draw(st.one_of(st.none(), st.text(max_size=12))),
        top_violations=draw(st.lists(st.text(max_size=24), max_size=5).map(tuple)),
    )


@st.composite
def _corpus_maxima(draw):
    """Generate arbitrary non-negative ``CorpusMaxima``, including zero maxima."""
    return CorpusMaxima(
        max_lane_load=draw(_non_negative_maximum),
        max_junction_load=draw(_non_negative_maximum),
        max_access_count=draw(_non_negative_maximum),
        max_mean_obstruction=draw(_non_negative_maximum),
    )


def _assert_unit_interval(value, key):
    """Assert ``value`` is a finite ``float`` within the closed interval [0, 1]."""
    assert isinstance(value, float), f"{key!r} is not a float: {value!r}"
    assert math.isfinite(value), f"{key!r} is not finite (NaN/inf): {value!r}"
    assert 0.0 <= value <= 1.0, f"{key!r} outside [0, 1]: {value!r}"


# A degenerate zone with positive counts so that all-zero maxima genuinely
# exercise the guarded denominators (non-zero numerator over a guarded zero
# denominator must still clamp into [0, 1]).
_NONZERO_ZONE = ZoneAggregate(
    h3_id="edge",
    time_bucket="all_day",
    total_records=10,
    main_road_count=10,
    double_park_count=10,
    junction_violation_count=10,
    access_violation_count=10,
    mean_vehicle_obstruction=2.0,
    has_named_junction=True,
    travel_time_ratio=None,
    station=None,
    top_violations=(),
)
_ZERO_MAXIMA = CorpusMaxima(
    max_lane_load=0.0,
    max_junction_load=0.0,
    max_access_count=0.0,
    max_mean_obstruction=0.0,
)


# ─── Property 3: components are normalized to [0, 1] ─────────────────────────

@settings(max_examples=200, deadline=None)
@given(z=_zone_aggregates(), m=_corpus_maxima())
def test_property_3_components_normalized_to_unit_interval(z, m):
    """Property 3: every scored component AND the severity diagnostic lie in [0, 1].

    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6.
    """
    components = compute_components(z, m)

    for key in BOUNDED_KEYS:
        assert key in components, f"missing component {key!r}"
        _assert_unit_interval(components[key], key)

    # The defaulted flag is a bool (not a score) and must always be present.
    assert isinstance(components["defaulted"], bool)


# ─── Property 7: normalization is bounded and never divides by zero ──────────

@settings(max_examples=200, deadline=None)
@given(z=_zone_aggregates(), m=_corpus_maxima())
@example(z=_NONZERO_ZONE, m=_ZERO_MAXIMA)  # force the all-zero-maxima edge case
def test_property_7_normalization_guarded_against_zero_maxima(z, m):
    """Property 7: count-based components stay finite in [0, 1] for ANY maxima.

    The strategy supplies zero maxima frequently (and the explicit example pins
    the all-zero case with positive counts), so computing must never raise a
    ``ZeroDivisionError`` and every count-based component must be a finite value
    in [0, 1] thanks to the guarded denominators.

    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 14.2.
    """
    # Must not raise (e.g. ZeroDivisionError) for any non-negative maxima.
    components = compute_components(z, m)

    for key in COUNT_BASED_KEYS:
        _assert_unit_interval(components[key], key)
