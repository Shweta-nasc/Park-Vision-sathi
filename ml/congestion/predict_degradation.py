"""
ParkVision-Saathi — predicted traffic-degradation component (Task 4)
=====================================================================

Replaces the deterministic ``DEFAULT_TRAFFIC_DEGRADATION = 0.5`` fallback (used
for ~2,517 of 2,527 zones) with a **predicted** value, so the CIS's
traffic-degradation component varies across the map instead of being a flat band
almost everywhere.

Label
-----
For a *measured* zone, the traffic-degradation component is the same transform
the scorer uses on the MapMyIndia ratio::

    degradation = clamp((congestion_ratio - 1) / 2, 0, 1)

This is the CIS-independent measured signal (it is derived from the ratio, not
from the CIS score).

Model
-----
With only ~150 measured zones we deliberately use a **small, strongly-regularized
linear model** (Ridge) rather than anything that could overfit. Features:

    [lane_blockage, intersection_impact, access_blockage, vehicle_size,
     poi_count, free_flow_speed_kmph]

The four components exist for every zone (from the CIS artifact); ``poi_count``
and ``free_flow_speed_kmph`` come from the Task 1 collector and exist only for
measured zones, so they are **mean-imputed** when predicting unmeasured zones
(a documented, conservative choice). Features are imputed + standardized inside
the pipeline; Ridge is closed-form and therefore fully deterministic.

Honesty
-------
Generalization is reported with **leave-one-zone-out CV** (R² and Spearman),
which is leakage-free: each held-out zone is predicted by a model refit on the
others. Measured zones in the output keep their *real* transform
(``source="measured"``); only unmeasured zones carry a model
``source="predicted"``. When there are too few measured zones to fit, the module
falls back to 0.5 for unmeasured zones with a logged warning.

Output: ``data/processed/predicted_degradation.json`` (only from a *real*
collector run; never committed from synthetic fixtures).
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

import numpy as np

from ml.congestion.calibrate_weights import COMPONENTS_4
from ml.congestion.impact_score import DEFAULT_TRAFFIC_DEGRADATION
from ml.congestion.validate_cis import DEFAULT_TIME_BUCKET, spearman

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CIS_ARTIFACT_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact.json"
DEFAULT_OBSERVATIONS_PATH = PROJECT_ROOT / "data" / "enriched" / "congestion_observations.json"
DEFAULT_DEGRADATION_PATH = PROJECT_ROOT / "data" / "processed" / "predicted_degradation.json"

# ─── Constants ───────────────────────────────────────────────────────────────

EXTRA_FEATURES: tuple[str, ...] = ("poi_count", "free_flow_speed_kmph")
FEATURE_NAMES: tuple[str, ...] = COMPONENTS_4 + EXTRA_FEATURES

DEFAULT_RIDGE_ALPHA = 1.0          # strong regularization for small N
MIN_TRAIN_FOR_MODEL = 5            # below this -> 0.5 fallback for unmeasured zones
MODEL_NAME = "ridge"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def ratio_to_degradation(ratio: float) -> float:
    """Scorer's transform: ``clamp((ratio - 1) / 2, 0, 1)`` (the measured label)."""
    return _clamp01((float(ratio) - 1.0) / 2.0)


def _make_model(alpha: float = DEFAULT_RIDGE_ALPHA):
    """Deterministic mean-impute -> standardize -> Ridge pipeline."""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="mean")),
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=alpha)),
        ]
    )


# ─── Feature assembly ────────────────────────────────────────────────────────

def _components_vector(bd: Mapping) -> Optional[list[float]]:
    comps = bd.get("components")
    if not isinstance(comps, Mapping):
        return None
    try:
        return [float(comps[c]) for c in COMPONENTS_4]
    except (KeyError, TypeError, ValueError):
        return None


def _extra_features(obs: Optional[Mapping]) -> list[float]:
    """``[poi_count, free_flow_speed_kmph]`` from an observation (NaN if absent)."""
    if not isinstance(obs, Mapping):
        return [float("nan"), float("nan")]
    pois = obs.get("pois")
    poi_count = float(len(pois)) if isinstance(pois, (list, tuple)) else float("nan")
    ffs = obs.get("free_flow_speed_kmph")
    ffs = float(ffs) if isinstance(ffs, (int, float)) and not isinstance(ffs, bool) else float("nan")
    return [poi_count, ffs]


