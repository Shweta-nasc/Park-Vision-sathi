"""
Property-based tests for the determinism of ``ml.congestion.impact_score``.
===========================================================================

Task 2.10 — determinism.

Covers one correctness property from the design's "Correctness Properties"
section, testing the pure scoring core end to end via ``score_zone(z, m)`` (and
its building blocks ``compute_components`` / ``compute_score``):

  * **Property 5 — Determinism:** for any fixed inputs, scoring twice yields
    identical ``CongestionBreakdown`` values — no randomness, clock, or network
    influences the result. The scoring functions are pure: every output is
    derived solely from the ``ZoneAggregate`` / ``CorpusMaxima`` handed in, so
    the observable consequence is that (a) repeated calls on the SAME inputs
    return equal results, and (b) a fresh ``ZoneAggregate`` / ``CorpusMaxima``
    built from identical field values (a distinct object, not the same identity)
    produces an equal result. Because the float arithmetic is the identical
    sequence of operations on identical inputs, the results are bit-identical, so
    plain ``==`` equality holds across the whole breakdown — including the nested
    ``components`` and the echoed ``weights``.

``score_zone`` returns a typed ``CongestionBreakdown`` (Pydantic) mirroring the
design's contract; the model provides value-based equality, so the whole-
breakdown ``==`` checks below still hold, while the nested-field checks read
attributes (``.components`` / ``.weights`` / ``.congestion_impact``) rather than
dict keys.

**Validates: Requirements 7.1, 7.2**

Framework: Hypothesis (per design "Property Test Library: Hypothesis"), with a
minimum of 100 examples per property (configured to 200 here).
"""

from __future__ import annotations

from dataclasses import fields, replace

from hypothesis import example, given, settings
from hypothesis import strategies as st

from ml.congestion.impact_score import (
    CorpusMaxima,
    ZoneAggregate,
    compute_components,
    compute_score,
    score_zone,
)

TIME_BUCKETS = ("all_day", "night", "morning_peak", "midday", "afternoon")

# Nested keys that must be value-equal across runs — the places float
# nondeterminism would surface first.
NESTED_KEYS = ("components", "weights")


# ─── Hypothesis strategies (mirroring the sibling scorer property suites) ────

# travel_time_ratio: None (missing -> deterministic fallback) OR a positive ratio
# spanning free-flow through heavy congestion. (Design generator: {None} ∪ [0.5, 4.0].)
_travel_time_ratio = st.one_of(
    st.none(),
    st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
)

# Non-negative corpus maxima that EXPLICITLY include exactly 0.0, so the
# determinism check also covers the guarded zero-maxima path.
_non_negative_maximum = st.one_of(
    st.just(0.0),
    st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
)


