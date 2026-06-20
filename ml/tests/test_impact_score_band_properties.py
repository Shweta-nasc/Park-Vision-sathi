"""
Property-based tests for ``ml.congestion.impact_score.impact_band``.
====================================================================

Task 2.6 — banding.

Covers one correctness property from the design's "Correctness Properties"
section, testing the pure ``impact_band(score)`` scoring core:

  * **Property 4 — Band matches score:** for any score in [0, 100],
    ``impact_band`` returns one of MINIMAL / MODERATE / SEVERE / CRITICAL per the
    **right-closed** thresholds, and the band always equals an independently
    re-derived expectation. Bands are right-closed (the upper bound belongs to
    the lower band):

        score <= 25  -> MINIMAL    (Requirement 4.1)
        score <= 50  -> MODERATE   (Requirement 4.2)
        score <= 75  -> SEVERE     (Requirement 4.3)
        score  > 75  -> CRITICAL   (Requirement 4.4)

    So the exact boundaries 25.0, 50.0, and 75.0 fall into MINIMAL, MODERATE,
    and SEVERE respectively (Requirement 4.5). The function is also exercised on
    values slightly outside [0, 100] to confirm sane behavior: any negative
    score lands in MINIMAL and any large score (> 75) lands in CRITICAL.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**

Framework: Hypothesis (per design "Property Test Library: Hypothesis"), with a
minimum of 100 examples per property (configured to 200 here).

Note on the oracle: ``_expected_band`` re-derives the right-closed rule directly
from the requirement thresholds (literal 25 / 50 / 75 with ``<=`` comparisons),
independently of the module's tuple-driven ``BAND_THRESHOLDS`` implementation, so
the test asserts agreement with the spec rather than restating the production
code.
"""

from __future__ import annotations

from hypothesis import example, given, settings
from hypothesis import strategies as st

from ml.congestion.impact_score import impact_band

# The complete, ordered set of valid band labels (lowest to highest impact).
VALID_BANDS = ("MINIMAL", "MODERATE", "SEVERE", "CRITICAL")


# ─── Expected-value oracle (re-derived independently from the requirements) ──

def _expected_band(score: float) -> str:
    """The expected band for ``score`` under the right-closed threshold rule.

    Re-derived directly from Requirements 4.1-4.4 with literal thresholds and
    inclusive upper bounds, deliberately *not* importing the module's band
    constants, so the assertion checks the production code against the spec
    rather than against itself. Defined over the whole real line: negatives fall
    into MINIMAL and large values into CRITICAL, which is exactly the "sane
    behavior" expected just outside [0, 100].
    """
    if score <= 25.0:
        return "MINIMAL"
    if score <= 50.0:
        return "MODERATE"
    if score <= 75.0:
        return "SEVERE"
    return "CRITICAL"


# ─── Hypothesis strategies ───────────────────────────────────────────────────

# The in-domain range: finite scores across the full [0, 100] CIS interval.
_in_range_score = st.floats(
    min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
)

# Slightly-outside scores to confirm sane behavior: negatives (down to -200) and
# above-100 values (up to 200). Finite only — NaN/inf are outside the domain of a
# numeric CIS and cannot arise from compute_score.
_out_of_range_score = st.one_of(
    st.floats(min_value=-200.0, max_value=0.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=100.0, max_value=200.0, allow_nan=False, allow_infinity=False),
)


# ─── Property 4: band matches score (in [0, 100]) ────────────────────────────

@settings(max_examples=200, deadline=None)
@given(score=_in_range_score)
@example(score=0.0)       # floor -> MINIMAL
@example(score=25.0)      # right-closed boundary -> MINIMAL
@example(score=25.0001)   # just above -> MODERATE
@example(score=50.0)      # right-closed boundary -> MODERATE
@example(score=50.0001)   # just above -> SEVERE
@example(score=75.0)      # right-closed boundary -> SEVERE
@example(score=75.0001)   # just above -> CRITICAL
@example(score=100.0)     # cap -> CRITICAL
def test_property_4_band_matches_score(score):
    """Property 4: for any score in [0, 100], ``impact_band`` returns a valid
    label equal to the independently re-derived right-closed expectation.

    The explicit ``@example`` cases pin every band boundary (25.0/50.0/75.0 and
    just above each) plus the [0, 100] endpoints.

    Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5.
    """
    band = impact_band(score)

    assert band in VALID_BANDS, f"score={score!r}: {band!r} is not a valid band"
    assert band == _expected_band(score), (
        f"score={score!r}: got {band!r}, expected {_expected_band(score)!r}"
    )


# ─── Property 4 (sanity just outside [0, 100]) ───────────────────────────────

@settings(max_examples=200, deadline=None)
@given(score=_out_of_range_score)
@example(score=-0.0001)    # just below floor -> MINIMAL
@example(score=-50.0)      # negative -> MINIMAL
@example(score=-1e9)       # extreme negative -> MINIMAL
@example(score=100.0001)   # just above cap -> CRITICAL
@example(score=150.0)      # large -> CRITICAL
@example(score=1e9)        # extreme large -> CRITICAL
def test_property_4_out_of_range_scores_are_sane(score):
    """Property 4 (robustness): for scores slightly outside [0, 100], the band
    still equals the right-closed expectation — negatives map to MINIMAL and
    large values (> 75) map to CRITICAL.

    Validates: Requirements 4.1, 4.4.
    """
    band = impact_band(score)

    assert band in VALID_BANDS, f"score={score!r}: {band!r} is not a valid band"
    assert band == _expected_band(score), (
        f"score={score!r}: got {band!r}, expected {_expected_band(score)!r}"
    )

    # Explicit directional sanity checks called out by the property.
    if score < 0.0:
        assert band == "MINIMAL", f"negative score={score!r} should be MINIMAL, got {band!r}"
    if score > 75.0:
        assert band == "CRITICAL", f"large score={score!r} should be CRITICAL, got {band!r}"


# ─── Exact boundary pins (literal expected labels, oracle-independent) ────────

def test_impact_band_exact_boundary_values():
    """Pin every band boundary to its exact expected label with literal values.

    Complements the property tests by hard-coding the right-closed mapping at and
    just above each threshold (and the [0, 100] endpoints), guarding the precise
    boundary semantics independently of the ``_expected_band`` oracle.

    Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5.
    """
    cases = [
        (0.0, "MINIMAL"),
        (25.0, "MINIMAL"),
        (25.0001, "MODERATE"),
        (50.0, "MODERATE"),
        (50.0001, "SEVERE"),
        (75.0, "SEVERE"),
        (75.0001, "CRITICAL"),
        (100.0, "CRITICAL"),
    ]
    for score, expected in cases:
        assert impact_band(score) == expected, (
            f"score={score!r}: expected {expected!r}, got {impact_band(score)!r}"
        )
