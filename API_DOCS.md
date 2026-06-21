# ParkVision-Saathi — API Documentation

> Backend deliverable. Base URL (local): `http://localhost:8000`
> Interactive docs (auto-generated): `http://localhost:8000/docs`

All endpoints are served from a **pre-computed JSON + in-memory** data layer —
**there is no database**. Nothing makes an external network call at request time,
so the API works fully offline. The canonical Congestion Impact Score (CIS) data
is loaded from `data/processed/zone_congestion_impact.json` (H3 res-9 zones);
legacy hotspot/enrichment views are loaded from `data/mock/` and `data/enriched/`.

## Running the server

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Run from the PROJECT ROOT (absolute imports require this):
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Static dashboard is served at `http://localhost:8000/dashboard/`.

---

## Time filters

CIS endpoints accept a `time_bucket` (and an informational `hour`):

- `time_bucket` — one of `all_day` (default), `night`, `morning_peak`, `midday`,
  `afternoon`. The four sub-buckets cover the data-rich **00:00–16:00 IST** window
  (recorded violations fall off a cliff after ~16:00, so there is deliberately no
  evening bucket). An unknown bucket falls back to the zone's `all_day` rollup.
- `hour` — integer `0–23`, accepted for wire compatibility but informational on
  the CIS endpoints.

