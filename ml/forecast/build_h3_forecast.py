"""
build_h3_forecast.py — H3-native daily violation forecaster (PREDICT pillar).

WHY THIS EXISTS
---------------
The original LightGBM+CatBoost ensemble (ml/forecast/train_model.py) is keyed to
a custom ~500 m lat/lon grid (`grid_cell_id` like "2563_15537") and trained off
the SQLite DB. The live map is keyed to **H3 resolution 9** (the Congestion
Impact artifact), so those grid predictions cannot be placed on the map without a
lossy centroid hack. This module trains a forecaster on the SAME H3 zones the map
uses, so "tomorrow's predicted hotspots" line up exactly with the Congestion
Impact layer — no re-keying, no fabrication.

It is self-contained (reads the raw violations CSV directly, reusing the CIS
build's H3/IST helpers), uses only installed deps (pandas + h3 + lightgbm;
CatBoost is intentionally NOT required), and is deterministic. It writes a single
committed artifact, `data/processed/forecasts.json`, keyed by `h3_id`, that the
backend serves statically — so deployment runs nothing.

METHOD (leakage-free, honest)
-----------------------------
1. Raw CSV → per-(h3_id, IST date) daily violation_count over the data-rich
   window (00:00–16:00 IST, matching the CIS temporal-cliff guard).
2. Dense (zone × day) panel; strictly-past features only: lag_1d / lag_7d,
   trailing rolling mean/std (shift(1) then rolling), expanding zone mean, and
   calendar fields. The target never enters its own features.
3. Chronological split (train < 2024-03-01, validate = March, test ≥ 2024-04-01).
   LightGBM Poisson, early-stopped on the March fold, then evaluated once on the
   held-out April test set.
4. Metrics: daily **Precision@10** (share of each test day's true top-10 hotspot
   zones the model ranks in its top-10) + MAE / RMSE.
5. One-step-ahead forecast: predict each zone's expected count for the day after
   the last observed date and write it (with a Poisson confidence band and a
   percentile-ranked 0–100 `predicted_risk` + band) to forecasts.json.

Usage
-----
    python -m ml.forecast.build_h3_forecast
    python ml/forecast/build_h3_forecast.py            # same
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.congestion.build_artifact import (
    LAT_COL, LON_COL, TIMESTAMP_COL,
    _ist_hours, _resolve_real_csv, h3_centroid, h3_id_for,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_PATH = PROJECT_ROOT / "data" / "processed" / "forecasts.json"

# Data-rich window (matches CIS): keep only 00:00–15:59 IST.
DATA_RICH_HOURS = set(range(16))

# Chronological split (IST dates), mirroring the grid ensemble for comparability.
VAL_START = pd.Timestamp("2024-03-01").date()
TEST_START = pd.Timestamp("2024-04-01").date()

SEED = 42
PRECISION_K = 10

FEATURES = [
    "lag_1d", "lag_7d", "rolling_mean_7d", "rolling_mean_14d", "rolling_std_7d",
    "zone_expanding_mean", "dow", "month", "is_weekend", "lat", "lon",
]


# ── 1. Raw CSV → per-(h3_id, date) daily counts ──────────────────────────────

def _daily_counts(csv_path: Path) -> pd.DataFrame:
    """Aggregate the raw violations CSV to one row per (h3_id, IST date)."""
    print(f"[h3-forecast] reading {csv_path}")
    df = pd.read_csv(csv_path, low_memory=False)
    df[LAT_COL] = pd.to_numeric(df.get(LAT_COL), errors="coerce")
    df[LON_COL] = pd.to_numeric(df.get(LON_COL), errors="coerce")
    df = df.dropna(subset=[LAT_COL, LON_COL])

    hours = _ist_hours(df[TIMESTAMP_COL])
    parsed = pd.to_datetime(df[TIMESTAMP_COL], errors="coerce", utc=True).dt.tz_convert(
        "Asia/Kolkata"
    )
    df = df.assign(__hour=hours, __date=parsed.dt.date)
    df = df.dropna(subset=["__hour", "__date"])
    df = df[df["__hour"].astype(int).isin(DATA_RICH_HOURS)]
    if df.empty:
        raise RuntimeError("No data-rich rows found in the CSV.")

    df["h3_id"] = [h3_id_for(la, lo) for la, lo in zip(df[LAT_COL], df[LON_COL])]
    daily = (
        df.groupby(["h3_id", "__date"]).size().reset_index(name="violation_count")
        .rename(columns={"__date": "date"})
    )
    daily["date"] = pd.to_datetime(daily["date"])
    print(f"[h3-forecast] {len(daily):,} (zone, day) rows across "
          f"{daily['h3_id'].nunique():,} H3 zones, "
          f"{daily['date'].min().date()} → {daily['date'].max().date()}")
    return daily


# ── 2. Dense panel + strictly-past features ──────────────────────────────────

def _build_panel(daily: pd.DataFrame) -> pd.DataFrame:
    """Dense (zone × day) panel with leakage-free autoregressive + calendar features."""
    all_days = pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")
    zones = daily["h3_id"].unique()
    # Dense index: every zone × every day in range (missing day = 0 violations).
    idx = pd.MultiIndex.from_product([zones, all_days], names=["h3_id", "date"])
    panel = (
        daily.set_index(["h3_id", "date"]).reindex(idx, fill_value=0)
        .reset_index().sort_values(["h3_id", "date"])
    )

    g = panel.groupby("h3_id")["violation_count"]
    panel["lag_1d"] = g.shift(1)
    panel["lag_7d"] = g.shift(7)
    shifted = g.shift(1)
    panel["rolling_mean_7d"] = shifted.rolling(7, min_periods=1).mean().reset_index(level=0, drop=True)
    panel["rolling_mean_14d"] = shifted.rolling(14, min_periods=1).mean().reset_index(level=0, drop=True)
    panel["rolling_std_7d"] = shifted.rolling(7, min_periods=2).std().reset_index(level=0, drop=True)
    # Expanding mean of strictly-past values (a stable per-zone level signal).
    panel["zone_expanding_mean"] = shifted.expanding(min_periods=1).mean().reset_index(level=0, drop=True)

    panel["dow"] = panel["date"].dt.dayofweek
    panel["month"] = panel["date"].dt.month
    panel["is_weekend"] = (panel["dow"] >= 5).astype(int)

    centroids = {z: h3_centroid(z) for z in zones}
    panel["lat"] = panel["h3_id"].map(lambda z: centroids[z][0])
    panel["lon"] = panel["h3_id"].map(lambda z: centroids[z][1])

    for col in ("lag_1d", "lag_7d", "rolling_mean_7d", "rolling_mean_14d",
                "rolling_std_7d", "zone_expanding_mean"):
        panel[col] = panel[col].fillna(0.0)
    panel["__date_only"] = panel["date"].dt.date
    return panel


# ── 3–4. Train + evaluate ─────────────────────────────────────────────────────

def _daily_precision_at_k(test: pd.DataFrame, k: int = PRECISION_K) -> float:
    """Mean over test days of |top-k predicted ∩ top-k actual| / k."""
    scores = []
    for _, day in test.groupby("__date_only"):
        if len(day) < k or day["violation_count"].sum() == 0:
            continue
        actual_top = set(day.nlargest(k, "violation_count")["h3_id"])
        pred_top = set(day.nlargest(k, "pred")["h3_id"])
        scores.append(len(actual_top & pred_top) / k)
    return float(np.mean(scores)) if scores else 0.0


def _train(panel: pd.DataFrame, features: list[str] = FEATURES):
    import lightgbm as lgb

    train = panel[panel["__date_only"] < VAL_START]
    val = panel[(panel["__date_only"] >= VAL_START) & (panel["__date_only"] < TEST_START)]
    test = panel[panel["__date_only"] >= TEST_START]
    print(f"[h3-forecast] split rows — train {len(train):,} | val {len(val):,} | test {len(test):,}")

    params = dict(
        objective="poisson", metric="poisson", learning_rate=0.05,
        num_leaves=63, min_data_in_leaf=50, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=1, seed=SEED, num_threads=1,
        deterministic=True, verbose=-1,
    )
    dtrain = lgb.Dataset(train[features], label=train["violation_count"])
    dval = lgb.Dataset(val[features], label=val["violation_count"], reference=dtrain)
    booster = lgb.train(
        params, dtrain, num_boost_round=1500, valid_sets=[dval],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)],
    )

    # Refit on train+val through the chosen iteration, then evaluate once on test.
    fit = panel[panel["__date_only"] < TEST_START]
    dfit = lgb.Dataset(fit[features], label=fit["violation_count"])
    final = lgb.train(params, dfit, num_boost_round=booster.best_iteration or 300,
                      callbacks=[lgb.log_evaluation(0)])

    test = test.copy()
    test["pred"] = np.clip(final.predict(test[features]), 0, None)
    mae = float(np.mean(np.abs(test["pred"] - test["violation_count"])))
    rmse = float(np.sqrt(np.mean((test["pred"] - test["violation_count"]) ** 2)))
    p_at_10 = _daily_precision_at_k(test, PRECISION_K)
    n_test_days = test["__date_only"].nunique()
    print(f"[h3-forecast] held-out: Precision@10={p_at_10:.3f} MAE={mae:.3f} "
          f"RMSE={rmse:.3f} over {n_test_days} test days")

    return final, dict(precision_at_10=round(p_at_10, 4), mae=round(mae, 4),
                       rmse=round(rmse, 4), n_test_days=int(n_test_days),
                       best_iteration=int(final.num_trees()))


# ── 5. One-step-ahead forecast per zone ───────────────────────────────────────

def _next_day_rows(panel: pd.DataFrame) -> pd.DataFrame:
    """Build a feature row per zone for the day AFTER the last observed date."""
    last_date = panel["date"].max()
    next_date = last_date + pd.Timedelta(days=1)
    rows = []
    for zone, g in panel.groupby("h3_id"):
        g = g.sort_values("date")
        counts = g.set_index("date")["violation_count"]
        recent = counts.tail(14)
        rows.append({
            "h3_id": zone,
            "lag_1d": float(counts.iloc[-1]),
            "lag_7d": float(counts.iloc[-7]) if len(counts) >= 7 else 0.0,
            "rolling_mean_7d": float(recent.tail(7).mean()),
            "rolling_mean_14d": float(recent.mean()),
            "rolling_std_7d": float(recent.tail(7).std(ddof=1)) if len(recent) >= 2 else 0.0,
            "zone_expanding_mean": float(counts.mean()),
            "dow": int(next_date.dayofweek),
            "month": int(next_date.month),
            "is_weekend": int(next_date.dayofweek >= 5),
            "lat": float(g["lat"].iloc[0]),
            "lon": float(g["lon"].iloc[0]),
        })
    out = pd.DataFrame(rows).fillna(0.0)
    return out, next_date.date()


def _band(percentile: float) -> str:
    if percentile >= 0.90:
        return "CRITICAL"
    if percentile >= 0.70:
        return "SEVERE"
    if percentile >= 0.40:
        return "MODERATE"
    return "MINIMAL"


def build_h3_forecast(csv_path: Path | None = None, out_path: Path = OUT_PATH) -> dict:
    """Train the H3 forecaster and write the per-zone next-day forecast artifact."""
    csv_path = Path(csv_path) if csv_path else _resolve_real_csv()
    daily = _daily_counts(csv_path)
    panel = _build_panel(daily)
    model, metrics = _train(panel)

    future, target_date = _next_day_rows(panel)
    future["pred"] = np.clip(model.predict(future[FEATURES]), 0, None)
    # Percentile rank → a 0–100 "predicted_risk" + band for the map.
    future["pct"] = future["pred"].rank(pct=True)

    zones = {}
    for _, r in future.iterrows():
        pred = float(r["pred"])
        se = float(np.sqrt(pred))  # Poisson sd
        zones[r["h3_id"]] = {
            "predicted_count": round(pred, 2),
            "predicted_risk": round(float(r["pct"]) * 100, 1),
            "predicted_band": _band(float(r["pct"])),
            "confidence_lower": round(max(0.0, pred - 1.96 * se), 2),
            "confidence_upper": round(pred + 1.96 * se, 2),
            "lat": round(float(r["lat"]), 6),
            "lon": round(float(r["lon"]), 6),
        }

    artifact = {
        "model": "LightGBM Poisson (H3 res-9, daily)",
        "is_proxy": False,
        "target": "violation_count per H3 zone per day",
        "generated_for": str(target_date),
        "trained_through": str(panel["date"].max().date()),
        "split": {"val_start": str(VAL_START), "test_start": str(TEST_START)},
        "features": FEATURES,
        "metrics": metrics,
        "n_zones": len(zones),
        "zones": zones,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(artifact, f, separators=(",", ":"))
    print(f"[h3-forecast] wrote {out_path} — {len(zones):,} zones, "
          f"Precision@10={metrics['precision_at_10']}, target {target_date}")
    return artifact


if __name__ == "__main__":
    build_h3_forecast()
