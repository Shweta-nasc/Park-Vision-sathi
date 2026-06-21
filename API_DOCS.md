# ParkVision-Saathi — API Reference

**Version:** 2.0.0
**Base URL (local):** `http://localhost:8000`
**Interactive docs:** `http://localhost:8000/docs` (Swagger UI) · `http://localhost:8000/redoc`
**Static dashboard:** `http://localhost:8000/dashboard/`

ParkVision-Saathi is a parking-enforcement intelligence API for Bengaluru. It
turns a raw parking-violation dataset into three decision-support layers:

| Pillar | Question it answers | Key endpoints |
| :-- | :-- | :-- |
| **QUANTIFY** | *How much does illegal parking choke traffic here?* | `/hotspots`, `/risk/{zone_id}`, `/heatmap`, `/agent/validation-report` |
| **PREDICT** | *Where will violations happen next?* | `/forecast/*` |
| **OPTIMIZE** | *Where do we send patrol teams, and what happens when we do?* | `/game/*`, `/simulate`, `/stations/*` |

---

## Table of contents

1. [Architecture & design principles](#1-architecture--design-principles)
2. [Running the API](#2-running-the-api)
3. [Core concepts](#3-core-concepts)
4. [Conventions (auth, CORS, errors, params)](#4-conventions)
5. [Data schemas](#5-data-schemas)
6. [Endpoint reference](#6-endpoint-reference)
   - [Health & service](#61-health--service)
   - [Congestion Impact — QUANTIFY](#62-congestion-impact--quantify)
   - [Enforcement risk views](#63-enforcement-risk-views)
   - [Forecasting — PREDICT](#64-forecasting--predict)
   - [Game theory & simulation — OPTIMIZE](#65-game-theory--simulation--optimize)
   - [Stations](#66-stations)
   - [Explanations](#67-explanations)
   - [Traffic context](#68-traffic-context)
   - [Self-validating agent](#69-self-validating-agent)
7. [Field glossary](#7-field-glossary)
8. [HTTP status codes](#8-http-status-codes)
9. [Versioning & changelog](#9-versioning--changelog)

---

## 1. Architecture & design principles

The API is deliberately split from the modelling work (see `docs/ML_PIPELINE.md`):

- **No database, no network at request time.** All analytics are pre-computed
  offline into JSON artifacts under `data/`. At startup, `backend/app/data_loader.py`
  loads them once into an in-memory store; every request reads from RAM. This
  makes the API fast, deterministic, and **fully offline-capable** — a hard
  requirement for an unreliable demo network.
- **Single source of truth = the Congestion Impact artifact.** The served zones
  are real Bengaluru **H3 resolution-9** cells. Identifiers line up across the
  map, the forecast, the game theory, the traffic enrichment, and the agent.
- **Every route is mounted twice:** at the bare path (e.g. `/hotspots`) and under
  an `/api` prefix (e.g. `/api/hotspots`). They are identical; use whichever your
  client expects.
- **Two zone "universes"** (see [§3](#3-core-concepts)): the full **2,527-zone**
  Congestion Impact artifact (city-wide map/forecast) and a curated **top-60
  hotspot universe** (markers, game theory, simulation, stations).

---

## 2. Running the API

```bash
# 1. install runtime deps (lean — no ML libs needed to SERVE)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-backend.txt        # or requirements.txt for ML+tests

# 2. run from the PROJECT ROOT (absolute imports require this)
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

- Health check: `GET /health`
- The static vanilla dashboard is served at `/dashboard/`.
- **Deployment (Render):** see `render.yaml`. Build = `pip install -r
  requirements-backend.txt`; start = `uvicorn backend.app.main:app --host 0.0.0.0
  --port $PORT`; health check path = `/health`.
- **Regenerating the data artifacts** the API serves: `python run_pipeline.py`
  (offline, no DB). See `docs/ML_PIPELINE.md`.

---

## 3. Core concepts

### 3.1 Zone identifiers (H3)

Every zone is an [Uber H3](https://h3geo.org/) **resolution-9** cell id, e.g.
`8960145b553ffff` (≈ 0.1 km² hexagons). The fields `zone_id`, `h3_id`, and
`grid_cell_id` all carry this same id (the multiple names are wire-compatibility
aliases for different clients). Coordinates (`lat`/`lon`, `grid_lat`/`grid_lon`)
are the H3 cell centroid.

### 3.2 The two zone universes

| Universe | Size | What it is | Drives |
| :-- | :-- | :-- | :-- |
| **Congestion Impact artifact** | 2,527 zones | Every H3 cell in the city with at least one recorded violation, scored offline | `/hotspots`, `/risk/{zone_id}` (CIS breakdown), `/heatmap?type=risk\|raw`, `/forecast/*`, `/agent/validation-report` |
| **Hotspot / OPTIMIZE universe** | top **60** | The 60 highest-volume zones, shaped at startup into the operational zone object | `/risk` (list), `/risk/summary`, `/risk/top_zones`, `/risk/overview`, `/heatmap?type=violator\|spillover`, `/heatmap/patrol_overlay`, `/game/*`, `/simulate`, `/stations/*`, `/traffic` lookups |

This split keeps the city-wide map rich (2,527 cells) while keeping operational
math (patrol coverage %, station rollups) meaningful over a focused hotspot set.

### 3.3 The two scores (they are intentionally different)

| Score | Range | Meaning | Source |
| :-- | :-- | :-- | :-- |
| **`congestion_impact`** (CIS) | 0–100 | *Where violations choke traffic flow.* A weighted blend of lane blockage, junction disruption, real travel-time degradation, transit/footpath blockage, and vehicle size. | `data/processed/zone_congestion_impact.json` |
| **`risk_score`** | 0–100 | *Where violations happen (enforcement priority).* The zone's relative violation-volume rank within the hotspot universe. | derived in `data_loader._build_zone_universe` |

> **They are NOT aliases.** Example: zone `8960145b553ffff` (Upparpet, Subedar
> Chatram Rd) has the **highest** `risk_score` (100, busiest by volume) but a
> **MINIMAL** `congestion_impact` (≈15) — a wide arterial absorbs the parking
> load. This "density ≠ impact" distinction is the project's central thesis and
> is exactly what the two-layer heatmap toggle visualizes.

### 3.4 Bands & labels

**Congestion impact band** (`impact_band`), right-closed thresholds:

| Band | CIS range |
| :-- | :-- |
| `MINIMAL` | 0 – 25 |
| `MODERATE` | 26 – 50 |
| `SEVERE` | 51 – 75 |
| `CRITICAL` | 76 – 100 |

**Enforcement risk label** (`risk_label`):

| Label | `risk_score` range |
| :-- | :-- |
| `LOW` | 0 – 33 |
| `MEDIUM` | 34 – 66 |
| `HIGH` | 67 – 79 |
| `CRITICAL` | 80 – 100 |

### 3.5 Time filters

CIS endpoints accept a `time_bucket`:

- `all_day` (default), `night`, `morning_peak`, `midday`, `afternoon`.
- These four sub-buckets cover the **00:00–16:00 IST** window. Recorded violations
  fall off a cliff after ~16:00, so there is deliberately no evening bucket.
- An **unknown bucket falls back** to the zone's `all_day` rollup.
- `hour` (0–23) is accepted on most endpoints for wire compatibility but is
  **informational** — it does not change CIS results.

### 3.6 Calibration (the self-validating agent)

For the zones that have real MapMyIndia travel-time data, an offline agent
compares the CIS against the measured travel-time ratio and produces a
`calibrated_score` / `calibrated_impact` plus human-readable `reasoning`. It can
adjust a score **up** (corridor is worse than violations implied) or **down**
(wide road absorbs the load). See [`/agent/validation-report`](#69-self-validating-agent).

---

## 4. Conventions

| Topic | Detail |
| :-- | :-- |
| **Auth** | **None.** The API is unauthenticated and read-mostly. It exposes only aggregate, non-personal analytics. ⚠️ If you deploy it on a public URL, put it behind a gateway/API key or network controls before adding any sensitive data. |
| **CORS** | Wide open (`allow_origins=["*"]`, all methods/headers) for demo convenience. Tighten for production. |
| **Content type** | All responses are `application/json`. `POST` bodies must be `application/json`. |
| **Rate limits** | None imposed by the app. |
| **Pagination** | Via `limit` / `n` query params; there is no cursor pagination (datasets are small). |
| **Determinism** | Responses are deterministic for a given artifact set; lists use stable tie-breaks (descending metric, then `h3_id`). |
| **Path mounting** | Every endpoint exists at both `/<path>` and `/api/<path>`. |

### Error model

**`422 Unprocessable Entity`** — query/body validation (FastAPI/Pydantic). Shape:

```json
{
  "detail": [
    { "type": "less_than_equal", "loc": ["query", "hour"],
      "msg": "Input should be less than or equal to 23", "input": "99", "ctx": {"le": 23} }
  ]
}
```

**`404 Not Found`** — unknown zone on `/risk/{zone_id}`. Structured detail:

```json
{ "detail": { "error": "No data for zone <id>", "zone_id": "<id>" } }
```

**Graceful empty** — if a pre-computed artifact is missing at startup, the
affected endpoint returns an empty list / zeroed payload (or a clearly-flagged
proxy) rather than erroring, preserving offline-safety.

---

## 5. Data schemas

### 5.1 Zone object (operational shape)

Returned by `/risk`, `/risk/top_zones`, `/risk/overview.top_zone`, `/game/stackelberg_strategy`, `/game/violator_adaptation`, and (with extra fields) `/stations/{station}/priority_areas`.

| Field | Type | Description |
| :-- | :-- | :-- |
| `grid_cell_id`, `h3_id` | string | H3 res-9 zone id (same value). |
| `grid_lat`, `grid_lon` | float | Zone centroid. |
| `hour` | int | Context hour (default 9). |
| `risk_score` | float 0–100 | Enforcement priority (volume rank). |
| `risk_label` | string | `LOW`/`MEDIUM`/`HIGH`/`CRITICAL` from `risk_score`. |
| `congestion_impact` | float 0–100 | CIS (distinct from `risk_score`). |
| `impact_band` | string | CIS band. |
| `calibrated_score` | float 0–100 | Agent-calibrated CIS (falls back to CIS when no calibration). |
| `violation_count` | int | Recorded violations in the zone. |
| `density` | float 0–1 | Volume relative to the busiest hotspot. **Real.** |
| `road_importance` | float 0–1 | How arterial the road is (from road name + real travel-time ratio). **Real.** |
| `heavy_vehicle_ratio` | float 0–1 | Heavy-vehicle obstruction = the real CIS `vehicle_size` component. **Real.** |
| `peak_weight` | float | Illustrative constant (1.0) — the `all_day` rollup has no hourly peak. |
| `repeat_offender` | float 0–1 | **Illustrative** proxy derived from volume (the dataset has no plate-level recurrence). |
| `validation_trust` | float 0–1 | **Illustrative** constant (0.70). |
| `travel_time_ratio`, `mappls_ratio` | float \| null | Real MapMyIndia peak/free-flow travel-time ratio (null when not enriched). |
| `road_name`, `road_type` | string | Real road name / class (from MapMyIndia where available). |
| `nearby_pois` | string[] | Real nearby points of interest (where enriched). |
| `station`, `police_station` | string | Owning police station. |
| `top_junction` | string \| null | Locality / junction label. |
| `top_violation` | string | Most frequent violation type. |
| `estimated_lane_hours_blocked` | float | Modelled daily lane-hours blocked (estimate). |
| `agent_status` | string \| null | `validated_accurate` / `adjusted_up` / `adjusted_down` (when calibrated). |
| `agent_reasoning` | string \| null | Human-readable calibration rationale. |
| `patrol_probability` | float | Stackelberg mixed-strategy probability (∝ `risk_score`^1.5, normalised). |
| `baseline_weight`, `adjusted_weight` | float | Pre/post game-theory weights. |
| `expected_cost`, `net_benefit`, `violator_risk_score` | float | Violator expected-utility outputs. |

> Fields marked **Illustrative** are transparent placeholders the raw dataset
> cannot supply; they are documented as such and never presented as measured.

### 5.2 `CongestionBreakdown` (returned by `/risk/{zone_id}` for a CIS zone)

| Field | Type | Description |
| :-- | :-- | :-- |
| `zone_id`, `h3_id` | string | Zone id. |
| `time_bucket` | string | The bucket served (after fallback). |
| `lat`, `lon` | float \| null | Centroid. |
| `congestion_impact` | float 0–100 | CIS. |
| `impact_band` | string | CIS band. |
| `components` | object | The five normalised (0–1) components — `lane_blockage`, `intersection_impact`, `traffic_degradation`, `access_blockage`, `vehicle_size` — plus `severity` (reported diagnostic, **not** weighted). |
| `weights` | object | The component weights (sum = 1.0): `lane_blockage` 0.30, `intersection_impact` 0.25, `traffic_degradation` 0.25, `access_blockage` 0.10, `vehicle_size` 0.10. |
| `estimated_lane_hours_blocked` | float | Daily lane-hours blocked (estimate). |
| `total_records` | int | Violations contributing to the score. |
| `top_violations` | string[] | Most frequent violation types. |
| `station` | string \| null | Police station. |
| `junction` | string \| null | Junction name. |
| `mappls_travel_time_ratio` | float \| null | Real measured ratio (null if absent). |
| `is_traffic_degradation_defaulted` | bool | `true` when no Mappls data, so the traffic component defaulted to 0.5. |
| `calibrated_impact` | float \| null | Agent-calibrated CIS (null when no calibration). |

### 5.3 `CongestionHeatmapResponse`

```jsonc
{
  "layer": "risk",            // risk | raw | violator | spillover
  "time_bucket": "all_day",
  "points": [
    { "lat": 12.93, "lon": 77.69, "h3_id": "89618920923ffff",
      "intensity": 49.537, "impact_band": "MODERATE" }
  ],
  "min_intensity": 0.0,
  "max_intensity": 49.537
}
```

`intensity` carries a **different quantity per layer** (see [§6.2](#62-congestion-impact--quantify)).

### 5.4 `SimulationResponse` / `SimulationRequest`

See [`POST /simulate`](#post-simulate).

---

## 6. Endpoint reference

> Conventions: query params are listed with their defaults and constraints.
> All examples use the bare path; prefix `/api` for the mirrored route.

---

### 6.1 Health & service

#### `GET /`

Service metadata and a curated endpoint index.

```bash
curl -s http://localhost:8000/
```

```json
{
  "service": "ParkVision-Saathi API",
  "version": "2.0.0",
  "data_layer": "JSON + in-memory (no database)",
  "endpoints": ["/hotspots", "/risk/top_zones", "/risk/{zone_id}", "/heatmap",
                "/stations", "/forecast/top_risk_zones", "/game/stackelberg_strategy",
                "/game/violator_adaptation", "/game/spillover_arrows", "/simulate",
                "/explain", "/traffic/{zone_id}", "/agent/validation-report"]
}
```

#### `GET /health`

Liveness + a snapshot of the in-memory data layer and the agent summary. Use this
as your readiness/health-check path.

```bash
curl -s http://localhost:8000/health
```

```json
{
  "status": "ok",
  "data_layer": "json-in-memory",
  "zones_loaded": 60,
  "sources": {
    "congestion_artifact_zones": 2527,
    "hotspot_universe": 60,
    "traffic_context_enriched": 10,
    "calibrated_scores": 10,
    "explanations_cache": 60,
    "forecast_zones": 2527
  },
  "agent": { "total_zones": 2527, "calibrated": 10, "accurate": 6,
             "adjusted_up": 3, "adjusted_down": 1, "mean_abs_adjustment_pct": 4.2 }
}
```

| Field | Meaning |
| :-- | :-- |
| `zones_loaded` | Size of the hotspot/OPTIMIZE universe (60). |
| `sources.congestion_artifact_zones` | Full CIS artifact size (2,527). |
| `sources.traffic_context_enriched` | Zones with real MapMyIndia data. |
| `agent` | Self-validating agent run summary. |

---

### 6.2 Congestion Impact — QUANTIFY

#### `GET /hotspots`

Top congestion hotspots ranked by **descending CIS** (the QUANTIFY pillar's
headline list). Served from the 2,527-zone artifact.

| Param | In | Type | Default | Notes |
| :-- | :-- | :-- | :-- | :-- |
| `time_bucket` | query | string | `all_day` | `all_day`/`night`/`morning_peak`/`midday`/`afternoon`. |
| `limit` | query | int | `15` | 1–100. |
| `hour` | query | int | — | 0–23, informational. |

```bash
curl -s "http://localhost:8000/hotspots?time_bucket=all_day&limit=2"
```

```json
[
  {
    "rank": 1,
    "zone_id": "89618920923ffff",
    "h3_id": "89618920923ffff",
    "lat": 12.9332, "lon": 77.6908,
    "congestion_impact": 49.54,
    "impact_band": "MODERATE",
    "violation_count": 6747,
    "station": "HAL Old Airport",
    "top_violation": "NO PARKING",
    "estimated_lane_hours_blocked": 2298.25
  }
]
```

Returns `[]` if the CIS artifact is absent. Response items follow the
`HotspotItem` schema.

#### `GET /risk/{zone_id}`

Full per-zone detail. **For a real CIS zone**, returns a `CongestionBreakdown`
(see [§5.2](#52-congestionbreakdown-returned-by-riskzone_id-for-a-cis-zone)),
including the five scored components, the weights echo, the real travel-time
ratio, and `calibrated_impact`. **For a hotspot-universe-only zone** not in the
CIS artifact, it falls back to the operational zone object. An **unknown zone →
404**.

| Param | In | Type | Default | Notes |
| :-- | :-- | :-- | :-- | :-- |
| `zone_id` | path | string | — | H3 res-9 id. |
| `time_bucket` | query | string | `all_day` | Falls back to `all_day`. |
| `hour` | query | int | — | Informational. |

```bash
curl -s "http://localhost:8000/risk/8960145b553ffff?time_bucket=all_day"
```

```json
{
  "zone_id": "8960145b553ffff", "h3_id": "8960145b553ffff", "time_bucket": "all_day",
  "lat": 12.9764, "lon": 77.5759,
  "congestion_impact": 14.85, "impact_band": "MINIMAL",
  "components": { "lane_blockage": 0.077, "intersection_impact": 0.043,
                  "traffic_degradation": 0.297, "access_blockage": 0.042,
                  "vehicle_size": 0.362, "severity": 0.362 },
  "weights": { "lane_blockage": 0.30, "intersection_impact": 0.25,
               "traffic_degradation": 0.25, "access_blockage": 0.10, "vehicle_size": 0.10 },
  "estimated_lane_hours_blocked": 3072.0, "total_records": 12109,
  "top_violations": ["NO PARKING", "WRONG PARKING", "DEFECTIVE NUMBER PLATE"],
  "station": "Upparpet", "junction": null,
  "mappls_travel_time_ratio": 1.594, "is_traffic_degradation_defaulted": false,
  "calibrated_impact": 15.9
}
```

```bash
# Unknown zone → 404
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/risk/nope0000   # 404
```

#### `GET /heatmap`

Point layers for the map. The same endpoint serves four **distinct** layers via
the `type` param — the intensity quantity changes per layer, which is what powers
the "two-layer toggle".

| Param | In | Type | Default | Notes |
| :-- | :-- | :-- | :-- | :-- |
| `type` | query | string | `risk` | `risk` \| `raw` \| `violator` \| `spillover`. Unknown → `risk`. |
| `time_bucket` | query | string | `all_day` | For `risk`/`raw`. |
| `hour` | query | int | — | Informational. |

| `type` | `intensity` is… | Source / size |
| :-- | :-- | :-- |
| `risk` | **Congestion Impact Score** (where traffic is choked) | CIS artifact, 2,527 pts |
| `raw` | **Violation count** (where violations happen) | CIS artifact, 2,527 pts |
| `violator` | **Violator net-benefit** (where rational violators still profit) | hotspot universe, 60 pts |
| `spillover` | **Agent-calibrated impact** | hotspot universe, 60 pts |

```bash
curl -s "http://localhost:8000/heatmap?type=risk"
curl -s "http://localhost:8000/heatmap?type=raw"
```

```json
{
  "layer": "risk", "time_bucket": "all_day",
  "points": [ { "lat": 12.9332, "lon": 77.6908, "h3_id": "89618920923ffff",
                "intensity": 49.537, "impact_band": "MODERATE" } ],
  "min_intensity": 0.0, "max_intensity": 49.537
}
```

> The `risk` and `raw` layers are intentionally **not** the same map — the top of
> `raw` is the busiest zone (Upparpet, 12,109 violations) while the top of `risk`
> is the highest-impact zone (HAL Old Airport, CIS 49.5). That difference is the
> demo's headline.

#### `GET /heatmap/patrol_overlay`

Patrol-probability points for sizing map markers (Stackelberg probabilities over
the hotspot universe).

| Param | In | Type | Default |
| :-- | :-- | :-- | :-- |
| `hour` | query | int | — |
| `time_bucket` | query | string | — |

```json
{ "hour": null, "time_bucket": null,
  "patrols": [ { "lat": 12.9764, "lon": 77.5759, "probability": 0.0408, "risk_score": 100.0 } ] }
```

---

### 6.3 Enforcement risk views

These serve the operational **`risk_score`** (enforcement priority) over the
hotspot universe — a separate concern from the CIS.

#### `GET /risk`

List of zone objects ([§5.1](#51-zone-object-operational-shape)), optionally filtered.

| Param | In | Type | Default | Notes |
| :-- | :-- | :-- | :-- | :-- |
| `hour` | query | int | — | 0–23. |
| `time_bucket` | query | string | — | Accepted; informational here. |
| `zone_id` | query | string | — | Return just that zone. |
| `risk_label` | query | string | — | `LOW`/`MEDIUM`/`HIGH`/`CRITICAL`. |
| `limit` | query | int | `100` | 1–1000. |

```bash
curl -s "http://localhost:8000/risk?risk_label=CRITICAL&limit=5"
```

#### `GET /risk/summary`

Distribution of zones grouped by `risk_label`.

```json
[ { "risk_label": "CRITICAL", "zone_count": 13, "total_violations": 72121,
    "avg_score": 90.0, "min_score": 80.0, "max_score": 100.0 } ]
```

#### `GET /risk/top_zones`

Top-N zones by `risk_score` (full zone objects). Powers map markers.

| Param | In | Type | Default | Notes |
| :-- | :-- | :-- | :-- | :-- |
| `n` | query | int | `10` | 1–50. |
| `hour`, `time_bucket` | query | — | — | Informational. |

```bash
curl -s "http://localhost:8000/risk/top_zones?n=15"
```

#### `GET /risk/overview`

Dashboard rollup: the `risk_label` distribution, the single top zone, and the
total zone count.

```json
{
  "hour": null, "time_bucket": null,
  "risk_distribution": [
    { "risk_label": "CRITICAL", "count": 13, "total_violations": 72121, "avg_score": 90.0 },
    { "risk_label": "HIGH", "count": 7, "total_violations": 18057, "avg_score": 73.3 },
    { "risk_label": "MEDIUM", "count": 20, "total_violations": 32985, "avg_score": 50.8 },
    { "risk_label": "LOW", "count": 20, "total_violations": 22183, "avg_score": 17.5 }
  ],
  "top_zone": { "...": "full zone object" },
  "total_zones": 60
}
```

---

### 6.4 Forecasting — PREDICT

A LightGBM-Poisson daily model trained on the **same H3 res-9 zones as the map**
(`ml/forecast/build_h3_forecast.py` → `data/processed/forecasts.json`), so
predicted hotspots line up with the Congestion Impact layer. If that artifact is
absent, endpoints fall back to a transparent historical-volume **proxy**
(flagged `is_proxy: true`).

#### `GET /forecast/top_risk_zones`

Zones predicted to have the most violations **tomorrow**, ranked.

| Param | In | Type | Default | Notes |
| :-- | :-- | :-- | :-- | :-- |
| `n` | query | int | `10` | 1–50. |
| `hour`, `time_bucket` | query | — | — | Informational. |

```json
[
  { "zone_id": "8960145b5cbffff", "h3_id": "8960145b5cbffff",
    "lat": 12.9743, "lon": 77.5783,
    "predicted_count": 31.4, "predicted_risk": 100.0, "predicted_band": "CRITICAL",
    "confidence_lower": 20.41, "confidence_upper": 42.38, "is_proxy": false }
]
```

| Field | Meaning |
| :-- | :-- |
| `predicted_count` | Expected next-day violations (Poisson mean). |
| `predicted_risk` | 0–100 percentile rank of the prediction. |
| `predicted_band` | Band from `predicted_risk`. |
| `confidence_lower/upper` | Poisson confidence interval. |
| `is_proxy` | `true` if served by the historical-volume fallback. |

#### `GET /forecast/zones`

Per-zone next-day forecast. With `zone_id`, returns just that zone.

| Param | In | Type | Default | Notes |
| :-- | :-- | :-- | :-- | :-- |
| `zone_id` | query | string | — | Return one zone. |
| `limit` | query | int | `100` | 1–5000. |

#### `GET /forecast/accuracy`

**Real held-out** accuracy of the forecast model (no params). Headline metric is
**Precision@10** — the share of tomorrow's actual top-10 hotspots the model ranks
in its own top-10.

```json
{
  "model": "LightGBM Poisson (H3 res-9, daily)", "is_proxy": false,
  "spatial_unit": "H3 resolution 9 (same as the Congestion Impact map)",
  "target": "violation_count per H3 zone per day",
  "precision_at_10": 0.45, "mae": 0.8323, "rmse": 4.4257, "n_test_days": 8,
  "generated_for": "2024-04-09",
  "split": { "val_start": "2024-03-01", "test_start": "2024-04-01" },
  "evaluation": "Held-out April test set; chronological split; strictly-past (leakage-free) features.",
  "summary": "Correctly identifies ~4 of tomorrow's top-10 H3 hotspots (Precision@10 = 0.45 ...)."
}
```

If the H3 artifact is missing, this falls back to the grid-keyed
LightGBM+CatBoost ensemble metrics (`models/ensemble_config.json`), then to a
proxy note.

---

### 6.5 Game theory & simulation — OPTIMIZE

Models the police-vs-violator interaction as a Stackelberg security game (police
lead, violators best-respond) and simulates patrol deployment with a waterbed
(spillover) effect. All over the hotspot universe.

#### `GET /game/stackelberg_strategy`

Zones with their Stackelberg mixed-strategy patrol probabilities
(`patrol_probability` ∝ `risk_score`^1.5, normalised). Returns full zone objects.

| Param | In | Type | Default |
| :-- | :-- | :-- | :-- |
| `hour`, `time_bucket`, `zone_id` | query | — | — |
| `limit` | query | int | `100` (1–1000) |

#### `GET /game/violator_adaptation`

Zones ranked by **violator** expected utility — where rational violators still
profit most despite enforcement. Key fields: `expected_cost`, `net_benefit`,
`violator_risk_score` (full zone object).

#### `GET /game/spillover_forecast`

The waterbed effect for a default 5-team enforcement: where displaced violations
land.

| Param | In | Type | Default |
| :-- | :-- | :-- | :-- |
| `spillover_type` | query | string | — |
| `limit` | query | int | `200` (1–2000) |

```json
[ { "grid_cell_id": "8960145b543ffff", "grid_lat": 12.9786, "grid_lon": 77.5735,
    "original_risk": 81.7, "adjusted_risk": 82.1, "risk_change_pct": 0.5,
    "spillover_type": "neighbor_1" } ]
```

#### `GET /game/summary`

Aggregate stats across the three game-theory layers.

```json
{
  "hour": null, "time_bucket": null,
  "stackelberg": { "zones": 60, "max_patrol_prob": 0.0408, "avg_patrol_prob": 0.0167 },
  "violator_adaptation": { "avg_violator_risk": 41.3, "max_violator_risk": 75.51, "avg_expected_cost": 8.33 },
  "spillover_zones": 5
}
```

#### `GET /game/spillover_arrows`

Pre-computed displacement arrows (top patrolled zone → nearest neighbour) for the
waterbed visualization.

```json
{ "arrows": [ { "from_zone": "8960145b553ffff", "to_zone": "8960145b543ffff",
               "from_lat": 12.9764, "from_lon": 77.5759,
               "to_lat": 12.9786, "to_lon": 77.5735, "weight": 0.0408 } ] }
```

#### `GET /game/whatif_coverage`

Coverage % and uncovered-high count for each team count 1..10 — drives the
simulation slider's read-out.

```json
{
  "1": { "num_teams": 1, "coverage_pct": 3.28, "uncovered_high_risk": 19 },
  "5": { "num_teams": 5, "coverage_pct": 15.85, "uncovered_high_risk": 15 },
  "10": { "num_teams": 10, "coverage_pct": 30.33, "uncovered_high_risk": 10 }
}
```

#### `POST /simulate`

Allocate `num_teams` patrol teams to the highest-priority zones; report coverage
and the waterbed spillover the deployment causes.

**Request body** (`SimulationRequest`):

| Field | Type | Default | Constraints |
| :-- | :-- | :-- | :-- |
| `num_teams` | int | `3` | 1–20 |
| `hour` | int | `9` | 0–23 |
| `strategy` | string | `"stackelberg"` | `stackelberg` / `blotto` (label only) |

```bash
curl -s -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"num_teams":5,"hour":9,"strategy":"stackelberg"}'
```

**Response** (`SimulationResponse`):

```json
{
  "num_teams": 5, "hour": 9, "strategy": "stackelberg",
  "assignments": [
    { "team_id": 1, "grid_cell_id": "8960145b553ffff", "grid_lat": 12.9764, "grid_lon": 77.5759,
      "risk_score": 100.0, "patrol_probability": 0.0408, "priority_rank": 1 }
  ],
  "uncovered_high_risk": [
    { "grid_cell_id": "8960145b5cbffff", "grid_lat": 12.9743, "grid_lon": 77.5783, "risk_score": 91.7 }
  ],
  "coverage_pct": 15.85,
  "total_risk_covered": 483.3,
  "spillover_zones": [
    { "grid_cell_id": "8960145b543ffff", "grid_lat": 12.9786, "grid_lon": 77.5735,
      "original_risk": 81.7, "adjusted_risk": 82.1, "risk_change_pct": 0.5, "spillover_type": "neighbor_1" }
  ]
}
```

| Field | Meaning |
| :-- | :-- |
| `assignments` | Team → zone allocation (highest priority first). |
| `uncovered_high_risk` | High-risk zones left uncovered (the "you can't cover everything" beat). |
| `coverage_pct` | Risk-weighted % of total hotspot risk covered. |
| `total_risk_covered` | Sum of `risk_score` covered. |
| `spillover_zones` | Where displaced violator pressure migrates (waterbed). |

---

### 6.6 Stations

#### `GET /stations`

All police stations present in the hotspot universe, with rollup stats and a
centroid (for the station-picker screen).

```json
[ { "name": "Upparpet", "zone_count": 6, "total_violations": 31666,
    "lat": 12.9764, "lon": 77.5773 } ]
```

#### `GET /stations/{station}/priority_areas`

Zones under a station ranked by priority, each annotated with the force needed and
an ETA from the station centroid. Returns zone objects + `force_needed`,
`priority`, `distance_km`, `eta_minutes`.

| Param | In | Type | Default | Notes |
| :-- | :-- | :-- | :-- | :-- |
| `station` | path | string | — | URL-encode names with spaces. |
| `hour` | query | int | `9` | 0–23. |
| `limit` | query | int | `10` | 1–50. |

```bash
curl -s "http://localhost:8000/stations/Upparpet/priority_areas?limit=5"
```

#### `GET /stations/{station}/summary`

Risk-label breakdown for one station.

```json
{
  "station": "Upparpet", "hour": 9, "total_zones": 6, "total_violations": 31666,
  "high_risk_zones": 4,
  "breakdown": [
    { "risk_label": "CRITICAL", "count": 4, "violations": 28364 },
    { "risk_label": "MEDIUM", "count": 1, "violations": 2212 },
    { "risk_label": "LOW", "count": 1, "violations": 1090 }
  ]
}
```

---

### 6.7 Explanations

#### `POST /explain`

Natural-language explanation of a zone's congestion situation for a control-room
officer. **Tiered and offline-safe:**

1. **cache** — pre-generated text (`data/processed/explanations_cache.json`), served as `source: "cache"`.
2. **live Gemini** — only when `GEMINI_API_KEY` is set; lazy-imported, any failure falls through. `source: "gemini"`.
3. **grounded fallback** — built only from the zone's real fields (no hallucination, no network). `source: "fallback"`.

Resolves **both** zone universes; an unknown id returns a graceful "no data"
message (HTTP 200, `source: "fallback"`).

**Request body** (`ExplainRequest`):

| Field | Type | Notes |
| :-- | :-- | :-- |
| `zone_id` | string | H3 id. |
| `hour` | int | Context hour. |

```bash
curl -s -X POST http://localhost:8000/explain \
  -H "Content-Type: application/json" \
  -d '{"zone_id":"8960145b553ffff","hour":9}'
```

```json
{
  "zone_id": "8960145b553ffff",
  "explanation": "Zone 8960145b553ffff on Subedar Chatram Road, Gandhi Nagar (Upparpet PS) scores 15/100 on the Congestion Impact Index — MINIMAL band — at 09:00 IST. It recorded 12,109 violations (top type: NO PARKING) ... MapMyIndia measures a 1.59x travel-time ratio here; the self-validating agent calibrates the score to 16/100 ...",
  "is_cached": true,
  "source": "cache"
}
```

| Field | Meaning |
| :-- | :-- |
| `is_cached` | `true` when served from the cache tier. |
| `source` | `cache` / `gemini` / `fallback`. |

---

### 6.8 Traffic context

#### `GET /traffic/{zone_id}`

Real MapMyIndia enrichment for a zone: travel-time ratio, road name/type, and
nearby POIs. Enriched zones return live values; un-enriched zones return the
zone's road label with `null` ratios.

```bash
curl -s "http://localhost:8000/traffic/8960145b553ffff"
```

```json
{
  "zone_id": "8960145b553ffff",
  "road_name": "Subedar Chatram Road, Gandhi Nagar",
  "road_type": "primary",
  "travel_time_peak_min": 12.0,
  "travel_time_offpeak_min": 7.5,
  "travel_time_ratio": 1.594,
  "nearby_pois": ["Flix Bus Bengaluru Bus Stop (106m)", "Bus Stop (211m)",
                  "Private Bus Station (275m)", "International Airport Bus Stop (432m)"]
}
```

| Field | Meaning |
| :-- | :-- |
| `travel_time_peak_min` | Live/peak ETA across the zone (minutes). |
| `travel_time_offpeak_min` | Free-flow baseline (minutes). |
| `travel_time_ratio` | peak ÷ off-peak (>1 = congested). |

---

### 6.9 Self-validating agent

#### `GET /agent/validation-report`

The agent's calibration of the CIS against real MapMyIndia travel times: a run
summary plus a per-zone reasoning log. Deterministic and offline.

```bash
curl -s "http://localhost:8000/agent/validation-report"
```

```json
{
  "summary": { "total_zones": 2527, "calibrated": 10, "accurate": 6,
               "adjusted_up": 3, "adjusted_down": 1, "mean_abs_adjustment_pct": 4.2 },
  "zones": [
    {
      "zone_id": "89618920923ffff", "station": "HAL Old Airport",
      "raw_score": 49.5, "calibrated_score": 44.1, "impact_band": "MODERATE",
      "validated": true, "mappls_ratio": 1.259, "expected_ratio": 1.991,
      "discrepancy": -0.732, "adjustment": -0.1103, "status": "adjusted_down",
      "reasoning": "Adjusted DOWN 50→44: Mappls shows only 1.26x travel time vs the 1.99x our CIS implied; the corridor absorbs the parking load better than violations alone suggest."
    }
  ]
}
```

| Field (per zone) | Meaning |
| :-- | :-- |
| `raw_score` → `calibrated_score` | CIS before/after calibration. |
| `mappls_ratio` | Real measured travel-time ratio. |
| `expected_ratio` | Ratio the CIS implied. |
| `discrepancy`, `adjustment` | Gap and the applied correction. |
| `status` | `validated_accurate` / `adjusted_up` / `adjusted_down`. |
| `reasoning` | Human-readable rationale. |

---

## 7. Field glossary

| Field | Range | Definition |
| :-- | :-- | :-- |
| `congestion_impact` (CIS) | 0–100 | How much a zone degrades traffic flow (weighted component blend). |
| `risk_score` | 0–100 | Enforcement priority = relative violation-volume rank in the hotspot universe. |
| `calibrated_score` / `calibrated_impact` | 0–100 | CIS after agent calibration vs real travel time. |
| `impact_band` | enum | `MINIMAL`/`MODERATE`/`SEVERE`/`CRITICAL` from CIS. |
| `risk_label` | enum | `LOW`/`MEDIUM`/`HIGH`/`CRITICAL` from `risk_score`. |
| `patrol_probability` | 0–1 | Stackelberg mixed strategy (∝ `risk_score`^1.5). |
| `violator_risk_score` | 0–100 | Where rational violators still profit (net benefit). |
| `estimated_lane_hours_blocked` | ≥0 | Modelled daily lane-hours blocked (estimate). |
| `travel_time_ratio` | ≥0 | Peak ÷ off-peak travel time (>1 congested). |
| `density` | 0–1 | Volume relative to the busiest hotspot. |
| `is_proxy` | bool | Forecast served by the historical-volume fallback. |
| `is_traffic_degradation_defaulted` | bool | CIS traffic component defaulted (no Mappls data). |

---

## 8. HTTP status codes

| Code | When |
| :-- | :-- |
| `200 OK` | Success (including graceful empty lists and the explain "no data" fallback). |
| `404 Not Found` | Unknown `zone_id` on `/risk/{zone_id}`. |
| `422 Unprocessable Entity` | Query/body validation failure (e.g. `hour=99`, `num_teams=0`). |
| `500 Internal Server Error` | A materialized artifact entry is malformed (shape validation). Rare. |

---

## 9. Versioning & changelog

- **API version:** `2.0.0` (reported by `/` and `/health`).
- **Data layer:** JSON + in-memory; **no database, no request-time network**.
- **Artifacts** are committed under `data/` and rebuilt offline via
  `run_pipeline.py` (see `docs/ML_PIPELINE.md`).

### Notes for integrators

- Prefer `/health` for readiness checks (cheap, no heavy work).
- `zone_id`, `h3_id`, and `grid_cell_id` are the same value — pick one and be
  consistent.
- Treat `congestion_impact` and `risk_score` as **different metrics**; never
  assume one equals the other.
- For the two-layer map toggle, request `/heatmap?type=risk` and
  `/heatmap?type=raw` and render both.
- Every endpoint is also available under `/api/...`.
```
