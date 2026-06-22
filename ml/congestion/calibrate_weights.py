"""
ParkVision-Saathi — CIS weight calibration (Task 3)
====================================================

Replaces the four *guessed* CIS component weights with weights **fitted to the
measured MapMyIndia congestion ratio**, turning the expert-set formula into a
calibrated one.

Circularity rule (critical)
---------------------------
The ``traffic_degradation`` component is itself **derived from** the measured
ratio (``clamp((ratio-1)/2)``). Fitting a weight for it against that same ratio
would be fitting a number to itself. So ``traffic_degradation`` is **excluded**
from the optimization: we fit only the four violation/road-derived components

    X = [lane_blockage, intersection_impact, access_blockage, vehicle_size]

against the label ``y = congestion_ratio`` (the CIS-independent measured signal).

Objective
---------
Find non-negative weights ``a₁..a₄`` summing to 1 that **maximize the Spearman
rank correlation** between ``Σ aᵢ·xᵢ`` and ``y`` on the *train* split. Spearman
is rank-based (non-differentiable), so we use a seeded **Dirichlet random
search** over the simplex (plus the simplex vertices and the current normalized
weights as explicit candidates) and an optional deterministic **Nelder-Mead**
refinement. Everything is seeded and reproducible.

Reassembly
----------
The full five-weight CIS vector keeps ``traffic_degradation`` fixed at
:data:`W_TD_FIXED` (= 0.25, documented as "the measured-signal weight") and sets
the other four to ``aᵢ·(1 − W_TD_FIXED)``. The reassembled vector is asserted to
sum to 1.0 ± 1e-9.

Honesty
-------
The new test-split Spearman is reported **as measured** alongside the old. The
optimizer is not allowed to claim a test improvement it did not earn — the
random search only guarantees it does no worse than the current weights *on the
train split* (the current weights are a candidate). A weaker test number is a
legitimate, reported outcome.

Output: ``data/processed/cis_calibration.json``. (Only produced from a *real*
collector run; never committed from synthetic fixtures.)
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

import numpy as np

from ml.congestion.impact_score import WEIGHTS, WEIGHT_SUM_TOLERANCE
from ml.congestion.validate_cis import (
    DEFAULT_SPLIT_SEED,
    DEFAULT_TIME_BUCKET,
    MIN_POINTS_FOR_CORR,
    deterministic_split,
    spearman,
)

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CIS_ARTIFACT_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact.json"
DEFAULT_OBSERVATIONS_PATH = PROJECT_ROOT / "data" / "enriched" / "congestion_observations.json"
DEFAULT_CALIBRATION_PATH = PROJECT_ROOT / "data" / "processed" / "cis_calibration.json"

# ─── Constants ───────────────────────────────────────────────────────────────

# The four fittable components (traffic_degradation deliberately excluded).
COMPONENTS_4: tuple[str, ...] = (
    "lane_blockage",
    "intersection_impact",
    "access_blockage",
    "vehicle_size",
)

# traffic_degradation's weight is held fixed at its canonical value: it is the
# directly-measured signal, so it keeps its seat in the convex combination while
# the other four are re-fitted to fill the remaining (1 - W_TD_FIXED) mass.
W_TD_FIXED = float(WEIGHTS["traffic_degradation"])  # 0.25

DEFAULT_N_SAMPLES = 20_000
DEFAULT_CALIBRATION_SEED = 20240315  # search RNG seed (distinct from split seed)
METHOD_TAG = "dirichlet_random_search+nelder_mead"


# ─── Training-matrix assembly ────────────────────────────────────────────────

def build_training_rows(
    cis_artifact: Mapping[str, Mapping],
    observations: Mapping[str, Mapping],
    *,
    seed: int = DEFAULT_SPLIT_SEED,
    time_bucket: str = DEFAULT_TIME_BUCKET,
) -> list[dict]:
    """Join per-zone component vectors with the measured ratio + split label.

    One row per zone present in **both** inputs with a usable
    ``congestion_ratio`` and a complete 4-component vector in ``time_bucket``.
    Each row: ``{h3_id, x (4-vector), y (ratio), split}``. The predictors are the
    raw CIS components; the label is the CIS-independent measured ratio — so this
    join is not circular. Sorted by ``h3_id`` for determinism.
    """
    rows: list[dict] = []
    for h3_id, obs in observations.items():
        if not isinstance(obs, Mapping):
            continue
        ratio = obs.get("congestion_ratio")
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
            continue
        if not (ratio == ratio) or ratio <= 0:
            continue

        buckets = cis_artifact.get(h3_id)
        if not isinstance(buckets, Mapping):
            continue
        bd = buckets.get(time_bucket)
        if not isinstance(bd, Mapping):
            continue
        comps = bd.get("components")
        if not isinstance(comps, Mapping):
            continue
        try:
            x = [float(comps[c]) for c in COMPONENTS_4]
        except (KeyError, TypeError, ValueError):
            continue

        rows.append(
            {
                "h3_id": str(h3_id),
                "x": x,
                "y": float(ratio),
                "split": deterministic_split(str(h3_id), seed),
            }
        )
    rows.sort(key=lambda r: r["h3_id"])
    return rows


# ─── Spearman helpers ────────────────────────────────────────────────────────

def _exact_spearman(pred: np.ndarray, y: np.ndarray) -> float:
    """Exact Spearman (scipy), or ``-inf`` when undefined (used by the search)."""
    if len(pred) < 2 or len(set(np.round(pred, 12))) <= 1 or len(set(np.round(y, 12))) <= 1:
        return float("-inf")
    from scipy.stats import spearmanr

    rho, _ = spearmanr(pred, y)
    if rho is None or (isinstance(rho, float) and rho != rho):
        return float("-inf")
    return float(rho)


def _ordinal_ranks(matrix: np.ndarray) -> np.ndarray:
    """Per-row ordinal ranks (0..n-1) of a 2-D array (ties broken by position)."""
    order = matrix.argsort(axis=1)
    ranks = np.empty_like(order, dtype=float)
    rows = np.arange(matrix.shape[0])[:, None]
    ranks[rows, order] = np.arange(matrix.shape[1])[None, :]
    return ranks


# ─── Weight fitting ──────────────────────────────────────────────────────────

def old_normalized_weights() -> np.ndarray:
    """Current 4-component weights, renormalized to sum to 1 (the baseline ``a``)."""
    w = np.array([WEIGHTS[c] for c in COMPONENTS_4], dtype=float)
    return w / w.sum()


def fit_weights(
    X_train: np.ndarray,
    y_train: np.ndarray,
    *,
    seed: int = DEFAULT_CALIBRATION_SEED,
    n_samples: int = DEFAULT_N_SAMPLES,
    refine: bool = True,
) -> tuple[np.ndarray, float]:
    """Return ``(a, train_spearman)`` maximizing Spearman(X·a, y) on the simplex.

    Candidates = the 4 simplex vertices + the current normalized weights +
    ``n_samples`` seeded Dirichlet draws. The vectorized search ranks each
    candidate's prediction and correlates it with ``y``; the best is optionally
    refined with Nelder-Mead (accepted only if it strictly improves the *exact*
    train Spearman). Fully deterministic for a fixed ``seed``.
    """
    X_train = np.asarray(X_train, dtype=float)
    y_train = np.asarray(y_train, dtype=float)

    a_old = old_normalized_weights()
    rng = np.random.default_rng(seed)
    vertices = np.eye(4)
    base = np.vstack([vertices, a_old.reshape(1, 4)])
    if n_samples > 0:
        draws = rng.dirichlet(np.ones(4), size=n_samples)
        candidates = np.vstack([base, draws])
    else:
        candidates = base

    # Vectorized rank-correlation search.
    preds = candidates @ X_train.T            # (m, n)
    pred_ranks = _ordinal_ranks(preds)        # (m, n)
    y_ranks = _ordinal_ranks(y_train.reshape(1, -1))[0]  # (n,)

    rc = pred_ranks - pred_ranks.mean(axis=1, keepdims=True)
    yc = y_ranks - y_ranks.mean()
    num = rc @ yc
    den = np.sqrt((rc ** 2).sum(axis=1) * (yc ** 2).sum())
    rho = np.where(den > 0, num / den, -np.inf)

    best_idx = int(np.argmax(rho))
    best_a = candidates[best_idx].astype(float)
    best_train = _exact_spearman(preds[best_idx], y_train)

    if refine:
        refined_a, refined_train = _nelder_mead_refine(X_train, y_train, best_a)
        if refined_train > best_train + 1e-9:
            best_a, best_train = refined_a, refined_train

    # Normalize defensively (handles any FP drift / refinement clipping).
    best_a = np.clip(best_a, 0.0, None)
    s = best_a.sum()
    best_a = best_a / s if s > 0 else a_old
    return best_a, best_train


def _nelder_mead_refine(
    X_train: np.ndarray, y_train: np.ndarray, start_a: np.ndarray
) -> tuple[np.ndarray, float]:
    """Deterministic Nelder-Mead polish of ``start_a`` (softmax-parameterized)."""
    try:
        from scipy.optimize import minimize

        def to_simplex(theta: np.ndarray) -> np.ndarray:
            e = np.exp(theta - theta.max())
            return e / e.sum()

        def neg_spearman(theta: np.ndarray) -> float:
            a = to_simplex(theta)
            return -_exact_spearman(X_train @ a, y_train)

        theta0 = np.log(np.clip(start_a, 1e-6, None))
        res = minimize(neg_spearman, theta0, method="Nelder-Mead",
                       options={"xatol": 1e-4, "fatol": 1e-4, "maxiter": 2000})
        a = to_simplex(res.x)
        return a, _exact_spearman(X_train @ a, y_train)
    except Exception as exc:  # noqa: BLE001 — refinement is best-effort
        logger.warning("Nelder-Mead refinement skipped: %s", exc)
        return start_a, _exact_spearman(X_train @ start_a, y_train)


def assemble_full_weights(a4: Sequence[float]) -> dict[str, float]:
    """Reassemble the 5-weight CIS vector: td fixed, others = aᵢ·(1−td)."""
    scale = 1.0 - W_TD_FIXED
    full = {c: float(a4[i]) * scale for i, c in enumerate(COMPONENTS_4)}
    full["traffic_degradation"] = W_TD_FIXED
    total = sum(full.values())
    assert abs(total - 1.0) < WEIGHT_SUM_TOLERANCE, f"weights must sum to 1.0 (got {total})"
    # Order the dict like the canonical WEIGHTS for readability.
    return {k: full[k] for k in WEIGHTS}


# ─── Report ──────────────────────────────────────────────────────────────────

def _predict(rows: list[dict], a4: np.ndarray) -> tuple[list[float], list[float]]:
    preds = [float(np.dot(a4, r["x"])) for r in rows]
    ys = [r["y"] for r in rows]
    return preds, ys


def build_calibration(
    cis_artifact: Mapping[str, Mapping],
    observations: Mapping[str, Mapping],
    *,
    split_seed: int = DEFAULT_SPLIT_SEED,
    calib_seed: int = DEFAULT_CALIBRATION_SEED,
    n_samples: int = DEFAULT_N_SAMPLES,
    refine: bool = True,
    time_bucket: str = DEFAULT_TIME_BUCKET,
    generated_at: Optional[str] = None,
) -> dict:
    """Fit weights and return the calibration report dict (no I/O).

    Falls back to the current weights (``method="fallback_insufficient_data"``)
    when there are too few train zones to fit, so the function never crashes on a
    sparse collection.
    """
    rows = build_training_rows(cis_artifact, observations, seed=split_seed, time_bucket=time_bucket)
    train = [r for r in rows if r["split"] == "train"]
    test = [r for r in rows if r["split"] == "test"]

    a_old = old_normalized_weights()
    old_full = dict(WEIGHTS)

    if len(train) < MIN_POINTS_FOR_CORR:
        logger.warning(
            "Only %d train zones (need >= %d) — keeping current weights.",
            len(train), MIN_POINTS_FOR_CORR,
        )
        a_new = a_old
        method = "fallback_insufficient_data"
    else:
        X_train = np.array([r["x"] for r in train], dtype=float)
        y_train = np.array([r["y"] for r in train], dtype=float)
        a_new, _ = fit_weights(X_train, y_train, seed=calib_seed, n_samples=n_samples, refine=refine)
        method = METHOD_TAG

    new_full = assemble_full_weights(a_new)

    # Honest test-split correlations (None when the test split is too small).
    old_pred_test, y_test = _predict(test, a_old)
    new_pred_test, _ = _predict(test, a_new)
    old_pred_train, y_train_all = _predict(train, a_old)
    new_pred_train, _ = _predict(train, a_new)

    return {
        "old_weights": old_full,
        "new_weights": new_full,
        "w_td_fixed": W_TD_FIXED,
        "fitted_components": list(COMPONENTS_4),
        "fitted_a_new": {c: round(float(a_new[i]), 6) for i, c in enumerate(COMPONENTS_4)},
        "spearman_old_test": spearman(old_pred_test, y_test),
        "spearman_new_test": spearman(new_pred_test, y_test),
        "spearman_old_train": spearman(old_pred_train, y_train_all),
        "spearman_new_train": spearman(new_pred_train, y_train_all),
        "n_train": len(train),
        "n_test": len(test),
        "split_seed": split_seed,
        "seed": calib_seed,
        "n_samples": n_samples,
        "method": method,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
    }


# ─── I/O ─────────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def run(
    cis_artifact_path: Path = DEFAULT_CIS_ARTIFACT_PATH,
    observations_path: Path = DEFAULT_OBSERVATIONS_PATH,
    calibration_path: Path = DEFAULT_CALIBRATION_PATH,
    *,
    split_seed: int = DEFAULT_SPLIT_SEED,
    calib_seed: int = DEFAULT_CALIBRATION_SEED,
    n_samples: int = DEFAULT_N_SAMPLES,
    refine: bool = True,
    time_bucket: str = DEFAULT_TIME_BUCKET,
    generated_at: Optional[str] = None,
    verbose: bool = True,
) -> dict:
    """Read inputs, fit weights, write the calibration report, print the table."""
    cis_artifact = _load_json(Path(cis_artifact_path))
    observations = (
        _load_json(Path(observations_path)) if Path(observations_path).exists() else {}
    )
    report = build_calibration(
        cis_artifact, observations,
        split_seed=split_seed, calib_seed=calib_seed, n_samples=n_samples,
        refine=refine, time_bucket=time_bucket, generated_at=generated_at,
    )

    calibration_path = Path(calibration_path)
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    with calibration_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    if verbose:
        _print_report(report)
    return report


def _fmt(value: Optional[float]) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) else "n/a"


def _print_report(report: dict) -> None:
    print(f"\nCIS weight calibration ({report['method']})")
    print(f"  train zones: {report['n_train']}   test zones: {report['n_test']}")
    print(f"  test Spearman   old ρ={_fmt(report['spearman_old_test'])}   "
          f"new ρ={_fmt(report['spearman_new_test'])}")
    print("  weight table (old -> new):")
    old_w, new_w = report["old_weights"], report["new_weights"]
    for c in old_w:
        marker = "  (fixed)" if c == "traffic_degradation" else ""
        print(f"    {c:<22} {old_w[c]:.3f} -> {new_w[c]:.3f}{marker}")
    print(f"  sum(new) = {sum(new_w.values()):.6f}\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CIS weight calibration (Task 3)")
    parser.add_argument("--cis", default=str(DEFAULT_CIS_ARTIFACT_PATH))
    parser.add_argument("--observations", default=str(DEFAULT_OBSERVATIONS_PATH))
    parser.add_argument("--out", default=str(DEFAULT_CALIBRATION_PATH))
    parser.add_argument("--split-seed", type=int, default=DEFAULT_SPLIT_SEED)
    parser.add_argument("--calib-seed", type=int, default=DEFAULT_CALIBRATION_SEED)
    parser.add_argument("--n-samples", type=int, default=DEFAULT_N_SAMPLES)
    parser.add_argument("--no-refine", action="store_true", help="disable Nelder-Mead refinement")
    parser.add_argument("--time-bucket", default=DEFAULT_TIME_BUCKET)
    args = parser.parse_args(argv)

    run(
        cis_artifact_path=Path(args.cis),
        observations_path=Path(args.observations),
        calibration_path=Path(args.out),
        split_seed=args.split_seed,
        calib_seed=args.calib_seed,
        n_samples=args.n_samples,
        refine=not args.no_refine,
        time_bucket=args.time_bucket,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
