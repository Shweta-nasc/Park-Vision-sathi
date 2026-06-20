# ParkVisionSaathi – Violation Count Forecast Model Card

## Overview
| Field | Value |
|---|---|
| **Model** | LightGBM Regressor (objective=poisson) |
| **Task** | Predict hourly violation count per 500 m grid cell |
| **Training date** | 2026-06-21 04:25:06 |
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
| R² | 0.1886 |
| MAE | 4.0129 |
| RMSE | 7.1280 |
| Precision@10 | 0.2875 (28.7%) |

## Per-Hour R² (⚠️ hours ≥16 have sparse data)
| Hour | R² |
|---|---|
| 0 | 0.2068 |
| 1 | 0.1286 |
| 2 | 0.0593 |
| 3 | 0.1686 |
| 4 | 0.2703 |
| 5 | 0.2834 |
| 6 | 0.1652 |
| 7 | 0.1021 |
| 8 | 0.1991 |
| 9 | -0.0995 |
| 18 | 0.0865 |
| 19 | 0.1707 |
| 20 | 0.135 |
| 21 | 0.1869 |
| 22 | -0.207 |
| 23 | 0.0045 |

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

## Target-Leakage Audit & Fix (honest metrics)
An earlier revision reported **R²≈0.9929 / MAE≈0.17**. Those numbers were **not
honest** — they were inflated by target leakage in the feature matrix:

- `rolling_mean_7d`, `rolling_mean_14d`, and `rolling_std_7d` were computed with
  `.rolling(window, min_periods=1)` **without shifting**, so each row's rolling
  window *included that same row's own `violation_count`* (the prediction target).
- `violation_rate` was `violation_count / rolling_mean_7d` — dividing the target
  by a window that already contained the target.

The old feature-importance ranking confirmed the model leaned on these leaky
columns (`violation_rate` #1, `rolling_mean_7d` #2). The fix (in
`ml/forecast/feature_engineering.py`) shifts each cell's series by one row before
rolling, so every rolling statistic uses **strictly-past** observations, and
redefines `violation_rate` as `lag_1 / rolling_mean_7d` (both strictly-past).

| Metric | Old (leaky) | New (honest) |
|---|---|---|
| R² | 0.9929 | 0.1886 |
| MAE | 0.1700 | 4.0129 |
| RMSE | 0.6657 | 7.1280 |
| Precision@10 | 0.5875 | 0.2875 |

The large drop in R² is **expected and correct**: hourly per-cell violation
counts are genuinely hard to predict from past counts alone. Precision@10 (the
rank-based "did we flag the right hotspots" metric) is the more demo-relevant
number and degrades gracefully.

## Limitations & Caveats
- Data covers Nov 2023 – Apr 2024 (Bengaluru); model may not generalise to other cities or time periods without retraining.
- **Sparse temporal index (lag semantics):** the feature matrix has one row per
  (grid_cell_id, date, hour) that recorded ≥1 violation; zero-violation slots are
  not materialized. So `lag_1` / `lag_24` / `lag_168` mean "1 / 24 / 168 *recorded
  observations* ago", not "1 / 24 / 168 *clock hours* ago", and the 168/336-row
  rolling windows span the last 168/336 recorded observations rather than strictly
  7/14 calendar days. A fully temporally-correct version would zero-fill the
  complete (cell × date × hour) grid before computing lags/rolling. The sparse
  representation is retained so these honest metrics stay directly comparable to
  the previously reported (leaky) metrics, which were computed on the same
  representation — isolating the leakage removal rather than confounding it with a
  representation change.
- `created_datetime` (and therefore `hour`) is stored in **UTC**, not IST; the
  data-rich window (hours 0–15) is a UTC convention. Per-hour metrics for the
  sparse UTC hours are not reliable.
- Zone-metadata features (`mean_vehicle_severity`, `mean_validation_trust`,
  `heavy_vehicle_ratio`, `junction_flag`) are aggregated over each cell's full
  history; they are static zone descriptors and a mild source of look-ahead that
  was left in scope-deliberately (they do not encode the per-row target).
- Grid cells with ≤ 30 observations are excluded during feature engineering.
- Lag features cause the first ~168 rows per cell to be dropped.
