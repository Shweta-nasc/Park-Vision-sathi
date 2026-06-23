"""
ParkVision-Saathi — statistical-honesty helpers (Task 11)
==========================================================

Shared, dependency-light utilities so every reported correlation carries a
**confidence interval**, calibration **refuses to fit noise**, and the
observations snapshot is **content-addressable** for an auditable provenance
chain. Deterministic (fixed seeds), no I/O, no network.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Optional, Sequence

# Below this many pairs a correlation / CI is undefined (matches validate_cis).
MIN_POINTS_FOR_CI = 5
# Default near-zero-spread threshold for the flat-variance abort.
DEFAULT_STD_MIN = 0.02


def _is_constant(values: Sequence[float]) -> bool:
    return len(set(values)) <= 1


def bootstrap_spearman_ci(
    x: Sequence[float],
    y: Sequence[float],
    *,
    n_boot: int = 2000,
    seed: int = 42,
    ci: float = 0.95,
) -> dict:
    """Spearman ρ with a percentile bootstrap CI (deterministic).

    Resamples the ``(x, y)`` pairs with replacement ``n_boot`` times using a
    seeded RNG, computes Spearman on each resample, and returns::

        {"rho": point estimate, "lo": ci-low, "hi": ci-high,
         "p_approx": two-sided bootstrap p (share crossing 0), "n": n, "n_boot": n_boot}

    Returns all-``None`` correlation fields (with ``n``) when there are fewer than
    :data:`MIN_POINTS_FOR_CI` pairs or either series is constant — never a
    misleading point estimate.
    """
    import numpy as np
    from scipy.stats import spearmanr

    if len(x) != len(y):
        raise ValueError("x and y must be the same length")
    n = len(x)
    empty = {"rho": None, "lo": None, "hi": None, "p_approx": None, "n": n, "n_boot": n_boot}
    if n < MIN_POINTS_FOR_CI or _is_constant(x) or _is_constant(y):
        return empty

    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    rho_full, _ = spearmanr(xa, ya)
    if rho_full is None or (isinstance(rho_full, float) and math.isnan(rho_full)):
        return empty

    rng = np.random.default_rng(seed)
    boots: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        bx, by = xa[idx], ya[idx]
        if _is_constant(bx.tolist()) or _is_constant(by.tolist()):
            continue
        r, _ = spearmanr(bx, by)
        if r is not None and not (isinstance(r, float) and math.isnan(r)):
            boots.append(float(r))

    if len(boots) < max(20, n_boot // 10):  # too few valid resamples to trust a CI
        return {"rho": round(float(rho_full), 4), "lo": None, "hi": None,
                "p_approx": None, "n": n, "n_boot": n_boot}

    arr = np.asarray(boots, dtype=float)
    alpha = (1.0 - ci) / 2.0
    lo = float(np.quantile(arr, alpha))
    hi = float(np.quantile(arr, 1.0 - alpha))
    frac_le0 = float(np.mean(arr <= 0.0))
    frac_ge0 = float(np.mean(arr >= 0.0))
    p_approx = min(1.0, 2.0 * min(frac_le0, frac_ge0))

    return {
        "rho": round(float(rho_full), 4),
        "lo": round(lo, 4),
        "hi": round(hi, 4),
        "p_approx": round(p_approx, 4),
        "n": n,
        "n_boot": n_boot,
    }


def flat_variance_abort(y: Sequence[float], std_min: float = DEFAULT_STD_MIN) -> Optional[dict]:
    """Return a structured abort dict when the measured ratios are near-flat.

    Off-peak collection makes every ratio ≈ 1.0, so calibration would fit noise.
    Returns ``None`` (proceed) when the spread is healthy, else a structured
    ``aborted_flat_variance`` payload (the caller must NOT fit and must NOT crash).
    """
    import numpy as np

    if len(y) == 0:
        return {
            "status": "aborted_flat_variance",
            "reason": "no measured ratios — likely no collection yet.",
            "std": 0.0, "std_min": std_min, "n": 0,
        }
    arr = np.asarray(y, dtype=float)
    std = float(np.std(arr))
    if std < std_min:
        return {
            "status": "aborted_flat_variance",
            "reason": (
                "measured ratios are nearly flat (std "
                f"{std:.4f} < {std_min}) — likely off-peak; treat any correlation "
                "as an off-peak lower bound, not a calibration."
            ),
            "std": round(std, 5),
            "std_min": std_min,
            "n": len(y),
        }
    return None


def content_sha256(content) -> str:
    """SHA-256 hex of ``content``: raw bytes/str, else canonical JSON of an object."""
    if isinstance(content, bytes):
        data = content
    elif isinstance(content, str):
        data = content.encode("utf-8")
    else:
        data = json.dumps(
            content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()
