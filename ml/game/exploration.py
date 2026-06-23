"""
ParkVision-Saathi — ε-greedy patrol allocation (predictive-policing bias
mitigation, Task 9)
==============================================================================

Mitigates the feedback loop where the model learns *where police record
violations, not where they happen* — concentrating patrols on already-watched
zones and going blind to unobserved ones. We split the patrol mass:

    allocation_i = (1 − ε) · exploit_i  +  ε · explore_i        (ε = 0.10)

* ``exploit_i`` — the Stackelberg distribution ``∝ risk_i ^ PATROL_ALPHA``
  (normalized), i.e. patrol where the recorded risk is highest.
* ``explore_i`` — mass directed at **under-observed / low-data** zones,
  ``∝ 1 / (1 + observed_count_i)`` (normalized), so the least-watched zones get
  the most exploration.

Both component distributions sum to 1, so for any ε ∈ [0, 1] the final allocation
is a convex combination that **sums to 1.0** (asserted by the caller). At ε = 0
the allocation is the pure exploit distribution; the documented default ε = 0.10
sends 10% of patrol effort to discover violations the enforcement record misses.

Pure / deterministic: no I/O, randomness, clock, or network.
"""

from __future__ import annotations

from typing import Sequence

EPSILON = 0.10          # documented exploration fraction
PATROL_ALPHA = 1.5      # Stackelberg emphasis (matches data_loader.PATROL_ALPHA)
ALLOCATION_SUM_TOLERANCE = 1e-9

HONEST_LIMITATION = (
    "Violation records are enforcement locations (where police recorded a "
    "violation), not ground-truth violations. The model can inherit this "
    "observation bias; we mitigate it by sending 10% of patrol effort to "
    "under-observed zones (ε-greedy exploration)."
)


def _normalize_or_uniform(weights: Sequence[float]) -> list[float]:
    """Normalize to sum 1; fall back to a uniform distribution if the sum is 0."""
    n = len(weights)
    if n == 0:
        return []
    total = float(sum(weights))
    if total <= 0:
        return [1.0 / n] * n
    return [float(w) / total for w in weights]


def exploit_distribution(risk_scores: Sequence[float], alpha: float = PATROL_ALPHA) -> list[float]:
    """Stackelberg exploit distribution ``∝ risk^alpha`` (uniform if all risk 0)."""
    weights = [max(float(r), 0.0) ** alpha for r in risk_scores]
    return _normalize_or_uniform(weights)


def exploration_distribution(observed_counts: Sequence[float]) -> list[float]:
    """Exploration distribution ``∝ 1/(1+observed_count)`` — favors under-observed zones."""
    weights = [1.0 / (1.0 + max(float(c), 0.0)) for c in observed_counts]
    return _normalize_or_uniform(weights)


def epsilon_greedy_allocation(
    risk_scores: Sequence[float],
    observed_counts: Sequence[float],
    *,
    epsilon: float = EPSILON,
    alpha: float = PATROL_ALPHA,
) -> list[float]:
    """Return the ε-greedy patrol allocation (sums to 1.0 for any non-empty input).

    ``allocation_i = (1−ε)·exploit_i + ε·explore_i``. Raises ``ValueError`` if the
    two input sequences differ in length.
    """
    n = len(risk_scores)
    if n != len(observed_counts):
        raise ValueError("risk_scores and observed_counts must be the same length")
    if n == 0:
        return []
    if not (0.0 <= epsilon <= 1.0):
        raise ValueError("epsilon must be in [0, 1]")
    exploit = exploit_distribution(risk_scores, alpha)
    explore = exploration_distribution(observed_counts)
    return [(1.0 - epsilon) * e + epsilon * x for e, x in zip(exploit, explore)]