def build_feature_tables(
    cis_artifact: Mapping[str, Mapping],
    observations: Mapping[str, Mapping],
    *,
    time_bucket: str = DEFAULT_TIME_BUCKET,
) -> tuple[list[dict], list[dict]]:
    """Split zones into ``(measured, unmeasured)`` feature rows.

    A *measured* row has a valid ``congestion_ratio`` (-> label) and the extra
    features from the observation. An *unmeasured* row has only the four
    components (extras NaN -> mean-imputed at prediction). Both are sorted by
    ``h3_id`` for determinism.
    """
    measured: list[dict] = []
    unmeasured: list[dict] = []

    for h3_id, buckets in cis_artifact.items():
        if not isinstance(buckets, Mapping):
            continue
        bd = buckets.get(time_bucket)
        if not isinstance(bd, Mapping):
            continue
        comps = _components_vector(bd)
        if comps is None:
            continue

        obs = observations.get(h3_id)
        ratio = obs.get("congestion_ratio") if isinstance(obs, Mapping) else None
        is_measured = (
            isinstance(ratio, (int, float))
            and not isinstance(ratio, bool)
            and ratio == ratio
            and ratio > 0
        )

        if is_measured:
            measured.append(
                {
                    "h3_id": str(h3_id),
                    "features": comps + _extra_features(obs),
                    "label": ratio_to_degradation(float(ratio)),
                }
            )
        else:
            unmeasured.append(
                {
                    "h3_id": str(h3_id),
                    "features": comps + [float("nan"), float("nan")],
                }
            )

    measured.sort(key=lambda r: r["h3_id"])
    unmeasured.sort(key=lambda r: r["h3_id"])
    return measured, unmeasured


# ─── Leave-one-zone-out CV (leakage-free) ────────────────────────────────────

def lozo_oof_predictions(
    X: np.ndarray,
    y: np.ndarray,
    make_model: Callable[[], object] = _make_model,
) -> np.ndarray:
    """Leave-one-zone-out out-of-fold predictions, clamped to [0, 1].

    For each row ``i`` the model is refit on every *other* row and used to
    predict ``i``; row ``i``'s label is never seen by the model that predicts it,
    so the result is leakage-free.
    """
    n = len(X)
    oof = np.empty(n, dtype=float)
    idx = np.arange(n)
    for i in range(n):
        mask = idx != i
        model = make_model()
        model.fit(X[mask], y[mask])
        oof[i] = _clamp01(float(model.predict(X[i].reshape(1, -1))[0]))
    return oof


def _r2(y_true: np.ndarray, y_pred: np.ndarray) -> Optional[float]:
    if len(y_true) < 2:
        return None
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    if ss_tot <= 0:
        return None
    return round(1.0 - ss_res / ss_tot, 4)


# ─── Prediction build ────────────────────────────────────────────────────────

