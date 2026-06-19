"""
Forecasting endpoints.
"""

from fastapi import APIRouter, Query
from backend.app.db import query_df, table_exists

router = APIRouter()

TIME_BUCKET_MAP = {
    "night_0_6": (0, 6),
    "morning_6_10": (6, 10),
    "midday_10_16": (10, 16),
    "evening_16_22": (16, 22),
    "night_22_24": (22, 24),
}


@router.get("/forecast/zones")
def get_zone_forecasts(
    horizon_hours: int = Query(default=24, ge=1, le=168, description="Forecast horizon in hours"),
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    zone_id: str = Query(default=None, description="Specific grid cell ID"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get forecasted violation counts per zone."""
    if not table_exists("forecast_predictions"):
        return {"error": "Forecast model not yet trained. Run ml/forecast/train_model.py first."}

    if time_bucket and time_bucket in TIME_BUCKET_MAP:
        lo, hi = TIME_BUCKET_MAP[time_bucket]
        hour_clause = "hour >= ? AND hour < ?"
        hour_params = [lo, hi]
    elif hour is not None:
        hour_clause = "hour = ?"
        hour_params = [hour]
    else:
        hour_clause = "1=1"
        hour_params = []

    sql = f"SELECT * FROM forecast_predictions WHERE {hour_clause}"
    params = hour_params

    if zone_id:
        sql += " AND grid_cell_id = ?"
        params.append(zone_id)

    sql += " ORDER BY date, hour LIMIT ?"
    params.append(limit)
    return query_df(sql, tuple(params))


@router.get("/forecast/top_risk_zones")
def get_top_predicted_zones(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    n: int = Query(default=10, ge=1, le=50),
):
    """Get zones predicted to have highest violations for a given hour or time bucket."""
    if not table_exists("forecast_predictions"):
        return {"error": "Forecast model not yet trained."}
    
    if time_bucket and time_bucket in TIME_BUCKET_MAP:
        lo, hi = TIME_BUCKET_MAP[time_bucket]
        hour_clause = "hour >= ? AND hour < ?"
        params = [lo, hi]
    elif hour is not None:
        hour_clause = "hour = ?"
        params = [hour]
    else:
        hour_clause = "1=1"
        params = []

    sql = f"""
        SELECT grid_cell_id, MIN(hour) as hour,
               ROUND(AVG(predicted), 2) as avg_predicted,
               ROUND(MAX(predicted), 2) as max_predicted,
               COUNT(*) as prediction_count
        FROM forecast_predictions
        WHERE {hour_clause}
        GROUP BY grid_cell_id
        ORDER BY avg_predicted DESC
        LIMIT ?
    """
    params.append(n)
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
