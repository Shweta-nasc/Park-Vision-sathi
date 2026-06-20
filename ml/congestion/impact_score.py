"""
ParkVision-Saathi — Congestion Impact Score (CIS): scoring core
================================================================

The "QUANTIFY" pillar of ParkVision-Saathi. CIS is a deterministic, transparent
**0-100 proxy score**, computed per H3 zone and per time bucket, that estimates
how much a parking-violation pattern degrades traffic flow — explicitly distinct
from raw violation counts.

This module is the pure, deterministic scoring core. It performs **no I/O, no
network, no LLM, and no database access** — it operates only on the aggregates
handed to it, so identical inputs always produce identical outputs. The offline
artifact builder (``ml/congestion/build_artifact.py``) feeds it; the FastAPI
backend never recomputes CIS at request time.

CIS is the weighted sum of five normalized components (weights summing to 1.0),
scaled to 100 and capped at 100. A sixth ``severity`` value is reported as a
transparency diagnostic but is deliberately **excluded** from the weighted sum
so the weights remain a clean partition of unity.

This file (task 1) defines the canonical constants and the typed input
contracts only. The scoring functions (``compute_components``, ``compute_score``,
``impact_band``, ``estimate_lane_hours``, ``score_zone``) are implemented in the
subsequent tasks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# The typed CIS contract lives in the backend's import-light models module
# (pydantic + typing only, no `ml` or FastAPI-app imports), so importing it here
# introduces no circular dependency back into `ml.*` and keeps the scoring core
# safe to import in any context. `score_zone` returns `CongestionBreakdown`; the
# other primitives keep returning plain stdlib types.
from backend.app.models import ComponentBreakdown, CongestionBreakdown

# ─── Canonical component weights ─────────────────────────────────────────────
#
# CIS = SCORE_CAP * Σ (WEIGHTS[c] · component[c]) for the five scored components.
# The weights MUST form a partition of unity (sum to 1.0) so that CIS is a true
# convex combination of [0, 1] components and is therefore bounded to [0, 100]
# before capping. The import-time assertion below enforces this invariant.

WEIGHTS: dict[str, float] = {
    "lane_blockage":       0.30,
    "intersection_impact": 0.25,
    "traffic_degradation": 0.25,
    "access_blockage":     0.10,
    "vehicle_size":        0.10,
}

# Tolerance for the weight-sum invariant (Requirements 1.3, 6.3).
WEIGHT_SUM_TOLERANCE = 1e-9

assert abs(sum(WEIGHTS.values()) - 1.0) < WEIGHT_SUM_TOLERANCE, (
    "Canonical CIS component weights must sum to 1.0 "
    f"(got {sum(WEIGHTS.values())!r})."
)

# ─── Scoring constants ───────────────────────────────────────────────────────

# Deterministic offline fallback for the traffic-degradation component, used when
# no valid MapMyIndia travel_time_ratio is available for a zone (Requirements 3.2,
# 3.3).
DEFAULT_TRAFFIC_DEGRADATION = 0.5

# CIS is scaled to this maximum and capped here (Requirement 1.5).
SCORE_CAP = 100.0

# ─── Impact band thresholds ──────────────────────────────────────────────────
#
# Bands are right-closed (the upper bound is inclusive):
#   0-25   MINIMAL
#   26-50  MODERATE
#   51-75  SEVERE
#   76-100 CRITICAL
# Matches backend/app/data_loader._band and ml/agent/validation_agent._impact_band.

BAND_MINIMAL_MAX = 25.0
BAND_MODERATE_MAX = 50.0
BAND_SEVERE_MAX = 75.0

# Ordered (inclusive_upper_bound, band_label) pairs applied lowest-first; any score
# above BAND_SEVERE_MAX falls into BAND_CRITICAL.
BAND_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (BAND_MINIMAL_MAX, "MINIMAL"),
    (BAND_MODERATE_MAX, "MODERATE"),
    (BAND_SEVERE_MAX, "SEVERE"),
)
BAND_CRITICAL = "CRITICAL"


# ─── Typed input contracts ───────────────────────────────────────────────────

@dataclass(frozen=True)
class ZoneAggregate:
    """Pre-aggregated violation counts for one ``(h3_id, time_bucket)`` cell.

    This is the immutable input to the scorer. It is produced offline by the
    artifact builder from cleaned violation records; the scorer treats it as the
    sole source of truth (no I/O is performed to enrich it).
    """

    h3_id: str
    time_bucket: str
    total_records: int
    main_road_count: int           # "PARKING IN A MAIN ROAD"
    double_park_count: int         # "DOUBLE PARKING"
    junction_violation_count: int  # road-crossing / traffic-light / zebra
    access_violation_count: int    # bus stop / school / hospital / footpath
    mean_vehicle_obstruction: float  # mean obstruction weight in [0.5, 2.0]
    has_named_junction: bool
    travel_time_ratio: Optional[float]  # MapMyIndia ratio; None -> deterministic fallback
    station: Optional[str]
    top_violations: tuple[str, ...]


@dataclass(frozen=True)
class CorpusMaxima:
    """Per-corpus maxima used to normalize the count-based components to [0, 1].

    Each maximum is the largest observed value of its quantity across every scored
    zone in the corpus, so dividing a zone's raw value by it maps the corpus
    maximum to 1.0. A maximum of 0 means the corpus contains no such violations;
    the scorer guards every denominator so this never raises a division error.
    """

    max_lane_load: float
    max_junction_load: float
    max_access_count: float
    max_mean_obstruction: float


# ─── Pure helpers ────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp ``value`` into the closed interval ``[lo, hi]`` (default ``[0, 1]``).

    Used to bound every component. Because it enforces both ends, it subsumes the
    design's ``MIN(x, 1.0)`` cap while also flooring any spurious negative input
    (e.g. malformed counts) at 0, honoring "constrain each component to [0, 1]"
    (Requirement 2.5).
    """
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _is_valid_travel_time_ratio(ratio: object) -> bool:
    """Return True iff ``ratio`` is a usable MapMyIndia travel-time ratio.

    A ratio is usable only when it is a finite, strictly-positive real number.
    ``None``, booleans, non-numeric types, non-finite values (NaN / ±inf), and
    values ``<= 0`` are all treated as missing, so the caller falls back to the
    deterministic ``DEFAULT_TRAFFIC_DEGRADATION`` (Requirements 3.2, 3.3; design
    Error-Handling Scenario 6).
    """
    # bool is a subclass of int; a True/False "ratio" is meaningless data, reject it.
    if ratio is None or isinstance(ratio, bool):
        return False
    if not isinstance(ratio, (int, float)):
        return False
    if not math.isfinite(float(ratio)):  # NaN / +inf / -inf
        return False
    return ratio > 0.0


