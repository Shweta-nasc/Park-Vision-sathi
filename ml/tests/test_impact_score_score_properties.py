"""
Property-based tests for ``ml.congestion.impact_score.compute_score`` and the
canonical ``WEIGHTS`` constant.
==============================================================================

Task 2.5 — score bounds & weight partition.

Covers two correctness properties from the design's "Correctness Properties"
section, testing the canonical weight vector and the pure ``compute_score``
scoring core:

  * **Property 1 — Weights form a partition of unity:** the canonical component
    ``WEIGHTS`` sum to exactly 1.0 (within a 1e-9 tolerance) and contain exactly
    the five expected scored keys with their documented values. Because the
    weights partition unity, ``compute_score`` is a true convex combination: a
    component vector whose five scored entries are all equal to some ``k`` in
    [0, 1] scores exactly ``100 * k``.

  * **Property 2 — Score is bounded and capped:** for ANY component dict — even
    one whose five weighted entries are wildly out of range (large positives up
    to 1e6 and negatives) — ``compute_score`` returns a finite value in the
    closed interval [0, 100], flooring at 0 and capping at 100. For components
    that are all already in [0, 1] (so no capping is needed), the score equals
    ``100 * Σ WEIGHTS[c] · components[c]`` within floating-point tolerance, and
    the reported ``severity`` / ``defaulted`` entries never influence it.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

Framework: Hypothesis (per design "Property Test Library: Hypothesis"), with a
minimum of 100 examples per property (configured to 200 here).

Note on the generators: ``compute_score`` consumes the finite [0, 1] component
values produced by ``compute_components`` (which clamps every component to a
finite unit interval). The score strategies therefore deliberately generate
*finite* floats only — including extreme magnitudes and negatives to exercise
the clamp — but exclude NaN / ±inf, which lie outside the function's input
domain and cannot arise from the real pipeline.
"""

from __future__ import annotations

import math

from hypothesis import example, given, settings
from hypothesis import strategies as st

from ml.congestion.impact_score import (
    SCORE_CAP,
    WEIGHT_SUM_TOLERANCE,
    WEIGHTS,
    compute_score,
)

# The five scored component keys, with their documented canonical weights
# (design Decision 1 / Requirement 1.2). ``severity`` and ``defaulted`` are
# carried in a real components dict but are NOT among the weighted keys.
EXPECTED_WEIGHTS = {
    "lane_blockage":       0.30,
    "intersection_impact": 0.25,
    "traffic_degradation": 0.25,
    "access_blockage":     0.10,
    "vehicle_size":        0.10,
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make(lane, intersection, traffic, access, vehicle, *, severity=0.5, defaulted=False):
    """Build a full components dict with the five weighted keys plus diagnostics.

    Mirrors the shape returned by ``compute_components``: the five scored keys
    that ``compute_score`` reads, plus the reported ``severity`` diagnostic and
    the ``defaulted`` flag that it must ignore.
    """
    return {
        "lane_blockage": lane,
        "intersection_impact": intersection,
        "traffic_degradation": traffic,
        "access_blockage": access,
        "vehicle_size": vehicle,
        "severity": severity,
        "defaulted": defaulted,
    }


def _assert_bounded_score(score):
    """Assert ``score`` is a finite ``float`` within the closed interval [0, 100]."""
    assert isinstance(score, float), f"score is not a float: {score!r}"
    assert math.isfinite(score), f"score is not finite (NaN/inf): {score!r}"
    assert 0.0 <= score <= SCORE_CAP, f"score outside [0, {SCORE_CAP}]: {score!r}"


# ─── Hypothesis strategies ───────────────────────────────────────────────────

# In-range component values: the realistic domain produced by compute_components.
_in_range_value = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

# "Arbitrary" component values mixing the in-range band with deliberately
# out-of-range magnitudes (large positives AND negatives) so the floor-at-0 and
# cap-at-100 clamps are both exercised. Finite only (see module docstring).
_arbitrary_value = st.one_of(
    _in_range_value,
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
)

# Arbitrary (finite) severity diagnostic — compute_score must ignore it entirely,
# so it is generated over a wide range to prove that independence.
_arbitrary_severity = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)


