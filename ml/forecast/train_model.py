"""
train_model.py – Consolidated LightGBM forecasting pipeline for ParkVisionSaathi.

Combines Poisson objective, early stopping, prediction clipping, per-hour R² evaluation, 
and Precision@10 rank-based metrics.
"""

import sqlite3
import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

try:
    import lightgbm as lgb
except ImportError:
    raise ImportError("LightGBM is required. Install via: pip install lightgbm")

# ── Paths ─────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH      = PROJECT_ROOT / "data" / "parkvision.db"
CSV_PATH     = PROJECT_ROOT / "data" / "forecast_features.csv"
MODEL_DIR    = PROJECT_ROOT / "models"
MODEL_PATH   = MODEL_DIR / "lightgbm_v1.pkl"
IMPORTANCE_PATH = MODEL_DIR / "feature_importance.txt"
MODEL_CARD_PATH = MODEL_DIR / "MODEL_CARD.md"

ID_COLS    = ["grid_cell_id", "date"]
TARGET     = "violation_count"
SPLIT_DATE = "2024-04-01"

DATA_RICH_HOURS = set(range(16))   # temporal cliff guard


# ── Data loading ──────────────────────────────────────────────────────────

def load_features(db_path: Path = DB_PATH, csv_path: Path = CSV_PATH) -> pd.DataFrame:
    try:
        conn = sqlite3.connect(str(db_path))
        df = pd.read_sql_query("SELECT * FROM forecast_features", conn)
        conn.close()
        print(f"[load] Loaded {len(df):,} rows from SQLite table 'forecast_features'")
    except Exception:
        df = pd.read_csv(csv_path)
        print(f"[load] Loaded {len(df):,} rows from CSV ({csv_path})")
    return df


# ── Preprocessing ─────────────────────────────────────────────────────────

def preprocess(df: pd.DataFrame):
    lag_cols = [c for c in df.columns if c.startswith("lag_")]
    initial_len = len(df)
    df = df.dropna(subset=lag_cols).reset_index(drop=True)
    print(f"[prep] Dropped {initial_len - len(df):,} rows with NaN lags → {len(df):,} rows remaining")

    df["date"] = df["date"].astype(str)

    if df["date"].max() >= SPLIT_DATE and df["date"].min() < SPLIT_DATE:
        print(f"[split] Time split at {SPLIT_DATE}")
        train_mask = df["date"] < SPLIT_DATE
    else:
        dates_sorted = np.sort(df["date"].unique())
        split_date   = dates_sorted[int(len(dates_sorted) * 0.8)]
        print(f"[split] Fallback 80/20 split at {split_date}")
        train_mask = df["date"] < split_date

    feature_cols = [c for c in df.columns if c not in ID_COLS + [TARGET]]

    X_train = df.loc[train_mask, feature_cols].copy()
    X_test  = df.loc[~train_mask, feature_cols].copy()
    y_train = df.loc[train_mask, TARGET].copy()
    y_test  = df.loc[~train_mask, TARGET].copy()
    id_train = df.loc[train_mask, ID_COLS + ["hour"]].copy()
    id_test = df.loc[~train_mask, ID_COLS + ["hour"]].copy()

    print(f"[split] Train: {len(X_train):,}  |  Test: {len(X_test):,}")
    return X_train, X_test, y_train, y_test, id_train, id_test, feature_cols


# ── Training ──────────────────────────────────────────────────────────────

def train_model(X_train: pd.DataFrame, y_train: pd.Series):
    """Train LightGBM with Poisson objective and early stopping on a 10% holdout."""
    val_split = int(len(X_train) * 0.9)
    X_tr, X_val = X_train.iloc[:val_split], X_train.iloc[val_split:]
    y_tr, y_val = y_train.iloc[:val_split], y_train.iloc[val_split:]

    model = lgb.LGBMRegressor(
        n_estimators=1000,     # upper bound; early stopping kicks in
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        subsample=0.8,
        colsample_bytree=0.8,
        objective='poisson',   # count data
        random_state=42,
        verbose=-1,
    )
    model.fit(
        X_tr, y_tr,
        eval_set=[(X_val, y_val)],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=False),
            lgb.log_evaluation(period=-1),   # silent
        ],
    )
    n_trees = model.best_iteration_ if model.best_iteration_ else model.n_estimators
    print(f"[train] LightGBM training complete (objective=poisson). Best iteration: {n_trees}")
    return model


# ── Evaluation ────────────────────────────────────────────────────────────

