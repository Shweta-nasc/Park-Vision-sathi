"""
build_h3_forecast_v2.py — forecast with MapMyIndia road context (Task 8).

Additive shadow of ``build_h3_forecast``: it reuses the same leakage-free panel
and trainer, but adds two features sourced from MapMyIndia (Task 1 + Task 8):

  * ``neighbor_spatial_lag`` — mean of the zone's road-connected neighbors'
    ``lag_1d`` (driving-time adjacency from ``ml.enrichment.adjacency``), so the
    model uses real road-network neighbors instead of straight-line distance.
  * ``road_size_proxy`` — 0..3 road-size class from the collector's free-flow
    speed (``ml.enrichment.road_geometry``).

It trains the v2 model AND the v1 baseline on the same split and reports
**Precision@10 old vs new** (and MAE/RMSE). Improvement is NOT forced — when the
adjacency / observations inputs are absent both new features are 0 everywhere, so
v2 reduces to v1 and the metrics match (an honest "no change without real data").

Writes ``data/processed/forecasts_v2.json`` (never overwrites ``forecasts.json``).
Offline and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

import numpy as np
import pandas as pd

from ml.enrichment.adjacency import neighbor_map
from ml.enrichment.road_geometry import road_size_proxy
from ml.forecast.build_h3_forecast import (
    FEATURES,
    _band,
    _build_panel,
    _daily_counts,
    _next_day_rows,
    _train,
)
from ml.congestion.build_artifact import _resolve_real_csv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_PATH_V2 = PROJECT_ROOT / "data" / "processed" / "forecasts_v2.json"
DEFAULT_ADJACENCY_PATH = PROJECT_ROOT / "data" / "enriched" / "zone_adjacency.json"
DEFAULT_OBSERVATIONS_PATH = PROJECT_ROOT / "data" / "enriched" / "congestion_observations.json"

# The two additive road-context features.
SPATIAL_FEATURES = ["neighbor_spatial_lag", "road_size_proxy"]
FEATURES_V2 = FEATURES + SPATIAL_FEATURES


def _load_json(path: Optional[Path]) -> dict:
    if not path:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def road_speeds_from_observations(observations: Mapping) -> dict[str, float]:
    """Build ``{h3_id: free_flow_speed_kmph}`` from the Task 1 observations."""
    out: dict[str, float] = {}
    for h3_id, obs in observations.items():
        if not isinstance(obs, Mapping):
            continue
        ffs = obs.get("free_flow_speed_kmph")
        if isinstance(ffs, (int, float)) and not isinstance(ffs, bool):
            out[str(h3_id)] = float(ffs)
    return out


def add_spatial_features(
    panel: pd.DataFrame,
    adjacency_map: Mapping[str, list],
    road_speeds: Mapping[str, float],
) -> pd.DataFrame:
    """Attach ``neighbor_spatial_lag`` + ``road_size_proxy`` to the dense panel."""
    panel = panel.copy()
    panel["road_size_proxy"] = panel["h3_id"].map(
        lambda z: float(road_size_proxy(road_speeds.get(z)))
    )
    panel["neighbor_spatial_lag"] = 0.0
    if adjacency_map:
        lag_pivot = panel.pivot(index="date", columns="h3_id", values="lag_1d")
        for zone, neighbors in adjacency_map.items():
            cols = [n for n in neighbors if n in lag_pivot.columns]
            if not cols:
                continue
            series = lag_pivot[cols].mean(axis=1)
            mask = panel["h3_id"] == zone
            panel.loc[mask, "neighbor_spatial_lag"] = panel.loc[mask, "date"].map(series).to_numpy()
    return panel


def _next_day_rows_v2(panel, adjacency_map, road_speeds):
    """v1 next-day rows + the two road-context features for the forecast day."""
    future, target_date = _next_day_rows(panel)
    future = future.copy()
    future["road_size_proxy"] = future["h3_id"].map(
        lambda z: float(road_size_proxy(road_speeds.get(z)))
    )
    lag_by_zone = dict(zip(future["h3_id"], future["lag_1d"]))

    def _nb_lag(zone: str) -> float:
        nbrs = adjacency_map.get(zone, [])
        vals = [lag_by_zone[n] for n in nbrs if n in lag_by_zone]
        return float(sum(vals) / len(vals)) if vals else 0.0

    future["neighbor_spatial_lag"] = future["h3_id"].map(_nb_lag)
    return future, target_date


def build_h3_forecast_v2(
    csv_path: Optional[Path] = None,
    *,
    daily: Optional[pd.DataFrame] = None,
    adjacency: Optional[Mapping] = None,
    observations: Optional[Mapping] = None,
    adjacency_path: Optional[Path] = DEFAULT_ADJACENCY_PATH,
    observations_path: Optional[Path] = DEFAULT_OBSERVATIONS_PATH,
    out_path: Path = OUT_PATH_V2,
    explain_out: Optional[Path] = None,
    compare: bool = True,
) -> dict:
    """Train the v2 forecaster (+ v1 baseline) and write the v2 artifact.

    When ``explain_out`` is set, also writes a per-zone SHAP explanations sidecar
    (Task 9) for the v2 model's next-day forecast.
    """
    if daily is None:
        csv_path = Path(csv_path) if csv_path else _resolve_real_csv()
        daily = _daily_counts(csv_path)
    panel = _build_panel(daily)

    adj_report = adjacency if adjacency is not None else _load_json(adjacency_path)
    obs = observations if observations is not None else _load_json(observations_path)
    adj_map = neighbor_map(adj_report) if adj_report else {}
    road_speeds = road_speeds_from_observations(obs) if obs else {}

    panel = add_spatial_features(panel, adj_map, road_speeds)

    model_v2, metrics = _train(panel, FEATURES_V2)
    metrics = dict(metrics)
    if compare:
        _, metrics_v1 = _train(panel, FEATURES)
        metrics["precision_at_10_baseline"] = metrics_v1["precision_at_10"]
        metrics["mae_baseline"] = metrics_v1["mae"]
        metrics["rmse_baseline"] = metrics_v1["rmse"]
        metrics["precision_at_10_delta"] = round(
            metrics["precision_at_10"] - metrics_v1["precision_at_10"], 4
        )
    metrics["spatial_features_active"] = bool(adj_map)
    metrics["road_proxy_active"] = bool(road_speeds)

    future, target_date = _next_day_rows_v2(panel, adj_map, road_speeds)
    future["pred"] = np.clip(model_v2.predict(future[FEATURES_V2]), 0, None)
    future["pct"] = future["pred"].rank(pct=True)

    # Optional SHAP explainability sidecar (Task 9).
    if explain_out is not None:
        from ml.forecast.forecast_explain import export_forecast_explanations
        export_forecast_explanations(model_v2, future, FEATURES_V2, Path(explain_out))

    zones = {}
    for _, r in future.iterrows():
        pred = float(r["pred"])
        se = float(np.sqrt(pred))
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
        "model": "LightGBM Poisson (H3 res-9, daily) + MapMyIndia road context (v2)",
        "is_proxy": False,
        "target": "violation_count per H3 zone per day",
        "generated_for": str(target_date),
        "trained_through": str(panel["date"].max().date()),
        "features": FEATURES_V2,
        "baseline_features": FEATURES,
        "spatial_features": SPATIAL_FEATURES,
        "metrics": metrics,
        "n_zones": len(zones),
        "zones": zones,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(artifact, f, separators=(",", ":"))
    print(f"[h3-forecast-v2] wrote {out_path} — {len(zones):,} zones, "
          f"Precision@10 {metrics.get('precision_at_10_baseline')} -> {metrics['precision_at_10']} "
          f"(spatial_active={metrics['spatial_features_active']}, "
          f"road_active={metrics['road_proxy_active']})")
    return artifact


if __name__ == "__main__":
    build_h3_forecast_v2()