> Note: `congestion_impact` (the CIS — "where violations choke traffic") is a
> value **distinct** from the legacy enforcement `risk_score` ("where violations
> happen / patrol priority"). They are no longer aliased.

---

## Health & Service

### `GET /health`
API status, the in-memory data layer, per-source counts, and the self-validating
agent summary.

```bash
curl -s http://localhost:8000/health
```

```json
{
  "status": "ok",
  "data_layer": "json-in-memory",
  "zones_loaded": 15,
  "sources": {
    "hotspots": 15,
    "traffic_context_enriched": 15,
    "calibrated_scores": 10,
    "explanations_cache": 15,
    "congestion_artifact_zones": 2527
  },
  "agent": { "total_zones": 2527, "calibrated": 10, "no_data": 2517, "accurate": 6, "adjusted_up": 3, "adjusted_down": 1 }
}
```

### `GET /`
Service metadata and endpoint index (`version` 2.0.0, `data_layer` "JSON +
in-memory (no database)").

---

## Congestion Impact Score (the QUANTIFY pillar)

### `GET /hotspots`
Top congestion hotspots ranked by **descending CIS**, from the CIS artifact.
Returns `list[HotspotItem]`. Query: `time_bucket` (default `all_day`), `limit`
(default `15`), `hour` (informational). Returns `[]` if the artifact is absent.

```bash
curl -s "http://localhost:8000/hotspots?time_bucket=all_day&limit=15"
```

```json
[
  { "rank": 1, "zone_id": "89618920923ffff", "h3_id": "89618920923ffff",
    "lat": 12.97, "lon": 77.59, "congestion_impact": 49.5, "impact_band": "MODERATE",
    "violation_count": 12109, "station": "Upparpet", "top_violation": "WRONG PARKING",
    "estimated_lane_hours_blocked": 31.2 }
]
```

### `GET /risk/{zone_id}`
Full per-zone Congestion Impact breakdown. For a **real CIS zone** this returns a
`CongestionBreakdown` (validated through the contract), including the five scored
components, the `weights` echo, `impact_band`, `estimated_lane_hours_blocked`, the
real MapMyIndia `mappls_travel_time_ratio` / `is_traffic_degradation_defaulted`
flag, and `calibrated_impact` (a number for agent-calibrated zones, `null`
otherwise). For a **legacy mock-hotspot zone** it falls back to the in-memory zone
shape (game-theory fields). An unknown zone yields a structured **HTTP 404**.
Query: `time_bucket` (default `all_day`), `hour` (informational).

```bash
curl -s "http://localhost:8000/risk/89618920923ffff?time_bucket=all_day"
```

```json
{
  "zone_id": "89618920923ffff", "h3_id": "89618920923ffff", "time_bucket": "all_day",
  "lat": 12.97, "lon": 77.59, "congestion_impact": 49.5, "impact_band": "MODERATE",
  "components": { "lane_blockage": 0.30, "intersection_impact": 0.25, "traffic_degradation": 0.13, "access_blockage": 0.10, "vehicle_size": 0.50, "severity": 0.50 },
  "weights": { "lane_blockage": 0.30, "intersection_impact": 0.25, "traffic_degradation": 0.25, "access_blockage": 0.10, "vehicle_size": 0.10 },
  "estimated_lane_hours_blocked": 31.2, "total_records": 12109, "station": "Upparpet",
  "mappls_travel_time_ratio": 1.259, "is_traffic_degradation_defaulted": false, "calibrated_impact": 44.1
}
```

### `GET /agent/validation-report`
Self-validating agent output: a summary (zones scanned, calibrated, no_data,
accurate/up/down counts) plus the per-zone calibration log. The agent calibrates
each zone's CIS against the real MapMyIndia travel-time ratio, deterministically
and offline.

```bash
curl -s "http://localhost:8000/agent/validation-report"
```

---

## Heatmap (two-layer toggle)

### `GET /heatmap`
Returns a `CongestionHeatmapResponse` for the map layers. Query: `type`
(`risk` | `raw` | `spillover`, default `risk`), `time_bucket` (default `all_day`),
`hour` (informational).

- `risk` — intensity = **CIS** (where violations choke traffic)
- `raw` — intensity = **violation count** (where violations happen)
- `spillover` — agent-calibrated layer

The `risk` and `raw` layers are intentionally **not** the same map — that
difference is the whole point of the toggle.

```bash
curl -s "http://localhost:8000/heatmap?type=risk"
curl -s "http://localhost:8000/heatmap?type=raw"
```

```json
{
  "layer": "risk", "time_bucket": "all_day",
  "points": [ { "lat": 12.97, "lon": 77.59, "h3_id": "89618920923ffff", "intensity": 49.5, "impact_band": "MODERATE" } ],
  "min_intensity": 0.0, "max_intensity": 49.5
}
```

### `GET /heatmap/patrol_overlay`
Patrol-probability overlay for marker sizing. Query: `hour`, `time_bucket`.

---

## Legacy risk views (enforcement-priority `risk_score`)

These serve the legacy `risk_score` from the hotspot-derived zone universe — a
separate concern from the CIS above.

### `GET /risk`
Risk-scored zones, optionally filtered. Query: `hour`, `time_bucket`, `zone_id`,
`risk_label` (`LOW|MEDIUM|HIGH|CRITICAL`), `limit` (default `100`).

### `GET /risk/summary`
Aggregated risk distribution. Query: `hour`, `time_bucket`, `type`.

### `GET /risk/top_zones`
Top `n` highest enforcement-priority zones (default `n=10`).

### `GET /risk/overview`
Dashboard overview: risk distribution, top zone, total zones.

---

## Forecasting (PREDICT pillar — H3-native, map-aligned)

A LightGBM-Poisson daily model trained on the **same H3 res-9 zones as the map**
(`ml/forecast/build_h3_forecast.py` → `data/processed/forecasts.json`), so the
predicted hotspots line up exactly with the Congestion Impact layer. Served
statically from the artifact; falls back to a historical-volume proxy if absent.

### `GET /forecast/top_risk_zones`
Tomorrow's top H3 zones by predicted violation count (default `n=10`). Each row
carries `zone_id`/`h3_id`, `lat`/`lon`, `predicted_count`, `predicted_risk`
(0–100 percentile rank), `predicted_band`, and a Poisson `confidence_lower/upper`.

### `GET /forecast/zones`
Per-H3-zone next-day forecast. Query: `zone_id` (returns just that zone), `limit`.

### `GET /forecast/accuracy`
**Real** held-out accuracy of the H3 model (leakage-free chronological split:
train < Mar, validate = Mar, test ≥ Apr). Headline is **Precision@10** — the
share of each test day's true top-10 hotspot H3 zones the model ranks in its own
top-10 — plus MAE / RMSE. Falls back to the coarser ~500 m-grid LightGBM+CatBoost
ensemble's metrics (`models/ensemble_config.json`), then a proxy note.

```json
{ "model": "LightGBM Poisson (H3 res-9, daily)", "is_proxy": false,
  "spatial_unit": "H3 resolution 9 (same as the Congestion Impact map)",
  "precision_at_10": 0.45, "mae": 0.83, "rmse": 4.43, "n_test_days": 8,
  "generated_for": "2024-04-09",
  "summary": "Correctly identifies ~4 of tomorrow's top-10 H3 hotspots (Precision@10 = 0.45 on the held-out April test set)." }
```

> Honest note: Precision@10 is lower on fine-grained H3 (2,527 zones, sparse
> 8-day April test window) than on the coarse ~500 m grid (≈ 0.68) — but the H3
> forecast is the one that actually aligns with the map. See the README.

---

## Game Theory

### `GET /game/stackelberg_strategy`
Stackelberg mixed-strategy patrol probabilities (∝ score^1.5, normalized).

### `GET /game/violator_adaptation`
Violator expected-utility and adaptation scores.

### `GET /game/spillover_forecast`
Waterbed / spillover predictions. Query: `spillover_type`, `limit`.

### `GET /game/summary`
Combined summary of the three game-theory layers.

### `GET /game/spillover_arrows`
Pre-computed displacement arrows for the waterbed visualization.

### `GET /game/whatif_coverage`
Pre-computed what-if coverage across team counts.

---

## Simulation

### `POST /simulate`
Greedy patrol allocation over Stackelberg probabilities → team assignments,
coverage %, uncovered high-risk zones, and waterbed spillover. Returns
`SimulationResponse`.

```bash
curl -s -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"num_teams":5,"hour":9,"strategy":"stackelberg"}'
```

---

## Stations

### `GET /stations`
All police stations with summary stats.

### `GET /stations/{station}/priority_areas`
Ranked priority zones under a station. Query: `hour` (default `9`), `limit`.

### `GET /stations/{station}/summary`
Risk-label breakdown for a station.

---

## Explanations

### `POST /explain`
Natural-language explanation of a zone's congestion risk (`ExplainResponse`).
Resolves **both** the legacy hotspot zones and the 2,527 real CIS zones. Tiered
and offline-safe: **cache** (pre-generated) → **live Gemini** (only when
`GEMINI_API_KEY` is set; lazy, any failure falls through) → **grounded fallback**
(built only from the zone's real fields — no hallucination, no network). The
`source` field reports which tier answered (`cache` | `gemini` | `fallback`).

```bash
curl -s -X POST http://localhost:8000/explain \
  -H "Content-Type: application/json" \
  -d '{"zone_id":"89618920923ffff","hour":9}'
```

---

## Traffic Context

### `GET /traffic/{zone_id}`
Real MapMyIndia travel-time ratio, road name/type, and nearby POIs for a zone
(`TrafficContext`).

```bash
curl -s "http://localhost:8000/traffic/8928308280fffff"
```

---

## Notes on schema alignment

- The Congestion Impact Score is keyed by **H3 resolution 9** (`h3_id` / `zone_id`)
  from the offline-built `data/processed/zone_congestion_impact.json` artifact.
- `congestion_impact` (CIS) and `risk_score` (legacy enforcement priority) are
  **distinct values from distinct sources** — they are not aliased.
- Every route is served at the bare path **and** under an `/api` prefix
  (e.g. `/hotspots` and `/api/hotspots`).
- No database, no Redis, no Docker — pre-computed JSON loaded into memory, so the
  demo survives offline.
