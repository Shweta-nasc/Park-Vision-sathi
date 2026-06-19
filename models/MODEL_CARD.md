# ParkVisionSaathi – Violation Count Forecast Model Card

## Overview
| Field | Value |
|---|---|
| **Model** | LightGBM Regressor (objective=poisson) |
| **Task** | Predict hourly violation count per 500 m grid cell |
| **Training date** | 2026-06-19 21:41:40 |
| **Framework** | LightGBM via scikit-learn API |

## Hyperparameters
| Parameter | Value |
|---|---|
| n_estimators | 1000 (with early stopping) |
| learning_rate | 0.05 |
| max_depth | 6 |
| num_leaves | 31 |
| subsample | 0.8 |
| colsample_bytree | 0.8 |
| objective | poisson |
| random_state | 42 |

## Data Split
| Set | Rows |
|---|---|
| Train | 21,089 |
| Test | 2,033 |

Split strategy: time-based (train < 2024-04-01, test ≥ 2024-04-01).
Falls back to 80/20 chronological if the date range does not support the fixed threshold.

## Evaluation Metrics (Test Set)
| Metric | Value |
|---|---|
| R² | 0.9929 |
| MAE | 0.1700 |
| RMSE | 0.6657 |
| Precision@10 | 0.5875 (58.8%) |

## Per-Hour R² (⚠️ hours ≥16 have sparse data)
| Hour | R² |
|---|---|
| 0 | 0.9951 |
| 1 | 0.9917 |
| 2 | 0.997 |
| 3 | 0.9959 |
| 4 | 0.9893 |
| 5 | 0.9914 |
| 6 | 0.9975 |
| 7 | 0.9972 |
| 8 | 0.9985 |
| 9 | 0.998 |
| 18 | 0.9689 |
| 19 | 0.9899 |
| 20 | 0.9946 |
| 21 | 0.9963 |
| 22 | 0.9906 |
| 23 | 0.9971 |

## Features (23)
- hour
- day_of_week
- month
- is_weekend
- is_peak
- sin_hour
- cos_hour
- sin_dow
- cos_dow
- sin_month
- cos_month
- is_data_rich_hour
- lag_1
- lag_24
- lag_168
- rolling_mean_7d
- rolling_mean_14d
- rolling_std_7d
- violation_rate
- mean_vehicle_severity
- mean_validation_trust
- heavy_vehicle_ratio
- junction_flag

## Artefacts
- `models/lightgbm_v1.pkl` – serialised model (joblib)
- `models/feature_importance.txt` – top-20 feature importance
- SQLite table `forecast_predictions` – test-set actuals vs predictions

## Limitations & Caveats
- Data covers Nov 2023 – May 2024 (Bengaluru); model may not generalise to other cities or time periods without retraining.
- Hours 16–23 contain <4% of data (temporal cliff). Metrics for those hours are not reliable.
- Grid cells with ≤ 30 observations are excluded during feature engineering.
- Lag features cause the first ~168 rows per cell to be dropped.
