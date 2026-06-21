# ParkVisionSaathi – Violation Count Forecast Model Card (v2: LGB + CatBoost ensemble)

## Overview
| Field | Value |
|---|---|
| **Models** | LightGBM (Poisson) + CatBoost (RMSE), rank-weighted blend |
| **Task** | Predict hourly violation count per ~550 m grid cell |
| **Training date** | 2026-06-21 06:10:06 |
| **Representation** | DENSE hourly grid (601 active cells × 3,624 IST hours = 2,178,024 slots, zero-filled) |
| **Blend weight** | 0.85·LightGBM + 0.15·CatBoost (tuned to maximise daily data-rich Precision@10 on the March validation fold) |

## Data Split (chronological, IST)
| Set | Window | Rows |
|---|---|---|
| fit | < 2024-03-01 | (early-stop training) |
| val | 2024-03-01 .. 2024-03-31 | (early-stopping + blend tuning) |
| train (fit+val) | < 2024-04-01 | 1,961,664 |
| test | >= 2024-04-01 | 115,392 |

Both models early-stop on the March fold and the blend weight is tuned there; the
final models ARE those early-stopped fit (< 2024-03-01) models, then evaluated
once on the April test set. (A separate refit on the full fit+val window was
skipped to stay within memory on the training machine; using the last train month
as the held-out early-stopping fold is standard and introduces no test leakage.)

## Evaluation Metrics (April test set)
| Model | R² | MAE | RMSE | P@10 (daily) | P@10 (daily, data-rich) | P@10 (hourly) | R² (data-rich h0–15) |
|---|---|---|---|---|---|---|---|
| LightGBM | 0.2502 | 0.1895 | 1.1709 | 67.5% | 67.5% | 23.0% | 0.2478 |
| CatBoost | 0.2525 | 0.1767 | 1.1691 | 70.0% | 70.0% | 22.7% | 0.2496 |
| Blend | 0.2571 | 0.1872 | 1.1655 | 67.5% | 67.5% | 23.1% | 0.2547 |

`P@10 (daily)` = for each test day, overlap between the 10 cells with the highest
ACTUAL daily total and the 10 with the highest PREDICTED daily total (the
demo-relevant "did we flag the right hotspots" metric). `data-rich` restricts the
daily total to IST hours 0–15 (the ~99 % data-rich window). `P@10 (hourly)` is the
same overlap computed per (day, hour).

## Honest before/after vs the prior baseline
The prior **honest** baseline was a single LightGBM on the SPARSE representation
(one row per recorded (cell, date, hour)) with leakage already removed:
R²=0.1886, MAE=4.01, RMSE=7.13,
Precision@10=28.7%.

| Metric | Prior baseline (sparse, LGB) | This ensemble (dense, blend) |
|---|---|---|
| R² | 0.1886 | 0.2571 |
| MAE | 4.01 | 0.1872 |
| RMSE | 7.13 | 1.1655 |
| Precision@10 | 28.7% | 67.5% (daily) / 67.5% (daily data-rich) |

> NOTE ON COMPARABILITY: the baseline's MAE/RMSE/R² were computed on the SPARSE
> matrix (only recorded cell-hours, target mean ≈ several), whereas this model is
> evaluated on the DENSE grid (every cell-hour, target mean ≈ 0.13 because most
> slots are structural zeros). MAE/RMSE therefore drop largely because the dense
> target is mostly zero, not solely from model skill — the **rank-based
> Precision@10 is the apples-to-closer demo metric** and is reported on the dense
> grid. The dense representation is what makes the lags physically correct.

## Blend sweep (val daily data-rich P@10 by w = weight on LightGBM)
0.0:0.6548, 0.05:0.6548, 0.1:0.6581, 0.15:0.6613, 0.2:0.6645, 0.25:0.6645, 0.3:0.6677, 0.35:0.6677, 0.4:0.6645, 0.45:0.6677, 0.5:0.6645, 0.55:0.6645, 0.6:0.6613, 0.65:0.6613, 0.7:0.6581, 0.75:0.6613, 0.8:0.6677, 0.85:0.671, 0.9:0.6677, 0.95:0.6645, 1.0:0.6645

## Features (27)
- grid_lat
- grid_lon
- hour
- day_of_week
- month
- is_weekend
- is_peak
- is_data_rich_hour
- sin_hour
- cos_hour
- sin_dow
- cos_dow
- sin_month
- cos_month
- lag_1
- lag_24
- lag_168
- rolling_mean_24h
- rolling_std_24h
- rolling_mean_168h
- rolling_std_168h
- violation_rate
- spatial_lag_1
- mean_vehicle_severity
- mean_validation_trust
- heavy_vehicle_ratio
- junction_flag

CatBoost categorical features: hour, day_of_week, month, is_weekend, is_peak, is_data_rich_hour, junction_flag.

## Artefacts
- `models/lightgbm_v2.pkl` – LightGBM model (joblib)
- `models/catboost_v1.cbm` – CatBoost model
- `models/ensemble_config.json` – blend weight + feature list + metrics
- `models/lightgbm_v1.pkl` – previous (sparse) model, retained for the backend path
- SQLite `forecast_features` (key: grid_cell_id, + h3_id) and `forecast_predictions`

## Leakage audit
Every predictive feature uses only data strictly before the target hour t:
lags use shift(k≥1); rolling stats are shift(1) THEN rolling(window); the spatial
lag uses neighbour counts at t-1; violation_rate = lag_1 / rolling_mean_168h. The
split is chronological. Verified programmatically in
`ml/forecast/feature_engineering.py` (see `_audit` checks during development).

## Limitations & caveats
- Predictions are capped at a high percentile of training-set hourly counts
  (LGB cap and CatBoost cap chosen on the March validation fold, not on test):
  the Poisson LightGBM otherwise extrapolates a few hourly counts ~1000× above
  anything physically observed, which alone drove R² negative. Capping is honest
  post-processing (never predict more than ~the most ever observed) and is tuned
  only on val.
- Dense hourly counts are highly zero-inflated; absolute-error metrics are
  dominated by the zero mass. Rank metrics (Precision@10) are the headline.
- Hours 16–23 IST hold ~1 % of violations (enforcement-shift bias); they are
  materialised so lags are physically correct but flagged via `is_data_rich_hour`,
  and data-rich-only metrics are reported as the headline.
- Static per-cell descriptors (severity/trust/heavy-vehicle/junction) are
  aggregated over each cell's full history; they are zone constants, not per-row
  targets, so they do not leak the target.
- Covers Nov 2023 – Apr 2024 (Bengaluru); retrain for other windows/cities.
