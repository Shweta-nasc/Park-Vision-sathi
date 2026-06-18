"""
LightGBM training for violation count forecasting.

Loads the engineered feature matrix (from SQLite or CSV), trains a LightGBM
regressor with a time-based train/test split, evaluates on held-out data,
and persists:
    - Trained model  → models/lightgbm_v1.pkl
    - Feature importance → models/feature_importance.txt
    - Predictions    → SQLite table 'forecast_predictions'
    - Model card     → models/MODEL_CARD.md
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
    raise ImportError(
        "LightGBM is required.  Install via:  pip install lightgbm"
    )

# ── paths ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"
CSV_PATH = PROJECT_ROOT / "data" / "forecast_features.csv"
MODEL_DIR = PROJECT_ROOT / "models"
MODEL_PATH = MODEL_DIR / "lightgbm_v1.pkl"
IMPORTANCE_PATH = MODEL_DIR / "feature_importance.txt"
MODEL_CARD_PATH = MODEL_DIR / "MODEL_CARD.md"

# Columns that are NOT used as input features
ID_COLS = ["grid_cell_id", "date"]
TARGET = "violation_count"

# Date threshold for the time-based split
SPLIT_DATE = "2024-04-01"


# ── data loading ─────────────────────────────────────────────────────────
def load_features(db_path: Path = DB_PATH,
                  csv_path: Path = CSV_PATH) -> pd.DataFrame:
    """Load the forecast_features table – prefer SQLite, fall back to CSV."""
    try:
        conn = sqlite3.connect(str(db_path))
        df = pd.read_sql_query("SELECT * FROM forecast_features", conn)
        conn.close()
        print(f"[load] Loaded {len(df):,} rows from SQLite "
              f"table 'forecast_features'")
    except Exception:
        df = pd.read_csv(csv_path)
        print(f"[load] Loaded {len(df):,} rows from CSV ({csv_path})")
    return df


# ── preprocessing ────────────────────────────────────────────────────────
def preprocess(df: pd.DataFrame):
    """
    Drop NaN lag rows, separate features / target / ids,
    and perform a time-based train/test split.

    Returns
    -------
    X_train, X_test, y_train, y_test, id_train, id_test, feature_names
    """
    lag_cols = [c for c in df.columns if c.startswith("lag_")]
    initial_len = len(df)
    df = df.dropna(subset=lag_cols).reset_index(drop=True)
    print(f"[prep] Dropped {initial_len - len(df):,} rows with NaN lags "
          f"→ {len(df):,} rows remaining")

    # Determine split point
    df["date"] = df["date"].astype(str)
    if df["date"].max() >= SPLIT_DATE and df["date"].min() < SPLIT_DATE:
        print(f"[split] Time-based split at {SPLIT_DATE}")
        train_mask = df["date"] < SPLIT_DATE
    else:
        # Fallback: 80/20 chronological
        dates_sorted = np.sort(df["date"].unique())
        split_idx = int(len(dates_sorted) * 0.8)
        split_date = dates_sorted[split_idx]
        print(f"[split] Fallback 80/20 split at {split_date}")
        train_mask = df["date"] < split_date

    feature_cols = [
        c for c in df.columns
        if c not in ID_COLS + [TARGET]
    ]

    X_train = df.loc[train_mask, feature_cols].copy()
    X_test = df.loc[~train_mask, feature_cols].copy()
    y_train = df.loc[train_mask, TARGET].copy()
    y_test = df.loc[~train_mask, TARGET].copy()
    id_train = df.loc[train_mask, ID_COLS + ["hour"]].copy()
    id_test = df.loc[~train_mask, ID_COLS + ["hour"]].copy()

    print(f"[split] Train: {len(X_train):,}  |  Test: {len(X_test):,}")
    return X_train, X_test, y_train, y_test, id_train, id_test, feature_cols


# ── training ─────────────────────────────────────────────────────────────
def train_model(X_train: pd.DataFrame, y_train: pd.Series):
    """Train a LightGBM regressor and return the fitted model."""
    model = lgb.LGBMRegressor(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train)
    print("[train] LightGBM model training complete")
    return model


# ── evaluation ───────────────────────────────────────────────────────────
def evaluate(model, X_test: pd.DataFrame, y_test: pd.Series):
    """Compute and print R², MAE, RMSE on the test set."""
    preds = model.predict(X_test)
    r2 = r2_score(y_test, preds)
    mae = mean_absolute_error(y_test, preds)
    rmse = np.sqrt(mean_squared_error(y_test, preds))
    print(f"[eval] R²:   {r2:.4f}")
    print(f"[eval] MAE:  {mae:.4f}")
    print(f"[eval] RMSE: {rmse:.4f}")
    return preds, {"r2": r2, "mae": mae, "rmse": rmse}


# ── persistence ──────────────────────────────────────────────────────────
def save_model(model, path: Path = MODEL_PATH):
    """Serialize the trained model with joblib."""
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    print(f"[save] Model saved → {path}")


def save_feature_importance(model, feature_names: list,
                            path: Path = IMPORTANCE_PATH, top_n: int = 15):
    """Write a plain-text feature importance report (top N)."""
    importances = model.feature_importances_
    fi = sorted(zip(feature_names, importances),
                key=lambda x: x[1], reverse=True)

    lines = [
        "ParkVisionSaathi – LightGBM Feature Importance (top 15)",
        "=" * 55,
        f"{'Rank':<6}{'Feature':<30}{'Importance':>12}",
        "-" * 55,
    ]
    for rank, (feat, imp) in enumerate(fi[:top_n], 1):
        lines.append(f"{rank:<6}{feat:<30}{imp:>12}")
    lines.append("-" * 55)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[save] Feature importance → {path}")


def save_predictions(id_test: pd.DataFrame, y_test: pd.Series,
                     preds: np.ndarray, db_path: Path = DB_PATH):
    """Save test-set predictions to the 'forecast_predictions' table."""
    pred_df = id_test.copy()
    pred_df["actual"] = y_test.values
    pred_df["predicted"] = preds
    # Ensure column order
    pred_df = pred_df[["grid_cell_id", "date", "hour", "actual", "predicted"]]

    conn = sqlite3.connect(str(db_path))
    pred_df.to_sql("forecast_predictions", conn, if_exists="replace",
                   index=False)
    conn.close()
    print(f"[save] {len(pred_df):,} predictions → SQLite table "
          f"'forecast_predictions'")


def write_model_card(metrics: dict, n_train: int, n_test: int,
                     feature_names: list, path: Path = MODEL_CARD_PATH):
    """Write a Markdown model card summarising the training run."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    card = f"""\