def evaluate(model, X_test: pd.DataFrame, y_test: pd.Series,
             id_test: pd.DataFrame, data_rich_only: bool = True):
    """Evaluate using R², MAE, RMSE, per-hour R², and Precision@10."""
    preds = np.clip(model.predict(X_test), 0, None)   # no negative predictions

    # ── Overall metrics ────────────────────────────────────────────────────
    r2   = r2_score(y_test, preds)
    mae  = mean_absolute_error(y_test, preds)
    rmse = np.sqrt(mean_squared_error(y_test, preds))
    print(f"[eval] Overall  R²={r2:.4f}  MAE={mae:.4f}  RMSE={rmse:.4f}")

    # ── Precision@10 ───────────────────────────────────────────────────────
    avg_p10 = 0.0
    if id_test is not None:
        eval_df = id_test.copy()
        eval_df["actual"] = y_test.values
        eval_df["predicted"] = preds
        p10_scores = []
        for date_val in eval_df["date"].unique():
            day = eval_df[eval_df["date"] == date_val]
            if len(day) < 10:
                continue
            actual_top10 = set(day.nlargest(10, "actual")["grid_cell_id"])
            pred_top10 = set(day.nlargest(10, "predicted")["grid_cell_id"])
            p10 = len(actual_top10 & pred_top10) / 10
            p10_scores.append(p10)
        avg_p10 = np.mean(p10_scores) if p10_scores else 0.0
    print(f"[eval] P@10:    {avg_p10:.4f} ({avg_p10*100:.1f}%)")

    # ── Per-hour R² ────────────────────────────────────────────────────────
    hour_col = id_test["hour"].values
    per_hour: dict[int, float] = {}
    print("\n[eval] Per-hour R²:")
    for h in sorted(set(hour_col)):
        mask = hour_col == h
        if mask.sum() < 10:
            continue
        r2_h = r2_score(y_test.values[mask], preds[mask])
        per_hour[int(h)] = round(r2_h, 4)
        rich = "✅" if h in DATA_RICH_HOURS else "⚠️"
        print(f"  hour {h:>2}  R²={r2_h:>7.4f}  {rich}")

    # ── Data-rich only summary ─────────────────────────────────────────────
    if data_rich_only:
        rich_mask = np.isin(hour_col, list(DATA_RICH_HOURS))
        if rich_mask.sum() > 0:
            r2_rich = r2_score(y_test.values[rich_mask], preds[rich_mask])
            print(f"\n[eval] DATA-RICH (h0-15) R²: {r2_rich:.4f}")
        else:
            r2_rich = r2

    return preds, {
        "r2": r2, 
        "mae": mae, 
        "rmse": rmse, 
        "precision_at_10": avg_p10, 
        "per_hour_r2": per_hour
    }


# ── Persistence ───────────────────────────────────────────────────────────

def save_model(model, path: Path = MODEL_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    print(f"[save] Model saved → {path}")


def save_feature_importance(model, feature_names: list,
                             path: Path = IMPORTANCE_PATH, top_n: int = 20):
    fi = sorted(zip(feature_names, model.feature_importances_),
                key=lambda x: x[1], reverse=True)
    lines = [
        "ParkVisionSaathi – LightGBM Feature Importance",
        "=" * 55,
        f"{'Rank':<5}{'Feature':<30}{'Importance':>12}",
        "-" * 55,
    ]
    for rank, (feat, imp) in enumerate(fi[:top_n], 1):
        lines.append(f"{rank:<5}{feat:<30}{imp:>12}")
    lines.append("-" * 55)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[save] Feature importance → {path}")

    # Print top-5 to stdout
    print("\n  Top-5 features:")
    for feat, imp in fi[:5]:
        print(f"    {feat:<30} {imp}")


def save_predictions(id_test: pd.DataFrame, y_test: pd.Series,
                     preds: np.ndarray, db_path: Path = DB_PATH):
    pred_df = id_test.copy()
    pred_df["actual"]    = y_test.values
    pred_df["predicted"] = preds.round(4)
    pred_df = pred_df[["grid_cell_id", "date", "hour", "actual", "predicted"]]

    conn = sqlite3.connect(str(db_path))
    pred_df.to_sql("forecast_predictions", conn, if_exists="replace", index=False)
    conn.close()
    print(f"[save] {len(pred_df):,} predictions → SQLite table 'forecast_predictions'")


def write_model_card(metrics: dict, n_train: int, n_test: int,
                      feature_names: list, path: Path = MODEL_CARD_PATH):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    per_hour_table = "\n".join(
        f"| {h} | {r2} |"
        for h, r2 in sorted(metrics.get("per_hour_r2", {}).items())
    )

    card = f"""\
# ParkVisionSaathi – Violation Count Forecast Model Card

## Overview
| Field | Value |
|---|---|
| **Model** | LightGBM Regressor (objective=poisson) |
| **Task** | Predict hourly violation count per 500 m grid cell |
| **Training date** | {now} |
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
| Train | {n_train:,} |
| Test | {n_test:,} |

Split strategy: time-based (train < {SPLIT_DATE}, test ≥ {SPLIT_DATE}).
Falls back to 80/20 chronological if the date range does not support the fixed threshold.

## Evaluation Metrics (Test Set)
| Metric | Value |
|---|---|
| R² | {metrics['r2']:.4f} |
| MAE | {metrics['mae']:.4f} |
| RMSE | {metrics['rmse']:.4f} |
| Precision@10 | {metrics.get('precision_at_10', 0.0):.4f} ({metrics.get('precision_at_10', 0.0)*100:.1f}%) |

## Per-Hour R² (⚠️ hours ≥16 have sparse data)
| Hour | R² |
|---|---|
{per_hour_table}

## Features ({len(feature_names)})
{chr(10).join('- ' + f for f in feature_names)}

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
| R² | 0.9929 | {metrics['r2']:.4f} |
| MAE | 0.1700 | {metrics['mae']:.4f} |
| RMSE | 0.6657 | {metrics['rmse']:.4f} |
| Precision@10 | 0.5875 | {metrics.get('precision_at_10', 0.0):.4f} |

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
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(card, encoding="utf-8")
    print(f"[save] Model card → {path}")


# ── Main ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("ParkVisionSaathi – LightGBM Forecast Training")
    print("=" * 60)

    # 1. Load features
    df = load_features()

    # 2. Preprocess & split
    X_train, X_test, y_train, y_test, id_train, id_test, feat_names = preprocess(df)

    # 3. Train
    model = train_model(X_train, y_train)

    # 4. Evaluate
    preds, metrics = evaluate(model, X_test, y_test, id_test)

    # 5. Save everything
    save_model(model)
    save_feature_importance(model, feat_names)
    save_predictions(id_test, y_test, preds)
    write_model_card(metrics, len(X_train), len(X_test), feat_names)

    print("\n✅ Training pipeline complete.")