# ─── Component computation ───────────────────────────────────────────────────

def compute_components(z: ZoneAggregate, m: CorpusMaxima) -> dict:
    """Compute the five weighted components, the severity diagnostic, and flag.

    Returns a ``dict`` whose keys match :data:`WEIGHTS` exactly for the five
    scored components, plus ``severity`` (a reported diagnostic that is *not*
    folded into the weighted score) and ``defaulted`` (True when the
    traffic-degradation value fell back to :data:`DEFAULT_TRAFFIC_DEGRADATION`):

        {
            "lane_blockage":       float in [0, 1],
            "intersection_impact": float in [0, 1],
            "traffic_degradation": float in [0, 1],
            "access_blockage":     float in [0, 1],
            "vehicle_size":        float in [0, 1],
            "severity":            float in [0, 1],   # diagnostic, NOT weighted
            "defaulted":           bool,
        }

    Keying the scored components by their :data:`WEIGHTS` names lets
    ``compute_score`` (task 2.4) take the weighted sum directly and lets
    ``score_zone`` (task 2.9) build the ``ComponentBreakdown`` without remapping.

    Normalization (Requirement 2.7): each count-based component divides the raw
    value by the per-corpus maximum so the corpus maximum maps to 1.0; the
    junction-boosted ``intersection_impact`` and the derived
    ``traffic_degradation`` can exceed 1.0 before clamping. Every denominator is
    guarded — ``max(value, 1)`` for counts and ``max(value, 1e-9)`` for the
    obstruction mean — so a zero corpus maximum (Requirement 14.2) yields a finite
    component in [0, 1] with no division error. This function is pure: no I/O, no
    randomness, no clock, no network.
    """
    # Component 1 — lane blockage (weight 0.30). Double-parking is weighted twice
    # as heavily as a main-road violation; normalized against the corpus's busiest
    # lane load. (Requirement 2.1)
    lane_load = z.main_road_count * 1.0 + z.double_park_count * 2.0
    lane_blockage = _clamp(lane_load / max(m.max_lane_load, 1))

    # Component 2 — intersection impact (weight 0.25), boosted 1.5x at a named
    # junction and damped to 0.5x otherwise; the boost can push the normalized
    # value above 1.0, so it is clamped. (Requirement 2.2)
    junction_factor = 1.5 if z.has_named_junction else 0.5
    junction_norm = z.junction_violation_count / max(m.max_junction_load, 1)
    intersection_impact = _clamp(junction_norm * junction_factor)

    # Component 3 — traffic degradation (weight 0.25), the sole externally-measured
    # signal (MapMyIndia). Missing / non-positive / non-numeric ratios fall back to
    # the deterministic default with the defaulted flag set. (Requirements 3.1-3.4)
    if _is_valid_travel_time_ratio(z.travel_time_ratio):
        traffic_degradation = _clamp((z.travel_time_ratio - 1.0) / 2.0)
        defaulted = False
    else:
        traffic_degradation = DEFAULT_TRAFFIC_DEGRADATION
        defaulted = True

    # Component 4 — access blockage (weight 0.10): bus-stop / school / hospital /
    # footpath obstruction, normalized against the corpus maximum. (Requirement 2.3)
    access_blockage = _clamp(z.access_violation_count / max(m.max_access_count, 1))

    # Component 5 — vehicle size (weight 0.10): mean obstruction weight normalized
    # against the corpus maximum mean obstruction (guarded with 1e-9 because the
    # mean is a small float, not a count). (Requirement 2.4)
    vehicle_size = _clamp(z.mean_vehicle_obstruction / max(m.max_mean_obstruction, 1e-9))

    # Diagnostic — severity: normalized mean per-violation severity in [0, 1],
    # REPORTED for transparency but deliberately excluded from the weighted score
    # (folding happens later in compute_score over the five weighted components
    # only). (Requirement 2.6)
    severity = _clamp(z.mean_vehicle_obstruction / 2.0)

    return {
        "lane_blockage": lane_blockage,
        "intersection_impact": intersection_impact,
        "traffic_degradation": traffic_degradation,
        "access_blockage": access_blockage,
        "vehicle_size": vehicle_size,
        "severity": severity,
        "defaulted": defaulted,
    }