# ParkVisionSaathi – Violation Count Forecast Model Card

## Overview
| Field | Value |
|---|---|
| **Model** | LightGBM Regressor (v1) |
| **Task** | Predict hourly violation count per 500 m grid cell |
| **Training date** | {now} |
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
| Train | {n_train:,} |
| Test | {n_test:,} |

Split strategy: time-based (train < {SPLIT_DATE}, test ≥ {SPLIT_DATE}).
Falls back to 80/20 chronological if the date range does not support the
fixed threshold.

## Evaluation Metrics (Test Set)
| Metric | Value |
|---|---|
| R² | {metrics['r2']:.4f} |
| MAE | {metrics['mae']:.4f} |
| RMSE | {metrics['rmse']:.4f} |

## Features ({len(feature_names)})
{chr(10).join('- ' + f for f in feature_names)}

## Artefacts
- `models/lightgbm_v1.pkl` – serialised model (joblib)
- `models/feature_importance.txt` – top-15 feature importance
- SQLite table `forecast_predictions` – test-set actuals vs predictions

## Limitations & Caveats
- Data covers Nov 2023 – May 2024 (Bengaluru); model may not generalise
  to other cities or time periods without retraining.
- Grid cells with ≤ 30 observations are excluded during feature engineering.
- Lag features cause the first ~168 rows per cell to be dropped.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(card, encoding="utf-8")
    print(f"[save] Model card → {path}")


# ── main ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("ParkVisionSaathi – LightGBM Forecast Training")
    print("=" * 60)

    # 1. Load features
    df = load_features()

    # 2. Preprocess & split
    X_train, X_test, y_train, y_test, id_train, id_test, feat_names = \
        preprocess(df)

    # 3. Train
    model = train_model(X_train, y_train)

    # 4. Evaluate
    preds, metrics = evaluate(model, X_test, y_test)

    # 5. Save everything
    save_model(model)
    save_feature_importance(model, feat_names)
    save_predictions(id_test, y_test, preds)
    write_model_card(metrics, len(X_train), len(X_test), feat_names)

    print("\n✅ Training pipeline complete.")
