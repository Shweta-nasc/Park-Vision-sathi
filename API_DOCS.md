# ParkVision-Saathi — API Documentation

> Person 1 (Backend) deliverable — Sprint 7 (`EXECUTION_PLANNER.md`).
> Base URL (local): `http://localhost:8000`
> Interactive docs (auto-generated): `http://localhost:8000/docs`

All endpoints read from the in-memory-loaded SQLite store (`data/parkvision.db`).
No external network calls are made at request time, so the API works fully offline.

## Running the server

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Static dashboard is served at `http://localhost:8000/dashboard/`.

---

## Time filters

Most endpoints accept either:

- `hour` — integer `0–23`, OR
- `time_bucket` — one of: `night_0_6`, `morning_6_10`, `midday_10_16`, `evening_16_22`, `night_22_24`

If both are omitted, the endpoint aggregates across all hours.

---

## Health & Service

### `GET /health`
Reports API status and presence of each required DB table.

```bash
curl -s http://localhost:8000/health
```

```json
{ "status": "ok", "tables": { "violations": true, "risk_scores": true, "game_stackelberg": true, "game_violator_adaptation": true, "game_spillover": true } }
```

### `GET /`
Service metadata and endpoint index.

```bash
curl -s http://localhost:8000/
```

---

## Risk & Hotspots

### `GET /hotspots`
DBSCAN hotspot clusters, optionally filtered by `hour`/`time_bucket`.
Query: `min_members` (default `5`).

```bash
curl -s "http://localhost:8000/hotspots?time_bucket=morning_6_10&min_members=5"
```

### `GET /risk`
Risk-scored grid cells. Query: `hour`, `time_bucket`, `zone_id`, `risk_label` (`LOW|MEDIUM|HIGH`), `limit` (default `100`).

```bash
curl -s "http://localhost:8000/risk?hour=9&limit=5"
```

### `GET /risk/summary`
Aggregated risk distribution. Query: `hour`, `time_bucket`, `type` (`risk|spillover`).

```bash
curl -s "http://localhost:8000/risk/summary?hour=9"
```

### `GET /risk/top_zones`
Top `n` highest-risk zones (default `n=10`).

```bash
curl -s "http://localhost:8000/risk/top_zones?hour=9&n=10"
```

### `GET /risk/overview`
Dashboard overview: risk distribution, top zone, total zones.

```bash
curl -s "http://localhost:8000/risk/overview?hour=9"
```

### `GET /risk/{zone_id}`
Detailed per-zone risk component breakdown joined with game-theory layers
(patrol probability, violator score, spillover).

```bash
curl -s "http://localhost:8000/risk/2596_15522?hour=9"
```

---

## Forecasting (LightGBM)

### `GET /forecast/zones`
Per-zone predicted violation counts. Query: `horizon_hours`, `hour`, `time_bucket`, `zone_id`, `limit`.

```bash
curl -s "http://localhost:8000/forecast/zones?hour=9&limit=5"
```

### `GET /forecast/top_risk_zones`
Zones predicted to have highest violations (default `n=10`).

```bash
curl -s "http://localhost:8000/forecast/top_risk_zones?hour=9&n=10"
```

### `GET /forecast/accuracy`
Live MAE / MSE / RMSE against held-out actuals.

```bash
curl -s "http://localhost:8000/forecast/accuracy"
```

```json
[ { "n_predictions": 2033, "mae": 0.17, "mse": 0.4431, "rmse": 0.6657 } ]
```

### `GET /forecast/stations`
Forecasts aggregated by police station. Query: `station` (required), `limit`.

```bash
curl -s "http://localhost:8000/forecast/stations?station=Upparpet"
```

---

## Game Theory

### `GET /game/stackelberg_strategy`
Stackelberg mixed-strategy patrol probabilities. Query: `hour`, `time_bucket`, `zone_id`, `limit`.

```bash
curl -s "http://localhost:8000/game/stackelberg_strategy?hour=9&limit=10"
```

### `GET /game/violator_adaptation`
Violator expected-utility and adaptation risk scores.

```bash
curl -s "http://localhost:8000/game/violator_adaptation?hour=9&limit=10"
```

### `GET /game/spillover_forecast`
Waterbed / spillover effect predictions. Query: `spillover_type`
(`patrolled|neighbor_1|neighbor_2|unaffected`), `limit`.

```bash
curl -s "http://localhost:8000/game/spillover_forecast?hour=9&limit=10"
```

### `GET /game/summary`
Combined summary of all three game-theory layers for an hour/bucket.

```bash
curl -s "http://localhost:8000/game/summary?hour=9"
```

### `GET /game/spillover_arrows`
Pre-computed displacement arrows for the waterbed visualization.

```bash
curl -s "http://localhost:8000/game/spillover_arrows"
```

### `GET /game/whatif_coverage`
Pre-computed what-if coverage for team counts `2,4,6,8,10,15,20`.

```bash
curl -s "http://localhost:8000/game/whatif_coverage"
```

---

## Simulation

### `POST /simulate`
Greedy patrol allocation over Stackelberg probabilities, returning team
assignments, coverage %, uncovered high-risk zones, and spillover zones.

Body (`SimulationRequest`):

```json
{ "num_teams": 5, "hour": 9, "strategy": "stackelberg" }
```

```bash
curl -s -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"num_teams":5,"hour":9,"strategy":"stackelberg"}'
```

---

## Heatmap

### `GET /heatmap`
Lat/lon/intensity points for the map layer. Query: `hour`, `time_bucket`,
`type` (`risk|violator|spillover|raw`).

```bash
curl -s "http://localhost:8000/heatmap?hour=9&type=risk"
curl -s "http://localhost:8000/heatmap?hour=9&type=raw"
```

### `GET /heatmap/patrol_overlay`
Patrol probability overlay for marker sizing.

```bash
curl -s "http://localhost:8000/heatmap/patrol_overlay?hour=9"
```

---

## Stations

### `GET /stations`
All 54 police stations with summary stats.

```bash
curl -s http://localhost:8000/stations
```

### `GET /stations/{station}/priority_areas`
Ranked priority zones under a station with force needed, distance, and ETA.
Query: `hour` (default `9`), `limit`.

```bash
curl -s "http://localhost:8000/stations/Upparpet/priority_areas?hour=9&limit=10"
```

### `GET /stations/{station}/summary`
Risk-label breakdown for a station at an hour.

```bash
curl -s "http://localhost:8000/stations/Upparpet/summary?hour=9"
```

---

## Explanations

### `POST /explain`
Data-driven natural-language explanation of a zone's congestion risk.

Body (`ExplainRequest`):

```json
{ "zone_id": "2596_15522", "hour": 9 }
```

```bash
curl -s -X POST http://localhost:8000/explain \
  -H "Content-Type: application/json" \
  -d '{"zone_id":"2596_15522","hour":9}'
```

---

## Traffic Context

### `GET /traffic/{zone_id}`
Travel-time delay ratio, road type, and nearby POIs for a zone.

```bash
curl -s "http://localhost:8000/traffic/2596_15522"
```

---

## Notes on schema alignment

The shipped implementation uses a grid-cell (`grid_cell_id`) + SQLite architecture
rather than the H3 + parquet contract sketched in `EXECUTION_PLANNER.md`. Field names
differ accordingly (e.g. `grid_cell_id` vs `h3_id`, `risk_score` vs `congestion_impact`),
but every planned endpoint is implemented and returns schema-stable JSON.
