"""
ParkVision-Saathi — forecast SHAP explainability (Task 9)
==========================================================

Explains the LightGBM forecast per zone: which features pushed tomorrow's
predicted violation count up or down. SHAP (TreeSHAP) values are computed with
LightGBM's **native** ``predict(pred_contrib=True)`` — identical to
``shap.TreeExplainer`` for tree models, but with no extra dependency, fully
offline and deterministic. (The ``shap`` package is listed in requirements for
optional richer plots; it is not required here.)

Additivity invariant (TreeSHAP): for each row, the contributions plus the base
value sum to the model's **raw** margin (``predict(raw_score=True)``). The export
keeps the per-zone base value and the top-k contributors by absolute impact.

Output sidecar: ``data/processed/forecast_explanations.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "forecast_explanations.json"


def shap_contributions(booster, X) -> np.ndarray:
    """Native TreeSHAP contributions, shape ``(n, n_features + 1)``.

    The last column is the base (expected) value; columns ``0..n_features-1`` are
    the per-feature SHAP contributions in the model's raw-score space.
    """
    arr = np.asarray(X, dtype=float)
    contrib = booster.predict(arr, pred_contrib=True)
    return np.asarray(contrib, dtype=float)


def build_explanations(
    booster,
    future_df,
    feature_names: Sequence[str],
    *,
    top_k: int = 5,
    pred_col: str = "pred",
) -> dict:
    """Per-zone top-k SHAP contributors for the next-day forecast (pure)."""
    feature_names = list(feature_names)
    X = future_df[feature_names].to_numpy(dtype=float)
    contrib = shap_contributions(booster, X)

    zones: dict[str, dict] = {}
    rows = list(future_df.itertuples(index=False))
    cols = list(future_df.columns)
    h3_idx = cols.index("h3_id")
    pred_idx = cols.index(pred_col) if pred_col in cols else None
    feat_idx = {f: cols.index(f) for f in feature_names}

    for i, row in enumerate(rows):
        c = contrib[i]
        base = float(c[-1])
        feats = [
            {
                "feature": f,
                "value": round(float(row[feat_idx[f]]), 4),
                "contribution": round(float(c[j]), 4),
            }
            for j, f in enumerate(feature_names)
        ]
        top = sorted(feats, key=lambda d: abs(d["contribution"]), reverse=True)[:top_k]
        zones[str(row[h3_idx])] = {
            "base_value": round(base, 4),
            "predicted_count": round(float(row[pred_idx]), 2) if pred_idx is not None else None,
            "top_contributors": top,
        }

    return {
        "model": "lightgbm_treeshap",
        "method": "native_pred_contrib",
        "feature_names": feature_names,
        "top_k": top_k,
        "n_zones": len(zones),
        "note": (
            "SHAP (TreeSHAP) contributions in the model's raw-score space; "
            "contributions + base_value sum to the raw margin."
        ),
        "zones": zones,
    }


def export_forecast_explanations(
    booster,
    future_df,
    feature_names: Sequence[str],
    out_path: Path = DEFAULT_OUTPUT_PATH,
    *,
    top_k: int = 5,
    pred_col: str = "pred",
) -> dict:
    """Build and write the per-zone SHAP explanations sidecar."""
    report = build_explanations(booster, future_df, feature_names, top_k=top_k, pred_col=pred_col)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, separators=(",", ":"))
    return report
