"""
Forecasting endpoints.

NOTE ON HONESTY: the LightGBM model in models/ was trained on the synthetic
seed data keyed by CELL_xxxx grid cells, which do not map onto the 15 real H3
hotspot zones. Rather than fabricate model metrics, we serve a TRANSPARENT
proxy forecast derived from each zone's historical daily volume, clearly
flagged as such. Swap in Person 2's real per-H3 ensemble predictions when ready.
"""

from fastapi import APIRouter, Query
from backend.app.data_loader import store

router = APIRouter()

DATASET_DAYS = 151  # Nov 2023 – Apr 2024 (per data card)


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


@router.get("/forecast/accuracy")
def get_forecast_accuracy():
    """Forecast accuracy. Proxy forecast → metrics pending real H3 model integration."""
    return [{
        "n_predictions": len(store.top_zones(1000)),
        "mae": None,
        "rmse": None,
        "note": "Proxy forecast from historical volume; real LightGBM/CatBoost "
                "Precision@10 to be wired from Person 2's H3-keyed model.",
    }]
