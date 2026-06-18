# ParkVisionSaathi – Violation Count Forecast Model Card

## Overview
| Field | Value |
|---|---|
| **Model** | LightGBM Regressor (v1) |
| **Task** | Predict hourly violation count per 500 m grid cell |
| **Training date** | 2026-06-18 16:08:26 |
| **Framework** | LightGBM via scikit-learn API |

## Hyperparameters
| Parameter | Value |
|---|---|
| n_estimators | 500 |
| learning_rate | 0.05 |
| max_depth | 6 |
| num_leaves | 31 |
| subsample | 0.8 |
| colsample_bytree | 0.8 |
| random_state | 42 |

## Data Split
| Set | Rows |
|---|---|
| Train | 21,089 |
| Test | 2,033 |

Split strategy: time-based (train < 2024-04-01, test ≥ 2024-04-01).
Falls back to 80/20 chronological if the date range does not support the
fixed threshold.

## Evaluation Metrics (Test Set)
| Metric | Value |
|---|---|
| R² | 0.1982 |
| MAE | 4.0615 |
| RMSE | 7.0855 |

## Features (19)
- hour
- day_of_week
- month
- is_weekend
- is_peak
- sin_hour
- cos_hour
- sin_dow
- cos_dow
- lag_1
- lag_24
- lag_168
- rolling_mean_7d
- rolling_mean_14d
- rolling_std_7d
- mean_vehicle_severity
- mean_validation_trust
- heavy_vehicle_ratio
- junction_flag

## Artefacts
- `models/lightgbm_v1.pkl` – serialised model (joblib)
- `models/feature_importance.txt` – top-15 feature importance
- SQLite table `forecast_predictions` – test-set actuals vs predictions

## Limitations & Caveats
- Data covers Nov 2023 – May 2024 (Bengaluru); model may not generalise
  to other cities or time periods without retraining.
- Grid cells with ≤ 30 observations are excluded during feature engineering.
- Lag features cause the first ~168 rows per cell to be dropped.
