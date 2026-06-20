"""
ParkVision-Saathi — Congestion Impact Score (CIS) package.

Houses the deterministic, offline CIS scoring core (``impact_score``) and the
offline artifact builder that pre-computes the per-zone, per-time-bucket
congestion impact artifact served by the FastAPI backend.

CIS is a transparent 0-100 *proxy* for traffic-flow degradation, kept distinct
from the enforcement-priority ``risk_score``.
"""

from ml.congestion.impact_score import (
    BAND_CRITICAL,
    BAND_MINIMAL_MAX,
    BAND_MODERATE_MAX,
    BAND_SEVERE_MAX,
    BAND_THRESHOLDS,
    DEFAULT_TRAFFIC_DEGRADATION,
    SCORE_CAP,
    WEIGHT_SUM_TOLERANCE,
    WEIGHTS,
    CorpusMaxima,
    ZoneAggregate,
)

__all__ = [
    "WEIGHTS",
    "WEIGHT_SUM_TOLERANCE",
    "DEFAULT_TRAFFIC_DEGRADATION",
    "SCORE_CAP",
    "BAND_MINIMAL_MAX",
    "BAND_MODERATE_MAX",
    "BAND_SEVERE_MAX",
    "BAND_THRESHOLDS",
    "BAND_CRITICAL",
    "ZoneAggregate",
    "CorpusMaxima",
]
