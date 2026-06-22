"""
Forecasting endpoints (PREDICT pillar) — H3-native and map-aligned.

The forecast is served from `data/processed/forecasts.json` (built offline by
`ml/forecast/build_h3_forecast.py`): a real LightGBM-Poisson daily model trained
on the SAME H3 res-9 zones as the Congestion Impact map, so "tomorrow's predicted
hotspots" line up exactly with the map. Metrics are honest held-out numbers
(chronological split, strictly-past features).

If that artifact is absent, the endpoints fall back to a transparent
historical-volume proxy over the legacy hotspot zones (clearly `is_proxy: true`)
so the API still responds.
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Query

from backend.app.data_loader import store

router = APIRouter()

DATASET_DAYS = 151  # Nov 2023 – Apr 2024 (per data card) — used only by the proxy
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENSEMBLE_CONFIG_PATH = PROJECT_ROOT / "models" / "ensemble_config.json"


# ── Proxy fallback (legacy hotspot zones; only when no H3 artifact) ──────────

def _proxy_row(z: dict) -> dict:
    daily = z["violation_count"] / DATASET_DAYS
    return {
        "zone_id": z["grid_cell_id"], "h3_id": z["grid_cell_id"],
        "grid_lat": z["grid_lat"], "grid_lon": z["grid_lon"],
        "predicted": round(daily, 1), "predicted_count": round(daily, 1),
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
    """H3 zones predicted to have the most violations tomorrow (ranked)."""
    rows = store.forecast_top_zones(n)
    if rows:
        return [{**r, "is_proxy": False} for r in rows]
    return [_proxy_row(z) for z in store.top_zones(n)]  # fallback


@router.get("/forecast/zones")
def get_zone_forecasts(
    zone_id: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=5000),
):
    """Per-H3-zone next-day forecast. With `zone_id`, returns just that zone."""
    if store.forecasts:
        if zone_id:
            rec = store.forecast_for_zone(zone_id)
            return [{**rec, "is_proxy": False}] if rec else []
        return [{**r, "is_proxy": False} for r in store.forecast_top_zones(limit)]
    rows = [_proxy_row(z) for z in store.top_zones(limit)]  # fallback
    return [r for r in rows if r["zone_id"] == zone_id] if zone_id else rows


@lru_cache(maxsize=1)
def _ensemble_config() -> dict:
    try:
        with open(ENSEMBLE_CONFIG_PATH) as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


@router.get("/forecast/explanations")
def get_forecast_explanations(
    zone_id: str = Query(default=None),
    limit: int = Query(default=50, ge=1, le=2000),
):
    """Per-zone SHAP (TreeSHAP) explanations for the forecast (Task 9).

    With ``zone_id``, returns that zone's top contributors; otherwise a list.
    When the explanations sidecar is absent, ``available`` is False (the panel
    shows the honest-limitations note without a SHAP breakdown).
    """
    if zone_id:
        rec = store.forecast_explanation_for(zone_id)
        return {"available": rec is not None, "zone": rec}
    return store.forecast_explanations_list(limit)


@router.get("/forecast/accuracy")
def get_forecast_accuracy():
    """Real held-out accuracy of the forecast model.

    Prefers the **H3-native map-aligned** model's metrics (forecasts.json). Falls
    back to the grid-keyed LightGBM+CatBoost ensemble's metrics (ensemble_config),
    then to a proxy note. The headline is Precision@10 — the share of tomorrow's
    actual top-10 hotspot zones the model ranks in its own top-10.
    """
    meta = store.forecast_metrics()
    m = meta.get("metrics") if meta else None
    if m and m.get("precision_at_10") is not None:
        p10 = m["precision_at_10"]
        return {
            "model": meta.get("model"),
            "is_proxy": meta.get("is_proxy", False),
            "spatial_unit": "H3 resolution 9 (same as the Congestion Impact map)",
            "target": meta.get("target"),
            "precision_at_10": p10,
            "mae": m.get("mae"),
            "rmse": m.get("rmse"),
            "n_test_days": m.get("n_test_days"),
            "generated_for": meta.get("generated_for"),
            "split": meta.get("split"),
            "evaluation": "Held-out April test set; chronological split; strictly-past (leakage-free) features.",
            "summary": (
                f"Correctly identifies ~{round(p10 * 10)} of tomorrow's top-10 H3 hotspots "
                f"(Precision@10 = {p10:.2f} on the held-out April test set)."
            ),
        }

    cfg = _ensemble_config()
    blend = cfg.get("metrics", {}).get("Blend", {}) if cfg else {}
    if blend:
        p10 = blend.get("p10_daily")
        return {
            "model": "LightGBM + CatBoost ensemble (Poisson, ~500m grid)",
            "is_proxy": False,
            "spatial_unit": "custom ~500m grid (not yet mapped to H3)",
            "precision_at_10": p10,
            "mae": blend.get("mae"), "rmse": blend.get("rmse"), "r2": blend.get("r2"),
            "baseline": cfg.get("baseline", {}),
            "split": cfg.get("split"),
            "note": "Grid-keyed ensemble metrics (the map-aligned H3 forecast artifact was not found).",
        }

    return {
        "model": "historical-volume proxy", "is_proxy": True,
        "n_predictions": len(store.top_zones(1000)), "mae": None, "rmse": None,
        "note": "Proxy forecast from historical volume; no trained-model metrics available.",
    }