# ─── Score aggregation and banding ───────────────────────────────────────────

def compute_score(components: dict) -> float:
    """Combine the five weighted components into the 0-100 CIS value.

    CIS = ``clamp(SCORE_CAP * Σ WEIGHTS[c] · components[c], 0, SCORE_CAP)`` summed
    over the **five scored components only** (the keys of :data:`WEIGHTS`):
    ``lane_blockage``, ``intersection_impact``, ``traffic_degradation``,
    ``access_blockage``, and ``vehicle_size``. The reported ``severity``
    diagnostic and the ``defaulted`` flag carried in the same dict are
    deliberately **not** read, keeping the weights a clean partition of unity and
    the score a true convex combination scaled to 100 (Requirement 1.1).

    Because each component is in [0, 1] and the weights sum to 1.0, the raw
    weighted sum is itself in [0, 1] and the scaled value lands in [0, 100]; the
    final clamp still floors the result at 0 (Requirement 1.4) and caps it at
    :data:`SCORE_CAP` (Requirement 1.5), so the score stays bounded even if a
    caller passes a component slightly outside [0, 1].

    Pure function: no I/O, randomness, clock, or network — identical ``components``
    always yield an identical score.

    :param components: the mapping returned by :func:`compute_components`; only the
        five :data:`WEIGHTS` keys are read (``severity``/``defaulted`` are ignored).
    :returns: the Congestion Impact Score in the closed interval ``[0, SCORE_CAP]``.
    """
    raw = sum(weight * components[name] for name, weight in WEIGHTS.items())
    return _clamp(raw * SCORE_CAP, 0.0, SCORE_CAP)


