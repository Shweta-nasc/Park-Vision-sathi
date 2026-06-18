"""
Forecasting endpoints.
"""

from fastapi import APIRouter, Query
from backend.app.db import query_df, table_exists

router = APIRouter()


@router.get("/forecast/zones")
def get_zone_forecasts(
    horizon_hours: int = Query(default=24, ge=1, le=168, description="Forecast horizon in hours"),
    zone_id: str = Query(default=None, description="Specific grid cell ID"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get forecasted violation counts per zone."""
    if not table_exists("forecast_predictions"):
        return {"error": "Forecast model not yet trained. Run ml/forecast/train_model.py first."}

    sql = "SELECT * FROM forecast_predictions"
    params = []

    if zone_id:
        sql += " WHERE grid_cell_id = ?"
        params.append(zone_id)

    sql += " ORDER BY date, hour LIMIT ?"
    params.append(limit)
    return query_df(sql, tuple(params))


@router.get("/forecast/accuracy")
def get_forecast_accuracy():
    """Get forecast model accuracy metrics."""
    if not table_exists("forecast_predictions"):
        return {"error": "Forecast model not yet trained."}

    sql = """
        SELECT
            COUNT(*) as n_predictions,
            ROUND(AVG(ABS(actual - predicted)), 4) as mae,
            ROUND(AVG((actual - predicted) * (actual - predicted)), 4) as mse
        FROM forecast_predictions
        WHERE actual IS NOT NULL
    """
    results = query_df(sql)
    if results:
        r = results[0]
        r["rmse"] = round(r["mse"] ** 0.5, 4) if r["mse"] else None
    return results


@router.get("/forecast/stations")
def get_station_forecasts(
    station: str = Query(description="Police station name"),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Get forecasts aggregated by police station."""
    if not table_exists("forecast_predictions"):
        return {"error": "Forecast model not yet trained."}

    # Join forecast with violations to get station mapping
    sql = """
        SELECT
            v.police_station,
            fp.hour,
            ROUND(AVG(fp.predicted), 2) as avg_predicted,
            COUNT(DISTINCT fp.grid_cell_id) as zone_count
        FROM forecast_predictions fp
        JOIN (
            SELECT DISTINCT grid_cell_id, police_station
            FROM violations
        ) v ON fp.grid_cell_id = v.grid_cell_id
        WHERE v.police_station = ?
        GROUP BY v.police_station, fp.hour
        ORDER BY fp.hour
        LIMIT ?
    """
    return query_df(sql, (station, limit))