@st.composite
def _component_dicts(draw, value_strategy):
    """Generate a full components dict whose five weighted keys are drawn
    independently from ``value_strategy``.

    Each of the five scored keys is drawn separately so a single dict can mix
    in-range, extreme-positive, and negative entries. ``severity`` and
    ``defaulted`` are populated with arbitrary values they should not affect.
    """
    components = {name: draw(value_strategy) for name in WEIGHTS}
    components["severity"] = draw(_arbitrary_severity)
    components["defaulted"] = draw(st.booleans())
    return components


# ─── Property 1: weights form a partition of unity ───────────────────────────

def test_property_1_canonical_weights_form_partition_of_unity():
    """Property 1: the canonical WEIGHTS sum to 1.0 (±1e-9) and are exactly the
    five documented scored components with their documented values.

    Validates: Requirements 1.2, 1.3.
    """
    # Exactly the five scored keys — no more, no less.
    assert set(WEIGHTS.keys()) == set(EXPECTED_WEIGHTS.keys())
    assert len(WEIGHTS) == 5

    # Each weight matches its documented canonical value (Requirement 1.2).
    for key, expected in EXPECTED_WEIGHTS.items():
        assert WEIGHTS[key] == expected, f"weight {key!r}: {WEIGHTS[key]!r} != {expected!r}"

    # The weights partition unity within the documented tolerance (Requirement 1.3).
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    assert abs(sum(WEIGHTS.values()) - 1.0) < WEIGHT_SUM_TOLERANCE


@settings(max_examples=200, deadline=None)
@given(k=_in_range_value)
@example(k=0.0)
@example(k=0.5)
@example(k=1.0)
def test_property_1_partition_of_unity_is_a_convex_combination(k):
    """Property 1 (behavioral): because the weights sum to 1.0, a component
    vector whose five scored entries all equal ``k`` scores exactly ``100·k``.

    This is the operational consequence of a partition of unity — the score is a
    true convex combination of the components, so identical components collapse
    to that value scaled to 100.

    Validates: Requirements 1.1, 1.2, 1.3.
    """
    components = _make(k, k, k, k, k, severity=k)
    score = compute_score(components)

    _assert_bounded_score(score)
    assert math.isclose(score, 100.0 * k, rel_tol=1e-9, abs_tol=1e-9), (
        f"k={k!r}: convex combination gave {score!r}, expected {100.0 * k!r}"
    )


# ─── Property 2: score is bounded and capped ─────────────────────────────────

@settings(max_examples=200, deadline=None)
@given(components=_component_dicts(_arbitrary_value))
@example(components=_make(1e6, 1e6, 1e6, 1e6, 1e6))         # extreme high -> cap at 100
@example(components=_make(-1e6, -1e6, -1e6, -1e6, -1e6))    # extreme low  -> floor at 0
@example(components=_make(1e6, -1e6, 1e6, -1e6, 0.5))       # mixed extremes
@example(components=_make(1.0, 1.0, 1.0, 1.0, 1.0))         # exactly the cap (100)
@example(components=_make(0.0, 0.0, 0.0, 0.0, 0.0))         # exactly the floor (0)
def test_property_2_score_is_bounded_and_capped(components):
    """Property 2: for ANY component dict (including extreme / negative entries),
    compute_score returns a finite value in [0, 100].

    Validates: Requirements 1.4, 1.5.
    """
    score = compute_score(components)
    _assert_bounded_score(score)


@settings(max_examples=200, deadline=None)
@given(components=_component_dicts(_in_range_value))
@example(components=_make(0.0, 0.0, 0.0, 0.0, 0.0))         # 0
@example(components=_make(1.0, 1.0, 1.0, 1.0, 1.0))         # 100
@example(components=_make(0.5, 0.5, 0.5, 0.5, 0.5))         # 50
@example(components=_make(1.0, 0.0, 0.0, 0.0, 0.0))         # 30 (lane_blockage weight)
def test_property_2_in_range_score_equals_weighted_sum(components):
    """Property 2 (no-capping branch): when every scored component is already in
    [0, 1], the score equals ``100 · Σ WEIGHTS[c]·components[c]`` within
    tolerance, and the reported severity / defaulted entries never affect it.

    Validates: Requirements 1.1, 1.4, 1.5.
    """
    score = compute_score(components)
    _assert_bounded_score(score)

    expected = 100.0 * sum(WEIGHTS[name] * components[name] for name in WEIGHTS)
    assert math.isclose(score, expected, rel_tol=1e-9, abs_tol=1e-9), (
        f"got {score!r}, expected weighted sum {expected!r}"
    )