def impact_band(score: float) -> str:
    """Classify a 0-100 CIS value into its impact band.

    Thresholds are **right-closed** (each upper bound belongs to the lower band),
    applied lowest-first from :data:`BAND_THRESHOLDS`:

        ``score <= 25`` -> ``"MINIMAL"``   (Requirement 4.1)
        ``score <= 50`` -> ``"MODERATE"``  (Requirement 4.2)
        ``score <= 75`` -> ``"SEVERE"``    (Requirement 4.3)
        otherwise       -> ``"CRITICAL"``  (Requirement 4.4)

    So the exact boundaries 25.0, 50.0, and 75.0 fall into MINIMAL, MODERATE, and
    SEVERE respectively. This matches ``backend/app/data_loader._band`` and
    ``ml/agent/validation_agent._impact_band`` (Requirement 4.5).

    Pure function: deterministic, with no I/O or side effects.

    :param score: a Congestion Impact Score, normally in ``[0, 100]``.
    :returns: one of ``"MINIMAL"``, ``"MODERATE"``, ``"SEVERE"``, ``"CRITICAL"``.
    """
    for upper_bound, band in BAND_THRESHOLDS:
        if score <= upper_bound:
            return band
    return BAND_CRITICAL


# ─── Lane-hours estimate ─────────────────────────────────────────────────────
#
# Per-violation-class lane-hours coefficients (Requirement 5.1). Each weight is a
# rough estimate of the daily lane-hours one violation of that class blocks: a
# double-parked vehicle (1.0) blocks roughly twice the lane-time of a main-road
# violation (0.5), a junction violation sits in between (0.75), and every other
# violation contributes a small baseline (0.25). Naming them keeps the estimate
# as transparent and auditable as the rest of the scoring core.

LANE_HOURS_MAIN_ROAD = 0.5
LANE_HOURS_DOUBLE_PARK = 1.0
LANE_HOURS_JUNCTION = 0.75
LANE_HOURS_OTHER = 0.25


def estimate_lane_hours(z: ZoneAggregate) -> float:
    """Estimate the daily lane-hours blocked by a zone's violation pattern.

    Computes a weighted violation count, charging the most disruptive classes the
    most lane-time (Requirement 5.1)::

        main_road·0.5 + double_park·1.0 + junction·0.75 + other·0.25

    where ``other`` is every violation not already in one of the three named
    classes::

        other = total_records − main_road_count − double_park_count
                − junction_violation_count

    The named counts are derived from overlapping source categories, so they are
    not guaranteed to be mutually exclusive nor to sum to at most
    ``total_records``; when categories over-count, the raw ``other`` can go
    negative. It is floored with ``max(other, 0)`` so an over-count can never
    subtract lane-hours, guaranteeing the result is always ≥ 0 (Requirement 5.2).

    Because every coefficient is positive and each named class's own coefficient
    (0.5 / 1.0 / 0.75) exceeds the 0.25 it removes from ``other``, raising any
    single contributing count while holding the others fixed never lowers the
    estimate — this holds even once ``other`` has hit its zero floor, where the
    ``other`` term simply stops changing (Requirement 5.3).

    Pure function: deterministic, with no I/O, randomness, clock, or network.

    :param z: the pre-aggregated counts for one ``(h3_id, time_bucket)`` zone.
    :returns: the non-negative estimated daily lane-hours blocked, as a float.
    """
    other = (
        z.total_records
        - z.main_road_count
        - z.double_park_count
        - z.junction_violation_count
    )
    other = max(other, 0)

    return (
        z.main_road_count * LANE_HOURS_MAIN_ROAD
        + z.double_park_count * LANE_HOURS_DOUBLE_PARK
        + z.junction_violation_count * LANE_HOURS_JUNCTION
        + other * LANE_HOURS_OTHER
    )


# ─── Full per-zone breakdown ─────────────────────────────────────────────────

