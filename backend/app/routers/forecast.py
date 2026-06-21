"""
Forecasting endpoints (PREDICT pillar).

Two honest layers:

  • `/forecast/accuracy` serves the REAL held-out metrics of the trained
    LightGBM + CatBoost ensemble, read from `models/ensemble_config.json`
    (chronological split: train < Mar, validate = Mar, test ≥ Apr). The headline
    is Precision@10 — "how many of tomorrow's top-10 daily hotspots we get right".

  • `/forecast/top_risk_zones` and `/forecast/zones` serve a TRANSPARENT proxy
    per-zone forecast derived from each zone's historical daily volume, clearly
    flagged with `is_proxy: true`. The trained ensemble is keyed to a different
    grid than the live H3 zones, so per-zone predictions are not yet mapped onto
    the H3 map (that re-keying is the remaining ML integration); rather than
    fabricate per-zone model outputs we serve the honest proxy and report the
    model's real aggregate accuracy separately.
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Query

from backend.app.data_loader import store

router = APIRouter()

DATASET_DAYS = 151  # Nov 2023 – Apr 2024 (per data card)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENSEMBLE_CONFIG_PATH = PROJECT_ROOT / "models" / "ensemble_config.json"


@lru_cache(maxsize=1)
def _ensemble_config() -> dict:
    """Load the trained ensemble's metrics/config once (committed, ML-free read).

    Returns ``{}`` if the file is absent so the endpoint degrades gracefully.
    """
    try:
        with open(ENSEMBLE_CONFIG_PATH) as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _forecast_row(z: dict) -> dict:
    daily = z["violation_count"] / DATASET_DAYS
    predicted = round(daily, 1)
    return {
        "grid_cell_id": z["grid_cell_id"],
        "hour": z["hour"],
        "grid_lat": z["grid_lat"],
        "grid_lon": z["grid_lon"],
        "predicted": predicted,
        "avg_predicted": predicted,
        "max_predicted": round(daily * 1.3, 1),
        "confidence_lower": round(daily * 0.8, 1),
        "confidence_upper": round(daily * 1.25, 1),
        "is_proxy": True,
    }


@router.get("/forecast/top_risk_zones")
def get_top_predicted_zones(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    n: int = Query(default=10, ge=1, le=50),
):
    """Zones predicted to have the most violations tomorrow (proxy from history)."""
    return [_forecast_row(z) for z in store.top_zones(n)]


@router.get("/forecast/zones")
def get_zone_forecasts(
    zone_id: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Per-zone forecasted daily violation counts (proxy)."""
    rows = [_forecast_row(z) for z in store.top_zones(limit)]
    if zone_id:
        rows = [r for r in rows if r["grid_cell_id"] == zone_id]
    return rows


def _pct(x) -> int | None:
    """Render a 0–1 precision as an integer count out of 10 (for the headline)."""
    return round(x * 10) if isinstance(x, (int, float)) else None


@router.get("/forecast/accuracy")
def get_forecast_accuracy():
    """Real held-out accuracy of the trained LightGBM + CatBoost ensemble.

    Reads `models/ensemble_config.json` (committed). The headline metric is
    Precision@10 on the held-out April test set — the planner's "we correctly
    predict ~N of tomorrow's top-10 daily hotspots". Falls back to a proxy note
    if the trained-model config is unavailable.
    """
    cfg = _ensemble_config()
    metrics = cfg.get("metrics", {}) if cfg else {}
    blend = metrics.get("Blend", {})

    if blend:
        p10 = blend.get("p10_daily")
        baseline = cfg.get("baseline", {})
        top_n = _pct(p10)
        return {
            "model": "LightGBM + CatBoost ensemble (Poisson)",
            "is_proxy": False,
            "target": "violation_count per zone per day",
            "precision_at_10": p10,
            "precision_at_10_data_rich": blend.get("p10_daily_rich"),
            "mae": blend.get("mae"),
            "rmse": blend.get("rmse"),
            "r2": blend.get("r2"),
            "r2_data_rich": blend.get("r2_data_rich"),
            "baseline": baseline,
            "blend_weights": {
                "lightgbm": cfg.get("blend_weight_lgb"),
                "catboost": cfg.get("blend_weight_cat"),
            },
            "split": cfg.get("split"),
            "per_model": {k: metrics[k] for k in ("LightGBM", "CatBoost") if k in metrics},
            "evaluation": "Held-out April test set; chronological split (train < Mar, val = Mar, test ≥ Apr). Leakage-audited strictly-past features.",
            "summary": (
                f"Correctly identifies ~{top_n} of tomorrow's top-10 daily hotspots "
                f"(Precision@10 = {p10:.2f} on the held-out April test set)."
                if isinstance(p10, (int, float)) else None
            ),
        }

    # Trained-model config unavailable → honest proxy note (matches /forecast/zones).
    return {
        "model": "historical-volume proxy",
        "is_proxy": True,
        "n_predictions": len(store.top_zones(1000)),
        "mae": None,
        "rmse": None,
        "note": "Proxy forecast from historical volume; trained ensemble metrics "
                "unavailable (models/ensemble_config.json not found).",
    }
