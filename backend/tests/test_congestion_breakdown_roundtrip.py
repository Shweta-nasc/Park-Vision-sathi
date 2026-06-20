"""
Property-based tests for the ``CongestionBreakdown`` contract round-trip.
========================================================================

Task 3.2 — contract round-trip.

Covers one correctness property from the design's "Correctness Properties"
section, testing the typed Pydantic contract in ``backend.app.models`` — the
serialized boundary between the scoring core, the backend, the frontend, and the
self-validating agent:

  * **Property 10 — Contract round-trip:** for any VALID ``CongestionBreakdown``,
    serializing to JSON and deserializing back yields an *equivalent* object
    (Pydantic v2 value equality), with every required field preserved. The
    contract is the wire format consumers depend on, so it must survive a full
    ``model_dump_json()`` -> ``model_validate_json()`` round-trip (and the
    in-memory ``model_dump()`` -> ``model_validate()`` round-trip) without losing
    or altering any field.

**Validates: Requirements 6.1, 6.2, 6.5**

  * Requirement 6.1 — the breakdown carries the CIS value, impact band, five
    components, severity diagnostic, lane-hours estimate, total record count, top
    violations, station, and the H3 identifier; the round-trip preserves each.
  * Requirement 6.2 — components stay in [0, 1] and the CIS stays in [0, 100]
    after the round-trip (validation re-runs on deserialize and still succeeds).
  * Requirement 6.5 — serialize-then-deserialize produces an equivalent object.

Framework: Hypothesis (per the design's "Property Test Library: Hypothesis"),
with a minimum of 100 examples per property (configured to 200 here).

Generator note: every generated instance is VALID by construction — components
in [0, 1], ``congestion_impact`` in [0, 100], ``estimated_lane_hours_blocked``
and ``total_records`` non-negative, ``calibrated_impact`` in [0, 100] or ``None``,
``impact_band`` from the valid set, ``time_bucket`` from the valid set, ``weights``
a dict summing to ~1.0, ``zone_id == h3_id`` (Requirement 9.2), and the
``is_traffic_degradation_defaulted`` flag tied to a missing MapMyIndia ratio
(design validation rule / Requirement 13.3). Float fields are finite (NaN / ±inf
cannot satisfy the contract's bounds and are not representable in JSON), and text
fields are drawn from UTF-8-encodable characters so they cross the JSON boundary
faithfully.
"""

from __future__ import annotations

from hypothesis import example, given, settings
from hypothesis import strategies as st

from backend.app.models import ComponentBreakdown, CongestionBreakdown

# Valid value sets carried on the contract.
VALID_TIME_BUCKETS = ("all_day", "night", "morning_peak", "midday", "afternoon")
VALID_IMPACT_BANDS = ("MINIMAL", "MODERATE", "SEVERE", "CRITICAL")

# The five scored-component keys echoed in ``weights`` (sum == 1.0).
_WEIGHT_KEYS = (
    "lane_blockage",
    "intersection_impact",
    "traffic_degradation",
    "access_blockage",
    "vehicle_size",
)
_CANONICAL_WEIGHTS = {
    "lane_blockage": 0.30,
    "intersection_impact": 0.25,
    "traffic_degradation": 0.25,
    "access_blockage": 0.10,
    "vehicle_size": 0.10,
}


# ─── Hypothesis strategies ───────────────────────────────────────────────────

# JSON-safe text: any UTF-8-encodable code point. This excludes lone surrogates
# (which cannot be represented in JSON / UTF-8 at all) while still exercising a
# broad slice of unicode — including non-ASCII and astral-plane characters — so
# the round-trip is tested on realistic and adversarial-but-representable strings.
_json_safe_text = st.text(st.characters(codec="utf-8"), max_size=24)

# Field-constrained float strategies (all finite — see the module docstring).
_unit_interval = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)
_score = st.floats(
    min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
)
_non_negative = st.floats(
    min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False
)

# Optional fields: each covers both the ``None`` case and a present value.
_optional_lat = st.one_of(
    st.none(),
    st.floats(min_value=-90.0, max_value=90.0, allow_nan=False, allow_infinity=False),
)
_optional_lon = st.one_of(
    st.none(),
    st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False),
)
_optional_ratio = st.one_of(
    st.none(),
    st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
)
_optional_score = st.one_of(st.none(), _score)
_optional_text = st.one_of(st.none(), _json_safe_text)


@st.composite
def _component_breakdowns(draw) -> ComponentBreakdown:
    """Generate a VALID ``ComponentBreakdown`` (every value in [0, 1])."""
    return ComponentBreakdown(
        lane_blockage=draw(_unit_interval),
        intersection_impact=draw(_unit_interval),
        traffic_degradation=draw(_unit_interval),
        access_blockage=draw(_unit_interval),
        vehicle_size=draw(_unit_interval),
        severity=draw(_unit_interval),
    )