def score_zone(z: ZoneAggregate, m: CorpusMaxima) -> CongestionBreakdown:
    """Assemble the complete Congestion Impact breakdown for one zone.

    This is the single entry point the offline artifact builder (task 5) calls
    per ``(h3_id, time_bucket)`` cell. It composes the already-tested scoring
    primitives — :func:`compute_components`, :func:`compute_score`,
    :func:`impact_band`, and :func:`estimate_lane_hours` — into one breakdown and
    performs no scoring math of its own, so the per-component contracts proven for
    those helpers carry through unchanged.

    Return shape (task 3.1): a typed
    :class:`~backend.app.models.CongestionBreakdown` whose fields mirror the
    design's contract. (Earlier tasks returned a plain dict with these same keys;
    task 3.1 swaps the assembly to the model — the field names are identical, so
    the change is mechanical and the scorer's value-based determinism is
    preserved.) The populated fields are::

        zone_id:            str    # H3 res-9 id (== h3_id)
        h3_id:              str
        time_bucket:        str
        congestion_impact:  float in [0, 100]
        impact_band:        "MINIMAL" | "MODERATE" | "SEVERE" | "CRITICAL"
        components:         ComponentBreakdown(
            lane_blockage       float in [0, 1],
            intersection_impact float in [0, 1],
            traffic_degradation float in [0, 1],
            access_blockage     float in [0, 1],
            vehicle_size        float in [0, 1],
            severity            float in [0, 1],   # diagnostic, NOT weighted
        )
        weights:                          dict[str, float]  # canonical WEIGHTS echo
        estimated_lane_hours_blocked:     float >= 0
        total_records:                    int
        top_violations:                   list[str]
        station:                          Optional[str]
        mappls_travel_time_ratio:         Optional[float]
        is_traffic_degradation_defaulted: bool

    ``lat``/``lon`` are intentionally left at their ``None`` defaults here: they
    are H3-cell-derived (the hexagon centroid) and are not carried on
    :class:`ZoneAggregate`. The offline artifact builder (task 5) attaches them
    when it materializes the artifact, so they are not this function's
    responsibility. The ``junction`` and ``calibrated_impact`` contract fields are
    likewise left at ``None`` — the former has no source on the aggregate and the
    latter is filled later by the self-validating agent (task 9).

    The ``defaulted`` flag from :func:`compute_components` is surfaced as
    ``is_traffic_degradation_defaulted``, and ``mappls_travel_time_ratio`` echoes
    the zone's raw ``travel_time_ratio`` (``None`` when MapMyIndia data was
    missing) so consumers can tell a measured signal from the deterministic
    fallback (Requirement 13.3). The ``weights`` echo is a fresh copy of
    :data:`WEIGHTS` (sum == 1.0) for transparency; copying prevents a consumer
    from mutating the module-level canonical vector.

    Purity (Requirements 7.1, 7.2): every input is read straight off ``z``/``m``
    and every value is derived only from the pure helpers, so there is no I/O,
    randomness, clock, or network — identical ``(z, m)`` inputs always yield an
    equal :class:`CongestionBreakdown` (the model provides value-based equality).

    :param z: the pre-aggregated counts for one ``(h3_id, time_bucket)`` zone.
    :param m: the per-corpus maxima used to normalize the count-based components.
    :returns: the full per-zone :class:`CongestionBreakdown` described above.
    """
    components = compute_components(z, m)
    score = compute_score(components)

    return CongestionBreakdown(
        # Spatial identity — H3 res-9 is canonical; zone_id mirrors h3_id
        # (Requirements 9.1, 9.2). lat/lon stay None here; the artifact builder
        # attaches the H3-centroid coordinates later.
        zone_id=z.h3_id,
        h3_id=z.h3_id,
        time_bucket=z.time_bucket,
        # Score, band, and the five scored components + severity diagnostic.
        congestion_impact=score,
        impact_band=impact_band(score),
        components=ComponentBreakdown(
            lane_blockage=components["lane_blockage"],
            intersection_impact=components["intersection_impact"],
            traffic_degradation=components["traffic_degradation"],
            access_blockage=components["access_blockage"],
            vehicle_size=components["vehicle_size"],
            severity=components["severity"],
        ),
        # Transparency echo of the canonical weights (copied so it stays immutable
        # to callers); sums to 1.0 by the import-time invariant (Requirement 6.3).
        weights=dict(WEIGHTS),
        estimated_lane_hours_blocked=estimate_lane_hours(z),
        total_records=z.total_records,
        top_violations=list(z.top_violations),
        station=z.station,
        # MapMyIndia validation signal: the raw ratio (None when missing) plus the
        # flag marking when traffic_degradation fell back to the default so
        # consumers never mistake the fallback for a measured value (Req 13.2/13.3).
        mappls_travel_time_ratio=z.travel_time_ratio,
        is_traffic_degradation_defaulted=components["defaulted"],
    )
