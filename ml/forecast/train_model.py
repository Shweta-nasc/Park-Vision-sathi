"""
train_model.py – LightGBM forecasting for ParkVisionSaathi.

Persists:
    models/lightgbm_v1.pkl
    models/feature_importance.txt
    SQLite: forecast_predictions
    models/MODEL_CARD.md

ADDITIONS vs v1
---------------
- Early stopping via lgb.early_stopping callback (val set = last 10% of train).
- Per-hour evaluation: prints R² for each hour so we can spot weak hours.
- ``violation_rate`` and new cyclical features automatically included in feature_cols.
- Predictions clipped to ≥ 0 (violations can't be negative).
- Model card now lists per-hour R² table.
- ``data_rich_only`` flag: if True, evaluate only on hours 0–15 (avoids temporal cliff
  distorting metrics with near-zero-count hours).
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
    raise ImportError("pip install lightgbm")

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
        print(f"[load] {len(df):,} rows from SQLite 'forecast_features'")
    except Exception:
        df = pd.read_csv(csv_path)
        print(f"[load] {len(df):,} rows from CSV")
    return df


# ── Preprocessing ─────────────────────────────────────────────────────────

def preprocess(df: pd.DataFrame):
    lag_cols = [c for c in df.columns if c.startswith("lag_")]
    n_before = len(df)
    df = df.dropna(subset=lag_cols).reset_index(drop=True)
    print(f"[prep] Dropped {n_before - len(df):,} NaN-lag rows → {len(df):,} remaining")

    df["date"] = df["date"].astype(str)

    if df["date"].max() >= SPLIT_DATE and df["date"].min() < SPLIT_DATE:
        print(f"[split] Time split at {SPLIT_DATE}")
        train_mask = df["date"] < SPLIT_DATE
    else:
        dates_sorted = np.sort(df["date"].unique())
        split_date   = dates_sorted[int(len(dates_sorted) * 0.8)]
        print(f"[split] Fallback 80/20 at {split_date}")
        train_mask = df["date"] < split_date

    feature_cols = [c for c in df.columns if c not in ID_COLS + [TARGET]]

    X_train = df.loc[train_mask, feature_cols].copy()
    X_test  = df.loc[~train_mask, feature_cols].copy()
    y_train = df.loc[train_mask, TARGET].copy()
    y_test  = df.loc[~train_mask, TARGET].copy()
    id_test = df.loc[~train_mask, ID_COLS + ["hour"]].copy()

    print(f"[split] Train: {len(X_train):,}  Test: {len(X_test):,}")
    return X_train, X_test, y_train, y_test, id_test, feature_cols


# ── Training ──────────────────────────────────────────────────────────────

def train_model(X_train: pd.DataFrame, y_train: pd.Series):
    """Train LightGBM with early stopping on a 10% holdout."""
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
    print(f"[train] LightGBM done.  Best iteration: {n_trees}")
    return model


# ── Evaluation ────────────────────────────────────────────────────────────

def evaluate(model, X_test: pd.DataFrame, y_test: pd.Series,
             id_test: pd.DataFrame, data_rich_only: bool = True):
    preds = np.clip(model.predict(X_test), 0, None)   # no negative predictions

    # ── Overall metrics ────────────────────────────────────────────────────
    r2   = r2_score(y_test, preds)
    mae  = mean_absolute_error(y_test, preds)
    rmse = np.sqrt(mean_squared_error(y_test, preds))
    print(f"[eval] Overall  R²={r2:.4f}  MAE={mae:.4f}  RMSE={rmse:.4f}")

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

    return preds, {"r2": r2, "mae": mae, "rmse": rmse,
                   "per_hour_r2": per_hour}


# ── Persistence ───────────────────────────────────────────────────────────

def save_model(model, path: Path = MODEL_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    print(f"[save] Model → {path}")


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
    print(f"[save] {len(pred_df):,} predictions → forecast_predictions")


def write_model_card(metrics: dict, n_train: int, n_test: int,
                     feature_names: list, path: Path = MODEL_CARD_PATH):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    per_hour_table = "\n".join(
        f"| {h} | {r2} |"
        for h, r2 in sorted(metrics.get("per_hour_r2", {}).items())
    )

    card = f"""\
# ParkVisionSaathi – Violation Count Forecast (LightGBM v1)

## Overview
| Field | Value |
|---|---|
| **Model** | LightGBM Regressor |
| **Task** | Predict hourly violation count per 500 m grid cell |
| **Date** | {now} |

## Hyperparameters
n_estimators=1000 (early stopping), lr=0.05, max_depth=6, num_leaves=31,
subsample=0.8, colsample_bytree=0.8, random_state=42

## Data Split
Train: {n_train:,}  |  Test: {n_test:,}  |  Split: time-based at {SPLIT_DATE}

## Overall Metrics
| Metric | Value |
|---|---|
| R² | {metrics['r2']:.4f} |
| MAE | {metrics['mae']:.4f} |
| RMSE | {metrics['rmse']:.4f} |

## Per-Hour R² (⚠️ hours ≥16 have sparse data)
| Hour | R² |
|---|---|
{per_hour_table}

## Features ({len(feature_names)})
{chr(10).join('- ' + f for f in feature_names)}

## Caveats
- Data covers Nov 2023 – May 2024 (Bengaluru only).
- Hours 16–23 contain <4% of data (temporal cliff). Metrics for those hours
  are not reliable.
- Grid cells ≤30 observations excluded.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(card, encoding="utf-8")
    print(f"[save] Model card → {path}")


# ── Main ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("ParkVisionSaathi – LightGBM Training")
    print("=" * 60)

    df = load_features()
    X_train, X_test, y_train, y_test, id_test, feat_names = preprocess(df)
    model = train_model(X_train, y_train)
    preds, metrics = evaluate(model, X_test, y_test, id_test)

    save_model(model)
    save_feature_importance(model, feat_names)
    save_predictions(id_test, y_test, preds)
    write_model_card(metrics, len(X_train), len(X_test), feat_names)

    print("\n✅ Training complete.")