@st.composite
def _weight_dicts(draw) -> dict:
    """Generate a ``weights`` echo dict whose values sum to ~1.0.

    Half the time this is the exact canonical weight vector (clean decimals);
    otherwise it is a random non-negative partition normalized to sum to 1.0
    within floating-point tolerance, so the round-trip is exercised on both tidy
    and messy float values.
    """
    if draw(st.booleans()):
        return dict(_CANONICAL_WEIGHTS)
    raw = draw(
        st.lists(
            st.floats(min_value=0.05, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=len(_WEIGHT_KEYS),
            max_size=len(_WEIGHT_KEYS),
        )
    )
    total = sum(raw)
    return {key: value / total for key, value in zip(_WEIGHT_KEYS, raw)}


@st.composite
def _congestion_breakdowns(draw) -> CongestionBreakdown:
    """Generate an arbitrary VALID ``CongestionBreakdown``.

    All field constraints are respected so construction always succeeds:
    ``zone_id == h3_id`` (Requirement 9.2), ``congestion_impact`` in [0, 100],
    components in [0, 1], non-negative lane-hours and record count, a ``weights``
    dict summing to ~1.0, ``impact_band`` / ``time_bucket`` from their valid sets,
    and the ``is_traffic_degradation_defaulted`` flag set True exactly when the
    MapMyIndia ratio is missing (design validation rule / Requirement 13.3).
    """
    h3_id = draw(_json_safe_text)
    ratio = draw(_optional_ratio)
    return CongestionBreakdown(
        zone_id=h3_id,  # zone_id == h3_id for every zone (Requirement 9.2)
        h3_id=h3_id,
        time_bucket=draw(st.sampled_from(VALID_TIME_BUCKETS)),
        lat=draw(_optional_lat),
        lon=draw(_optional_lon),
        congestion_impact=draw(_score),
        impact_band=draw(st.sampled_from(VALID_IMPACT_BANDS)),
        components=draw(_component_breakdowns()),
        weights=draw(_weight_dicts()),
        estimated_lane_hours_blocked=draw(_non_negative),
        total_records=draw(st.integers(min_value=0, max_value=1_000_000)),
        top_violations=draw(st.lists(_json_safe_text, max_size=5)),
        station=draw(_optional_text),
        junction=draw(_optional_text),
        mappls_travel_time_ratio=ratio,
        is_traffic_degradation_defaulted=ratio is None,
        calibrated_impact=draw(_optional_score),
    )


# ─── Representative explicit examples (pin important shapes) ──────────────────

# Fully populated, MapMyIndia ratio present (measured branch, no defaulting).
_FULLY_POPULATED = CongestionBreakdown(
    zone_id="8928308280fffff",
    h3_id="8928308280fffff",
    time_bucket="morning_peak",
    lat=12.9716,
    lon=77.5946,
    congestion_impact=88.7,
    impact_band="CRITICAL",
    components=ComponentBreakdown(
        lane_blockage=0.62,
        intersection_impact=0.55,
        traffic_degradation=0.6,
        access_blockage=0.2,
        vehicle_size=0.35,
        severity=0.525,
    ),
    weights=dict(_CANONICAL_WEIGHTS),
    estimated_lane_hours_blocked=34.25,
    total_records=5838,
    top_violations=["WRONG PARKING", "PARKING IN A MAIN ROAD"],
    station="Upparpet",
    junction="Majestic Circle",
    mappls_travel_time_ratio=1.076,
    is_traffic_degradation_defaulted=False,
    calibrated_impact=90.1,
)

# Missing MapMyIndia ratio -> deterministic 0.5 fallback, flag True, optionals None.
_DEFAULTED_MISSING_RATIO = CongestionBreakdown(
    zone_id="8928308281fffff",
    h3_id="8928308281fffff",
    time_bucket="all_day",
    lat=None,
    lon=None,
    congestion_impact=12.5,
    impact_band="MINIMAL",
    components=ComponentBreakdown(
        lane_blockage=0.0,
        intersection_impact=0.0,
        traffic_degradation=0.5,
        access_blockage=0.0,
        vehicle_size=0.0,
        severity=0.0,
    ),
    weights=dict(_CANONICAL_WEIGHTS),
    estimated_lane_hours_blocked=1.75,
    total_records=3,
    top_violations=[],
    station=None,
    junction=None,
    mappls_travel_time_ratio=None,
    is_traffic_degradation_defaulted=True,
    calibrated_impact=None,
)

# Lower boundary: zeros everywhere, all optionals None, empty collections.
_BOUNDARY_FLOOR = CongestionBreakdown(
    zone_id="89283082803ffff",
    h3_id="89283082803ffff",
    time_bucket="night",
    lat=None,
    lon=None,
    congestion_impact=0.0,
    impact_band="MINIMAL",
    components=ComponentBreakdown(
        lane_blockage=0.0,
        intersection_impact=0.0,
        traffic_degradation=0.0,
        access_blockage=0.0,
        vehicle_size=0.0,
        severity=0.0,
    ),
    weights=dict(_CANONICAL_WEIGHTS),
    estimated_lane_hours_blocked=0.0,
    total_records=0,
    top_violations=[],
    station=None,
    junction=None,
    mappls_travel_time_ratio=None,
    is_traffic_degradation_defaulted=True,
    calibrated_impact=None,
)

# Upper boundary: maxed components/score, all optionals present at their bounds.
_BOUNDARY_CEILING = CongestionBreakdown(
    zone_id="89283082807ffff",
    h3_id="89283082807ffff",
    time_bucket="afternoon",
    lat=90.0,
    lon=180.0,
    congestion_impact=100.0,
    impact_band="CRITICAL",
    components=ComponentBreakdown(
        lane_blockage=1.0,
        intersection_impact=1.0,
        traffic_degradation=1.0,
        access_blockage=1.0,
        vehicle_size=1.0,
        severity=1.0,
    ),
    weights=dict(_CANONICAL_WEIGHTS),
    estimated_lane_hours_blocked=1_000_000.0,
    total_records=1_000_000,
    top_violations=["A", "B", "C", "D", "E"],
    station="Central",
    junction="Big Junction",
    mappls_travel_time_ratio=4.0,
    is_traffic_degradation_defaulted=False,
    calibrated_impact=100.0,
)


# ─── Shared assertions ───────────────────────────────────────────────────────

def _assert_round_trip_equivalent(restored: CongestionBreakdown, original: CongestionBreakdown):
    """Assert ``restored`` is an equivalent, field-preserving copy of ``original``.

    Covers Requirement 6.5 (whole-object value equality), Requirement 6.1 (each
    enumerated contract field is preserved through the boundary), and Requirement
    6.2 (the bounded fields still satisfy their declared constraints after the
    round-trip re-validates the data).
    """
    # Requirement 6.5: the contract survives the boundary as an equivalent object.
    assert restored == original, (
        "round-trip produced a non-equivalent CongestionBreakdown:\n"
        f"original={original!r}\nrestored={restored!r}"
    )

    # Requirement 6.1: every enumerated contract field is preserved.
    assert restored.congestion_impact == original.congestion_impact
    assert restored.impact_band == original.impact_band
    assert restored.components == original.components
    assert restored.components.severity == original.components.severity
    assert restored.weights == original.weights
    assert restored.estimated_lane_hours_blocked == original.estimated_lane_hours_blocked
    assert restored.total_records == original.total_records
    assert restored.top_violations == original.top_violations
    assert restored.station == original.station
    assert restored.h3_id == original.h3_id
    assert restored.zone_id == original.zone_id
    # MapMyIndia validation fields and the defaulted flag (Requirement 6.4 / 13.3).
    assert restored.mappls_travel_time_ratio == original.mappls_travel_time_ratio
    assert (
        restored.is_traffic_degradation_defaulted
        == original.is_traffic_degradation_defaulted
    )

    # Requirement 6.2: bounded fields remain within their declared constraints.
    assert 0.0 <= restored.congestion_impact <= 100.0
    for name in _WEIGHT_KEYS + ("severity",):
        value = getattr(restored.components, name)
        assert 0.0 <= value <= 1.0, f"component {name!r} outside [0, 1] after round-trip: {value!r}"


# ─── Property 10: JSON round-trip ────────────────────────────────────────────

@settings(max_examples=200, deadline=None)
@given(breakdown=_congestion_breakdowns())
@example(breakdown=_FULLY_POPULATED)
@example(breakdown=_DEFAULTED_MISSING_RATIO)
@example(breakdown=_BOUNDARY_FLOOR)
@example(breakdown=_BOUNDARY_CEILING)
def test_property_10_json_round_trip_preserves_breakdown(breakdown):
    """Property 10: ``model_validate_json(model_dump_json())`` returns an
    equivalent ``CongestionBreakdown`` with all required fields preserved.

    This is the real serialized boundary to the frontend and the agent, so a
    failure here means a field is lost or altered crossing JSON.

    Validates: Requirements 6.1, 6.2, 6.5.
    """
    restored = CongestionBreakdown.model_validate_json(breakdown.model_dump_json())
    _assert_round_trip_equivalent(restored, breakdown)


# ─── Property 10: dict round-trip (lossless, complementary check) ────────────

@settings(max_examples=200, deadline=None)
@given(breakdown=_congestion_breakdowns())
@example(breakdown=_FULLY_POPULATED)
@example(breakdown=_DEFAULTED_MISSING_RATIO)
@example(breakdown=_BOUNDARY_FLOOR)
@example(breakdown=_BOUNDARY_CEILING)
def test_property_10_dict_round_trip_preserves_breakdown(breakdown):
    """Property 10 (dict form): ``model_validate(model_dump())`` returns an
    equivalent ``CongestionBreakdown``.

    The Python-object round-trip carries no serialization loss, so it isolates
    the contract's structural fidelity (nested ``ComponentBreakdown``, the
    ``weights`` dict, optional fields) from any JSON text-encoding concern.

    Validates: Requirements 6.1, 6.2, 6.5.
    """
    restored = CongestionBreakdown.model_validate(breakdown.model_dump())
    _assert_round_trip_equivalent(restored, breakdown)