@st.composite
def _zone_aggregates(draw):
    """Generate an arbitrary VALID ``ZoneAggregate``.

    ``total_records`` is drawn first; each category count is then bounded to
    ``[0, total_records]`` to honor the design precondition that no category
    count exceeds the zone total. ``mean_vehicle_obstruction`` is drawn from
    [0.5, 2.0] and ``travel_time_ratio`` from {None} ∪ [0.5, 4.0], matching the
    sibling scorer suites.
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


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _clone_by_fields(obj):
    """Rebuild a frozen dataclass instance from its field values.

    Returns a NEW object (distinct ``id``) carrying field-for-field identical
    values, so Property 5 is checked across value-equal-but-not-identical inputs
    — proving ``score_zone`` depends only on input *values*, not on object
    identity or any hidden per-instance state.
    """
    cls = type(obj)
    return cls(**{f.name: getattr(obj, f.name) for f in fields(obj)})


# Representative fixtures for the explicit ``@example`` cases.
_BASE_ZONE = ZoneAggregate(
    h3_id="prop5",
    time_bucket="all_day",
    total_records=5838,
    main_road_count=620,
    double_park_count=180,
    junction_violation_count=410,
    access_violation_count=300,
    mean_vehicle_obstruction=1.05,
    has_named_junction=True,
    travel_time_ratio=1.076,
    station="Upparpet",
    top_violations=("WRONG PARKING", "PARKING IN A MAIN ROAD"),
)
_BASE_MAXIMA = CorpusMaxima(
    max_lane_load=1200.0,
    max_junction_load=900.0,
    max_access_count=600.0,
    max_mean_obstruction=1.8,
)
_ZERO_MAXIMA = CorpusMaxima(
    max_lane_load=0.0,
    max_junction_load=0.0,
    max_access_count=0.0,
    max_mean_obstruction=0.0,
)


# ─── Property 5a: repeated calls on the same inputs are identical ────────────

@settings(max_examples=200, deadline=None)
@given(z=_zone_aggregates(), m=_corpus_maxima())
# valid MapMyIndia ratio (measured branch):
@example(z=_BASE_ZONE, m=_BASE_MAXIMA)
# missing ratio -> deterministic 0.5 fallback branch:
@example(z=replace(_BASE_ZONE, travel_time_ratio=None), m=_BASE_MAXIMA)
# all-zero corpus maxima -> guarded-denominator branch:
@example(z=_BASE_ZONE, m=_ZERO_MAXIMA)
def test_property_5_score_zone_identical_across_repeated_calls(z, m):
    """Property 5: ``score_zone`` called three times on the SAME inputs returns
    breakdowns that are exactly equal, including the nested ``components`` and the
    echoed ``weights`` (so no float nondeterminism leaks in).

    Validates: Requirements 7.1, 7.2.
    """
    r1 = score_zone(z, m)
    r2 = score_zone(z, m)
    r3 = score_zone(z, m)

    # Whole-breakdown value equality across all three runs.
    assert r1 == r2, f"score_zone not deterministic across calls 1 and 2:\n{r1!r}\n{r2!r}"
    assert r2 == r3, f"score_zone not deterministic across calls 2 and 3:\n{r2!r}\n{r3!r}"
    assert r1 == r3, f"score_zone not deterministic across calls 1 and 3:\n{r1!r}\n{r3!r}"

    # Explicit nested equality — the first place float nondeterminism would show.
    # score_zone now returns a CongestionBreakdown model, so read fields via
    # attribute access (getattr for the looped keys) rather than dict subscripting.
    for key in NESTED_KEYS:
        assert getattr(r1, key) == getattr(r2, key) == getattr(r3, key), (
            f"nested {key!r} differs across runs"
        )

    # Scalar floats must be bit-identical, not merely close.
    assert r1.congestion_impact == r2.congestion_impact == r3.congestion_impact
    assert (
        r1.estimated_lane_hours_blocked
        == r2.estimated_lane_hours_blocked
        == r3.estimated_lane_hours_blocked
    )


# ─── Property 5b: result depends only on input values, not identity ──────────

@settings(max_examples=200, deadline=None)
@given(z=_zone_aggregates(), m=_corpus_maxima())
@example(z=_BASE_ZONE, m=_BASE_MAXIMA)
@example(z=replace(_BASE_ZONE, travel_time_ratio=None), m=_BASE_MAXIMA)
@example(z=_BASE_ZONE, m=_ZERO_MAXIMA)
def test_property_5_score_zone_depends_only_on_input_values(z, m):
    """Property 5: a second ``ZoneAggregate`` / ``CorpusMaxima`` rebuilt from
    identical field values (a distinct object, not the same identity) yields a
    ``score_zone`` result equal to the original — value equality, not identity.

    Validates: Requirements 7.1, 7.2.
    """
    z2 = _clone_by_fields(z)
    m2 = _clone_by_fields(m)

    # Distinct objects (not identity) that are nonetheless value-equal.
    assert z2 is not z and m2 is not m
    assert z2 == z and m2 == m

    assert score_zone(z2, m2) == score_zone(z, m), (
        "score_zone differs for value-equal but distinct inputs (non-deterministic):\n"
        f"original={score_zone(z, m)!r}\nclone={score_zone(z2, m2)!r}"
    )


# ─── Property 5c: the underlying helpers are deterministic too ───────────────

@settings(max_examples=200, deadline=None)
@given(z=_zone_aggregates(), m=_corpus_maxima())
@example(z=_BASE_ZONE, m=_BASE_MAXIMA)
@example(z=replace(_BASE_ZONE, travel_time_ratio=None), m=_BASE_MAXIMA)
@example(z=_BASE_ZONE, m=_ZERO_MAXIMA)
def test_property_5_components_and_score_are_deterministic(z, m):
    """Property 5 (building blocks): ``compute_components`` and ``compute_score``
    are themselves deterministic, so the determinism of ``score_zone`` rests on
    deterministic primitives rather than a coincidence of assembly.

    Validates: Requirements 7.1, 7.2.
    """
    c1 = compute_components(z, m)
    c2 = compute_components(z, m)
    assert c1 == c2, f"compute_components not deterministic:\n{c1!r}\n{c2!r}"

    # Scoring the (equal) component dicts must agree, and scoring twice off the
    # same dict must agree — both the inputs and the reduction are deterministic.
    assert compute_score(c1) == compute_score(c2)
    assert compute_score(c1) == compute_score(c1)
