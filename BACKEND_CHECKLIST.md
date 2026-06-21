# ParkVision-Saathi: Backend Checklist & Implementation Status

This document tracks the backend infrastructure against `EXECUTION_PLANNER.md`.

> **Architecture:** the backend is **JSON + in-memory, no database**. At startup
> `backend/app/data_loader.py` loads the pre-computed JSON artifacts in `data/`
> into a single in-memory `DataStore`; every router reads from that store. There
> is **no SQLite/PostgreSQL/Redis/Docker** and nothing makes a network call at
> request time, so the API runs fully offline. See `API_DOCS.md` for the endpoint
> reference and `run_pipeline.py` for how the artifacts are regenerated.

## Data artifacts the backend serves

| Artifact | Purpose |
| :-- | :-- |
| `data/processed/zone_congestion_impact.json` | Canonical Congestion Impact Score (CIS) — 2,527 real H3 res-9 Bengaluru zones (QUANTIFY pillar; powers heatmap, hotspots, zone detail) |
| `data/enriched/traffic_context_h3.json` | Real MapMyIndia travel-time ratio, road names, POIs — keyed by true H3 id |
| `data/processed/calibrated_scores.json` | Self-validating agent's calibrated scores |
| `data/processed/agent_log.json` | Agent run summary + per-zone reasoning |
| `data/processed/forecasts.json` | H3-native LightGBM-Poisson next-day forecast (PREDICT pillar) |
| `data/processed/explanations_cache.json` | Pre-generated LLM zone explanations (cache tier of `/explain`) |

The served **hotspot / OPTIMIZE zone universe** (markers, game theory, simulation,
stations, `/traffic`) is built in `data_loader._build_zone_universe()` as the
**top-60 real CIS zones by violation volume** — every id is a true H3 id that
matches the CIS map, the traffic enrichment, the calibration, and the forecast.

## Summary status

| Requirement / Task | Target File(s) | Status | Details |
| :--- | :--- | :---: | :--- |
| FastAPI skeleton with CORS | `backend/app/main.py` | ✅ DONE | App entry, CORS wildcard, static dashboard mount at `/dashboard`; routes mounted at bare path and under `/api`. |
| In-memory DataStore (no DB) | `backend/app/data_loader.py` | ✅ DONE | Loads all JSON once; builds the real-zone universe + game-theory fields. |
| Heatmap router | `backend/app/routers/heatmap.py` | ✅ DONE | `/heatmap` (risk / raw / violator / spillover layers) + `/heatmap/patrol_overlay`. |
| Risk & hotspots router | `backend/app/routers/risk.py` | ✅ DONE | `/hotspots` (CIS-ranked), `/risk`, `/risk/summary`, `/risk/top_zones`, `/risk/overview`, `/risk/{zone_id}` (CIS breakdown). |
| Forecast router | `backend/app/routers/forecast.py` | ✅ DONE | `/forecast/zones`, `/forecast/top_risk_zones`, `/forecast/accuracy` (real held-out metrics), served from `forecasts.json`. |
| Game theory router | `backend/app/routers/game.py` | ✅ DONE | `/game/stackelberg_strategy`, `/violator_adaptation`, `/spillover_forecast`, `/summary`, `/spillover_arrows`, `/whatif_coverage`. |
| Simulation router | `backend/app/routers/simulate.py` | ✅ DONE | `POST /simulate` — greedy allocation, coverage %, waterbed spillover. |
| Explanations router | `backend/app/routers/explain.py` | ✅ DONE | `POST /explain` — cache → optional Gemini → grounded offline fallback. |
| Traffic context router | `backend/app/routers/traffic.py` | ✅ DONE | `GET /traffic/{zone_id}` — real MapMyIndia ratio, road, POIs. |
| Stations router | `backend/app/routers/stations.py` | ✅ DONE | `/stations`, `/stations/{station}/priority_areas`, `/stations/{station}/summary`. |
| Agent router | `backend/app/routers/agent.py` | ✅ DONE | `GET /agent/validation-report`. |
| Pydantic models | `backend/app/models.py` | ✅ DONE | CIS contract + legacy response models. |
| Requirements | `requirements.txt` / `requirements-backend.txt` | ✅ DONE | Full (ML + tests) and lean runtime (deploy) sets. |
| Deploy config | `render.yaml`, `Procfile` | ✅ DONE | Render blueprint + Procfile, `$PORT`, `/health` check. |

---

## Verification

```bash
# Full test suite (backend + ML): 126 passed
PYTHONPATH=. python -m pytest -q

# Run the API (from the project root)
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

All endpoints return HTTP 200 and serve real, id-aligned Bengaluru data from the
in-memory JSON store.