def build_predictions(
    cis_artifact: Mapping[str, Mapping],
    observations: Mapping[str, Mapping],
    *,
    alpha: float = DEFAULT_RIDGE_ALPHA,
    time_bucket: str = DEFAULT_TIME_BUCKET,
    generated_at: Optional[str] = None,
) -> dict:
    """Fit, LOZO-evaluate, and predict degradation for every zone (no I/O)."""
    measured, unmeasured = build_feature_tables(cis_artifact, observations, time_bucket=time_bucket)
    zones: dict[str, dict] = {}

    # Measured zones always keep their real transform.
    for row in measured:
        zones[row["h3_id"]] = {"degradation": round(row["label"], 6), "source": "measured"}

    n = len(measured)
    if n < MIN_TRAIN_FOR_MODEL:
        logger.warning(
            "Only %d measured zones (need >= %d) — falling back to %.2f for unmeasured zones.",
            n, MIN_TRAIN_FOR_MODEL, DEFAULT_TRAFFIC_DEGRADATION,
        )
        for row in unmeasured:
            zones[row["h3_id"]] = {
                "degradation": DEFAULT_TRAFFIC_DEGRADATION,
                "source": "default_fallback",
            }
        return {
            "model": "fallback_0.5",
            "n": n,
            "n_predicted": len(unmeasured),
            "lozo_r2": None,
            "lozo_spearman": None,
            "alpha": alpha,
            "features": list(FEATURE_NAMES),
            "time_bucket": time_bucket,
            "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
            "zones": dict(sorted(zones.items())),
        }

    X = np.array([r["features"] for r in measured], dtype=float)
    y = np.array([r["label"] for r in measured], dtype=float)

    # Leakage-free generalization estimate.
    oof = lozo_oof_predictions(X, y, lambda: _make_model(alpha))
    lozo_r2 = _r2(y, oof)
    lozo_spear = spearman(list(oof), list(y))

    # Final model refit on all measured zones, used for the unmeasured predictions.
    model = _make_model(alpha)
    model.fit(X, y)
    if unmeasured:
        X_pred = np.array([r["features"] for r in unmeasured], dtype=float)
        preds = model.predict(X_pred)
        for row, p in zip(unmeasured, preds):
            zones[row["h3_id"]] = {"degradation": round(_clamp01(float(p)), 6), "source": "predicted"}

    return {
        "model": MODEL_NAME,
        "n": n,
        "n_predicted": len(unmeasured),
        "lozo_r2": lozo_r2,
        "lozo_spearman": lozo_spear,
        "alpha": alpha,
        "features": list(FEATURE_NAMES),
        "time_bucket": time_bucket,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "zones": dict(sorted(zones.items())),
    }


# ─── I/O ─────────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def degradation_lookup(report: Mapping) -> dict[str, float]:
    """Flatten a report to ``{h3_id: degradation}`` (the Task 5 consumer view)."""
    zones = report.get("zones", {})
    return {h3: float(v["degradation"]) for h3, v in zones.items() if isinstance(v, Mapping)}


def run(
    cis_artifact_path: Path = DEFAULT_CIS_ARTIFACT_PATH,
    observations_path: Path = DEFAULT_OBSERVATIONS_PATH,
    degradation_path: Path = DEFAULT_DEGRADATION_PATH,
    *,
    alpha: float = DEFAULT_RIDGE_ALPHA,
    time_bucket: str = DEFAULT_TIME_BUCKET,
    generated_at: Optional[str] = None,
    verbose: bool = True,
) -> dict:
    """Read inputs, build predictions, write the artifact, print the summary."""
    cis_artifact = _load_json(Path(cis_artifact_path))
    observations = (
        _load_json(Path(observations_path)) if Path(observations_path).exists() else {}
    )
    report = build_predictions(
        cis_artifact, observations, alpha=alpha, time_bucket=time_bucket, generated_at=generated_at,
    )

    degradation_path = Path(degradation_path)
    degradation_path.parent.mkdir(parents=True, exist_ok=True)
    with degradation_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    if verbose:
        r2 = report["lozo_r2"]
        rho = report["lozo_spearman"]
        r2s = f"{r2:.3f}" if isinstance(r2, (int, float)) else "n/a"
        rhos = f"{rho:.3f}" if isinstance(rho, (int, float)) else "n/a"
        print(
            f"Degradation model={report['model']} on {report['n']} measured zones; "
            f"LOZO R²={r2s} Spearman={rhos}; predicted {report['n_predicted']} unmeasured zones."
        )
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Predict traffic-degradation component (Task 4)")
    parser.add_argument("--cis", default=str(DEFAULT_CIS_ARTIFACT_PATH))
    parser.add_argument("--observations", default=str(DEFAULT_OBSERVATIONS_PATH))
    parser.add_argument("--out", default=str(DEFAULT_DEGRADATION_PATH))
    parser.add_argument("--alpha", type=float, default=DEFAULT_RIDGE_ALPHA)
    parser.add_argument("--time-bucket", default=DEFAULT_TIME_BUCKET)
    args = parser.parse_args(argv)

    run(
        cis_artifact_path=Path(args.cis),
        observations_path=Path(args.observations),
        degradation_path=Path(args.out),
        alpha=args.alpha,
        time_bucket=args.time_bucket,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
