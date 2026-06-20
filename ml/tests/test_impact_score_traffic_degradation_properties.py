"""
Property-based tests for the traffic-degradation component of
``ml.congestion.impact_score.compute_components``.
====================================================================

Task 2.3 — traffic-degradation fallback & bounds.

Covers one correctness property from the design's "Correctness Properties"
section, testing the pure ``compute_components(z, m)`` scoring core:

  * **Property 6 — Traffic-degradation fallback and bounds:** for any zone, if
    ``travel_time_ratio`` is missing or non-positive (or non-numeric), then
    ``traffic_degradation == 0.5`` and the ``defaulted`` flag (surfaced on the
    contract as ``is_traffic_degradation_defaulted``) is True; otherwise
    ``traffic_degradation == clamp((ratio - 1) / 2, 0, 1)`` and the flag is
    False. In every case ``traffic_degradation`` is a finite float in [0, 1].

This mirrors design Error-Handling Scenario 6 ("Malformed travel_time_ratio
(<= 0 or non-numeric) -> treat as missing -> default 0.5 and
is_traffic_degradation_defaulted = True") and the module's own
``_is_valid_travel_time_ratio`` predicate, which rejects ``None``, booleans,
non-numeric types, non-finite values (NaN / +-inf), and values ``<= 0``.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 13.3**

Framework: Hypothesis (per design "Property Test Library: Hypothesis"), with a
minimum of 100 examples per property (configured to 200 here).
"""

from __future__ import annotations

import math
from dataclasses import replace

from hypothesis import example, given, settings
from hypothesis import strategies as st

from ml.congestion.impact_score import (
    DEFAULT_TRAFFIC_DEGRADATION,
    CorpusMaxima,
    ZoneAggregate,
    compute_components,
)

TIME_BUCKETS = ("all_day", "night", "morning_peak", "midday", "afternoon")


# ─── Expected-value oracle (computed independently of the module) ────────────

def _expected_degradation(ratio: float) -> float:
    """The expected ``traffic_degradation`` for a VALID positive ratio.

    Re-derives the design formula ``clamp((ratio - 1) / 2, 0, 1)`` independently
    of the production code so the test asserts agreement rather than tautology.
    """
    return min(1.0, max(0.0, (ratio - 1.0) / 2.0))


def _assert_unit_interval(value, key="traffic_degradation"):
    """Assert ``value`` is a finite ``float`` within the closed interval [0, 1]."""
    assert isinstance(value, float), f"{key!r} is not a float: {value!r}"
    assert math.isfinite(value), f"{key!r} is not finite (NaN/inf): {value!r}"
    assert 0.0 <= value <= 1.0, f"{key!r} outside [0, 1]: {value!r}"


# ─── travel_time_ratio strategies ────────────────────────────────────────────

# VALID ratios: strictly-positive, finite floats spanning the design generator's
# range {None} ∪ [0.5, 4.0]. The sampled points pin both ends of the clamp:
#   * below 1.0 (0.5 / 0.75 / 0.9) -> (ratio - 1)/2 is negative  -> clamps to 0.0
#   * at 1.0                       -> 0.0
#   * >= 3.0  (3.0 / 3.5 / 4.0)    -> (ratio - 1)/2 >= 1.0        -> clamps to 1.0
_valid_ratios = st.one_of(
    st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
    st.sampled_from([0.5, 0.75, 0.9, 1.0, 2.0, 3.0, 3.5, 4.0]),
)

# INVALID / missing ratios that MUST fall back to the deterministic default:
#   * None                         (missing)                 -> Requirement 3.2
#   * floats <= 0 (incl. 0.0, -0.0, negatives)               -> Requirement 3.3
#   * NaN / +inf / -inf            (non-finite)              -> Scenario 6
#   * booleans     (bool rejected even though True == 1)     -> validator branch
#   * non-numeric text                                        -> Requirement 3.3
_invalid_ratios = st.one_of(
    st.none(),
    st.floats(max_value=0.0, allow_nan=False, allow_infinity=False),
    st.sampled_from([float("nan"), float("inf"), float("-inf")]),
    st.booleans(),
    st.text(max_size=8),
)


# ─── Zone / maxima generators ────────────────────────────────────────────────

