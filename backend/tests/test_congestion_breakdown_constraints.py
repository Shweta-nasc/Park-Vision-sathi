"""
Unit tests for the CIS contract field constraints.
===================================================

Task 3.3 — example-based unit tests (pytest, not Hypothesis) for the typed CIS
contract in ``backend.app.models``: ``ComponentBreakdown`` and
``CongestionBreakdown``. These tests pin the field-level validation rules from
the design's "Data Models -> Validation Rules" section and exercise both the
rejection of out-of-range values and the acceptance of valid boundary values.

Requirements covered:
  * Requirement 6.2 — every component value is constrained to [0, 1] and
    ``congestion_impact`` is constrained to [0, 100]. (Also exercises the
    non-negative ``estimated_lane_hours_blocked`` / ``total_records`` and the
    optional ``calibrated_impact`` in [0, 100] from the same Data Models block.)
  * Requirement 6.3 — the echoed ``weights`` sum to 1.0 within 1e-9, permitting
    any weight distribution that satisfies that sum.
  * Requirement 13.3 — the ``is_traffic_degradation_defaulted`` flag marks when
    the traffic-degradation value was defaulted (ratio missing), so consumers do
    not treat it as a measured signal.

Cross-field validator note (Requirement 13.3 / design validation rule):
  The design lists "``is_traffic_degradation_defaulted`` is True exactly when
  ``mappls_travel_time_ratio is None``" as a validation rule, but the shipped
  ``CongestionBreakdown`` model does NOT implement a cross-field validator tying
  the flag to the ratio (only the per-field ``ge``/``le`` constraints and the
  ``weights`` partition-of-unity validator added in task 3.3 exist). The linkage
  is therefore maintained at the scoring source — ``ml.congestion.impact_score``
  sets both together — rather than enforced by the contract. Accordingly, these
  tests assert that the model independently *accepts* each documented combination
  (the defaulted shape and the measured shape) and explicitly document that the
  inconsistent combinations are also accepted, proving no cross-field rule exists.

Framework: pytest with ``pytest.raises(ValidationError)`` for the rejection cases.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.models import (
    WEIGHT_SUM_TOLERANCE,
    ComponentBreakdown,
    CongestionBreakdown,
)

# ─── Canonical fixtures ──────────────────────────────────────────────────────

# The canonical component weights (a partition of unity); echoed on every
# breakdown for transparency. Built here so the tests are independent of the
# scoring core (`ml.congestion.impact_score.WEIGHTS`).
_CANONICAL_WEIGHTS = {
    "lane_blockage": 0.30,
    "intersection_impact": 0.25,
    "traffic_degradation": 0.25,
    "access_blockage": 0.10,
    "vehicle_size": 0.10,
}

# The six ``ComponentBreakdown`` fields (five scored + the severity diagnostic),
# each constrained to [0, 1] (Requirement 6.2).
_COMPONENT_FIELDS = (
    "lane_blockage",
    "intersection_impact",
    "traffic_degradation",
    "access_blockage",
    "vehicle_size",
    "severity",
)


def _valid_component_kwargs() -> dict:
    """Return kwargs for a valid ``ComponentBreakdown`` (every value in [0, 1])."""
    return {
        "lane_blockage": 0.4,
        "intersection_impact": 0.3,
        "traffic_degradation": 0.5,
        "access_blockage": 0.2,
        "vehicle_size": 0.35,
        "severity": 0.45,
    }


def _make_component(**overrides) -> ComponentBreakdown:
    """Build a ``ComponentBreakdown`` from valid defaults with field overrides."""
    kwargs = _valid_component_kwargs()
    kwargs.update(overrides)
    return ComponentBreakdown(**kwargs)


def _valid_breakdown_kwargs() -> dict:
    """Return kwargs for a valid ``CongestionBreakdown`` (all constraints satisfied)."""
    return {
        "zone_id": "8928308280fffff",
        "h3_id": "8928308280fffff",  # zone_id == h3_id (Requirement 9.2)
        "time_bucket": "all_day",
        "congestion_impact": 50.0,
        "impact_band": "MODERATE",
        "components": _make_component(),
        "weights": dict(_CANONICAL_WEIGHTS),
        "estimated_lane_hours_blocked": 12.5,
        "total_records": 100,
        "top_violations": ["WRONG PARKING"],
        "station": "Upparpet",
        "mappls_travel_time_ratio": 1.2,
        "is_traffic_degradation_defaulted": False,
        "calibrated_impact": 55.0,
    }


def _make_breakdown(**overrides) -> CongestionBreakdown:
    """Build a ``CongestionBreakdown`` from valid defaults with field overrides."""
    kwargs = _valid_breakdown_kwargs()
    kwargs.update(overrides)
    return CongestionBreakdown(**kwargs)


# ─── ComponentBreakdown: out-of-range rejection (Requirement 6.2) ────────────

@pytest.mark.parametrize("field", _COMPONENT_FIELDS)
@pytest.mark.parametrize("bad_value", [-0.1, 1.1])
def test_component_field_out_of_range_rejected(field, bad_value):
    """Each of the six components is rejected below 0 or above 1 (Req 6.2).

    Pydantic's ``ge=0.0``/``le=1.0`` field constraints raise ``ValidationError``
    for any value outside the closed interval [0, 1].
    """
    with pytest.raises(ValidationError):
        _make_component(**{field: bad_value})


@pytest.mark.parametrize("field", _COMPONENT_FIELDS)
@pytest.mark.parametrize("boundary_value", [0.0, 1.0])
def test_component_field_boundary_values_accepted(field, boundary_value):
    """Each component accepts the inclusive boundary values 0.0 and 1.0 (Req 6.2)."""
    component = _make_component(**{field: boundary_value})
    assert getattr(component, field) == boundary_value


# ─── CongestionBreakdown: out-of-range rejection (Requirement 6.2) ───────────

@pytest.mark.parametrize("bad_score", [-1.0, 100.1])
def test_congestion_impact_out_of_range_rejected(bad_score):
    """``congestion_impact`` outside [0, 100] is rejected (Req 6.2)."""
    with pytest.raises(ValidationError):
        _make_breakdown(congestion_impact=bad_score)


@pytest.mark.parametrize("bad_lane_hours", [-0.1, -1.0])
def test_estimated_lane_hours_negative_rejected(bad_lane_hours):
    """Negative ``estimated_lane_hours_blocked`` is rejected (Req 6.2 / Data Models)."""
    with pytest.raises(ValidationError):
        _make_breakdown(estimated_lane_hours_blocked=bad_lane_hours)


@pytest.mark.parametrize("bad_total", [-1, -100])
def test_total_records_negative_rejected(bad_total):
    """Negative ``total_records`` is rejected (Req 6.2 / Data Models)."""
    with pytest.raises(ValidationError):
        _make_breakdown(total_records=bad_total)


@pytest.mark.parametrize("bad_calibrated", [-0.1, 100.1])
def test_calibrated_impact_out_of_range_rejected(bad_calibrated):
    """``calibrated_impact`` outside [0, 100] is rejected (Req 6.2 / Data Models)."""
    with pytest.raises(ValidationError):
        _make_breakdown(calibrated_impact=bad_calibrated)


# ─── CongestionBreakdown: valid boundary acceptance (Requirement 6.2) ────────

@pytest.mark.parametrize("score", [0.0, 100.0])
def test_congestion_impact_boundary_values_accepted(score):
    """``congestion_impact`` accepts the inclusive bounds 0.0 and 100.0 (Req 6.2)."""
    breakdown = _make_breakdown(congestion_impact=score)
    assert breakdown.congestion_impact == score


def test_estimated_lane_hours_zero_accepted():
    """``estimated_lane_hours_blocked`` accepts its inclusive lower bound 0.0."""
    breakdown = _make_breakdown(estimated_lane_hours_blocked=0.0)
    assert breakdown.estimated_lane_hours_blocked == 0.0


def test_total_records_zero_accepted():
    """``total_records`` accepts its inclusive lower bound 0."""
    breakdown = _make_breakdown(total_records=0)
    assert breakdown.total_records == 0


@pytest.mark.parametrize("calibrated", [0.0, 100.0, None])
def test_calibrated_impact_boundaries_and_none_accepted(calibrated):
    """``calibrated_impact`` accepts the bounds 0.0 and 100.0, and ``None``.

    ``None`` is the documented "no calibration record yet" state (Requirement
    6.6); the bounds are the inclusive edges of [0, 100].
    """
    breakdown = _make_breakdown(calibrated_impact=calibrated)
    assert breakdown.calibrated_impact == calibrated


# ─── is_traffic_degradation_defaulted semantics (Requirement 13.3) ───────────

def test_defaulted_shape_accepted():
    """The documented *defaulted* shape is accepted: no MapMyIndia ratio + flag True.

    Per Requirement 13.3 and the design, when ``mappls_travel_time_ratio is None``
    the traffic-degradation value was defaulted, so the flag is True and the
    component carries the deterministic 0.5 fallback. The contract accepts this
    shape (the fields are validated independently — see the cross-field note below).
    """
    breakdown = _make_breakdown(
        components=_make_component(traffic_degradation=0.5),
        mappls_travel_time_ratio=None,
        is_traffic_degradation_defaulted=True,
    )
    assert breakdown.mappls_travel_time_ratio is None
    assert breakdown.is_traffic_degradation_defaulted is True
    assert breakdown.components.traffic_degradation == 0.5


def test_measured_shape_accepted():
    """The documented *measured* shape is accepted: a real ratio + flag False.

    When a valid MapMyIndia ratio is present the traffic-degradation value is
    measured, so ``is_traffic_degradation_defaulted`` is False (Requirement 13.3).
    """
    breakdown = _make_breakdown(
        components=_make_component(traffic_degradation=0.25),
        mappls_travel_time_ratio=1.5,
        is_traffic_degradation_defaulted=False,
    )
    assert breakdown.mappls_travel_time_ratio == 1.5
    assert breakdown.is_traffic_degradation_defaulted is False


@pytest.mark.parametrize(
    "ratio, flag",
    [
        (None, False),   # ratio missing but flag says "measured"
        (1.5, True),     # ratio present but flag says "defaulted"
    ],
)
def test_flag_and_ratio_are_not_cross_validated(ratio, flag):
    """No cross-field validator ties the flag to the ratio (documented behavior).

    The design lists "the flag is True exactly when the ratio is None" as a
    validation rule, but the shipped ``CongestionBreakdown`` does NOT enforce it:
    there is no model/field validator linking these two fields. This test pins
    that fact by constructing the inconsistent combinations and asserting they are
    accepted. The flag/ratio linkage is upheld at the scoring source
    (``ml.congestion.impact_score.score_zone`` sets both together), not by the
    contract. If a cross-field validator is ever added, this test should be
    updated to expect rejection of these combinations.
    """
    breakdown = _make_breakdown(
        mappls_travel_time_ratio=ratio,
        is_traffic_degradation_defaulted=flag,
    )
    assert breakdown.mappls_travel_time_ratio == ratio
    assert breakdown.is_traffic_degradation_defaulted is flag


# ─── weights echo: partition of unity (Requirement 6.3) ──────────────────────

def test_valid_breakdown_weights_sum_to_one():
    """A valid breakdown carries a ``weights`` dict summing to 1.0 within 1e-9 (Req 6.3)."""
    breakdown = _make_breakdown()
    assert abs(sum(breakdown.weights.values()) - 1.0) < 1e-9


def test_canonical_weights_echo_accepted():
    """The canonical weight vector is a valid echo (sums to 1.0)."""
    breakdown = _make_breakdown(weights=dict(_CANONICAL_WEIGHTS))
    assert abs(sum(breakdown.weights.values()) - 1.0) < WEIGHT_SUM_TOLERANCE


def test_alternative_partition_of_unity_accepted():
    """Any weight distribution summing to 1.0 is accepted, not only the canonical one.

    Requirement 6.3 permits "any weight distribution that satisfies this sum", so
    an equal 0.2-each split (which also sums to 1.0) must be accepted.
    """
    equal_split = {key: 0.2 for key in _CANONICAL_WEIGHTS}
    breakdown = _make_breakdown(weights=equal_split)
    assert abs(sum(breakdown.weights.values()) - 1.0) < WEIGHT_SUM_TOLERANCE


@pytest.mark.parametrize(
    "bad_weights",
    [
        {  # sums to 0.90 — below 1.0 beyond tolerance
            "lane_blockage": 0.30,
            "intersection_impact": 0.25,
            "traffic_degradation": 0.25,
            "access_blockage": 0.10,
            "vehicle_size": 0.00,
        },
        {  # sums to 1.20 — above 1.0 beyond tolerance
            "lane_blockage": 0.40,
            "intersection_impact": 0.30,
            "traffic_degradation": 0.25,
            "access_blockage": 0.15,
            "vehicle_size": 0.10,
        },
        {},  # empty echo sums to 0.0
    ],
)
def test_weights_not_summing_to_one_rejected(bad_weights):
    """A ``weights`` echo that does not sum to 1.0 within 1e-9 is rejected (Req 6.3).

    Exercises the partition-of-unity validator added to ``CongestionBreakdown`` in
    task 3.3.
    """
    with pytest.raises(ValidationError):
        _make_breakdown(weights=bad_weights)