@st.composite
def _zones_with(draw, ratio_strategy):
    """Generate an arbitrary VALID ``ZoneAggregate`` whose ``travel_time_ratio``
    is drawn from ``ratio_strategy``.

    Every other field is generated freely (category counts bounded by
    ``total_records``) so the property holds "for any zone" — proving the
    traffic-degradation result depends solely on the ratio, not on counts,
    maxima, or junction flags.
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
        travel_time_ratio=draw(ratio_strategy),
        station=draw(st.one_of(st.none(), st.text(max_size=12))),
        top_violations=draw(st.lists(st.text(max_size=24), max_size=5).map(tuple)),
    )


@st.composite
def _corpus_maxima(draw):
    """Generate arbitrary non-negative ``CorpusMaxima``, including zero maxima.

    traffic_degradation does not depend on the maxima, so they are randomized to
    confirm that independence.
    """
    maximum = st.one_of(
        st.just(0.0),
        st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    )
    return CorpusMaxima(
        max_lane_load=draw(maximum),
        max_junction_load=draw(maximum),
        max_access_count=draw(maximum),
        max_mean_obstruction=draw(maximum),
    )


# A fixed, representative zone reused by the explicit ``@example`` cases; only its
# travel_time_ratio is varied via ``dataclasses.replace``.
_BASE_ZONE = ZoneAggregate(
    h3_id="prop6",
    time_bucket="all_day",
    total_records=100,
    main_road_count=20,
    double_park_count=10,
    junction_violation_count=15,
    access_violation_count=8,
    mean_vehicle_obstruction=1.2,
    has_named_junction=True,
    travel_time_ratio=None,  # overridden per example
    station="TestStation",
    top_violations=(),
)
_BASE_MAXIMA = CorpusMaxima(
    max_lane_load=50.0,
    max_junction_load=40.0,
    max_access_count=30.0,
    max_mean_obstruction=2.0,
)


# ─── Property 6a: valid ratio -> clamped linear value, not defaulted ─────────

@settings(max_examples=200, deadline=None)
@given(z=_zones_with(_valid_ratios), m=_corpus_maxima())
# below 1.0 -> 0.0:
@example(z=replace(_BASE_ZONE, travel_time_ratio=0.5), m=_BASE_MAXIMA)
# exactly 1.0 (boundary) -> 0.0:
@example(z=replace(_BASE_ZONE, travel_time_ratio=1.0), m=_BASE_MAXIMA)
# mid-range -> 0.5:
@example(z=replace(_BASE_ZONE, travel_time_ratio=2.0), m=_BASE_MAXIMA)
# exactly 3.0 (boundary) -> 1.0:
@example(z=replace(_BASE_ZONE, travel_time_ratio=3.0), m=_BASE_MAXIMA)
# high ratio -> clamps to 1.0:
@example(z=replace(_BASE_ZONE, travel_time_ratio=4.0), m=_BASE_MAXIMA)
def test_property_6_valid_ratio_is_clamped_linear_and_not_defaulted(z, m):
    """Property 6 (valid branch): traffic_degradation == clamp((ratio-1)/2, 0, 1)
    and the defaulted flag is False.

    Validates: Requirements 3.1, 3.4.
    """
    components = compute_components(z, m)
    degradation = components["traffic_degradation"]

    # Always a finite float in [0, 1].
    _assert_unit_interval(degradation)

    # A valid ratio is NEVER defaulted.
    assert components["defaulted"] is False

    # Matches the independently-computed clamp, within float tolerance.
    expected = _expected_degradation(z.travel_time_ratio)
    assert math.isclose(degradation, expected, rel_tol=0.0, abs_tol=1e-9), (
        f"ratio={z.travel_time_ratio!r}: got {degradation!r}, expected {expected!r}"
    )


# ─── Property 6b: missing / invalid ratio -> 0.5 fallback, defaulted ─────────

@settings(max_examples=200, deadline=None)
@given(z=_zones_with(_invalid_ratios), m=_corpus_maxima())
@example(z=replace(_BASE_ZONE, travel_time_ratio=None), m=_BASE_MAXIMA)     # missing
@example(z=replace(_BASE_ZONE, travel_time_ratio=0.0), m=_BASE_MAXIMA)      # zero
@example(z=replace(_BASE_ZONE, travel_time_ratio=-2.5), m=_BASE_MAXIMA)     # negative
@example(z=replace(_BASE_ZONE, travel_time_ratio=float("nan")), m=_BASE_MAXIMA)   # NaN
@example(z=replace(_BASE_ZONE, travel_time_ratio=float("inf")), m=_BASE_MAXIMA)   # +inf
@example(z=replace(_BASE_ZONE, travel_time_ratio=float("-inf")), m=_BASE_MAXIMA)  # -inf
@example(z=replace(_BASE_ZONE, travel_time_ratio=True), m=_BASE_MAXIMA)     # bool (== 1)
@example(z=replace(_BASE_ZONE, travel_time_ratio="1.5"), m=_BASE_MAXIMA)    # non-numeric
def test_property_6_missing_or_invalid_ratio_defaults_to_half(z, m):
    """Property 6 (fallback branch): a missing / non-positive / non-numeric ratio
    yields traffic_degradation == 0.5 with the defaulted flag True.

    Validates: Requirements 3.2, 3.3, 13.3.
    """
    components = compute_components(z, m)
    degradation = components["traffic_degradation"]

    # Deterministic offline fallback to the documented default (0.5).
    assert degradation == DEFAULT_TRAFFIC_DEGRADATION == 0.5
    assert components["defaulted"] is True

    # Still a finite float in [0, 1].
    _assert_unit_interval(degradation)
