# ParkVision-Saathi — ML & Data Pipeline

This project has **two layers**, by design:

1. **The offline ML / data-generation pipeline** (the modelling work) — trains
   models and computes the analytics, writing the results to artifacts on disk.
2. **The serving layer** (FastAPI) — at request time it only reads those
   pre-computed artifacts from memory. It runs **no ML and no database at request
   time**, so it deploys fast and works fully offline.

This separation is intentional: the heavy lifting happens once, offline; the API
stays light and reliable for the demo.

---

## Layer 1 — Offline ML / data generation (where the modelling lives)

### A. Congestion + forecast + agent pipeline (current, JSON, no DB)

Run by **`run_pipeline.py`** at the project root. Database-free and deterministic.

| Step | Script | Produces |
| :-- | :-- | :-- |
| Re-key MapMyIndia enrichment to true H3 ids | `ml/enrichment/rekey_traffic_context.py` | `data/enriched/traffic_context_h3.json` |
| Congestion Impact Score (CIS) per H3 zone | `ml/congestion/build_artifact.py`, `ml/congestion/impact_score.py` | `data/processed/zone_congestion_impact.json` (2,527 zones) |
| Self-validating agent (calibrates CIS vs real travel time) | `ml/agent/validation_agent.py` | `data/processed/calibrated_scores.json`, `agent_log.json` |
| H3-native daily forecast (LightGBM-Poisson) | `ml/forecast/build_h3_forecast.py` | `data/processed/forecasts.json` |
| LLM zone explanations (cache pre-warm) | `ml/llm/generate_explanations.py` | `data/processed/explanations_cache.json` |

```bash
PYTHONPATH=. python run_pipeline.py            # rebuild the served artifacts
PYTHONPATH=. python run_pipeline.py --multi-res  # also res 5/7/8
```

### B. Modelling & analysis scripts (SQLite-based)

These are the original modelling scripts — the DBSCAN hotspots, the
LightGBM + CatBoost forecasting ensemble, the risk scoring, and the game-theory
models. They read a local SQLite working DB (`data/parkvision.db`) built from the
violation CSV. **They are the code behind the trained models in `models/`** and
the game-theory analysis, and are kept here as the project's modelling record.

| Script | Role | Output |
| :-- | :-- | :-- |
| `data/load_and_clean.py` | ETL: violation CSV → cleaned `data/parkvision.db` | SQLite working DB |
| `scripts/seed_db.py` | (Optional) generate a synthetic DB when the raw CSV isn't on the machine | SQLite working DB |
| `ml/risk_score.py` | Hourly enforcement risk scoring | `data/risk_scores_by_hour.json` |
| `ml/hotspot_dbscan.py` | DBSCAN spatial hotspot clustering | hotspot clusters |
| `ml/forecast/feature_engineering.py` | Lag/rolling feature matrix for forecasting | `data/forecast_features.csv` |
| `ml/forecast/train_model.py` | **Trains the LightGBM + CatBoost ensemble** | `models/lightgbm_v1.pkl`, `models/catboost_v1.cbm`, `models/ensemble_config.json`, `models/feature_importance.txt`, `models/MODEL_CARD.md` |
| `ml/game/stackelberg.py` | Stackelberg patrol-allocation game | `data/whatif_coverage.json` |
| `ml/game/expected_utility.py` | Violator expected-utility / adaptation model | `data/violator_utility.json` |
| `ml/game/spillover.py` | Waterbed / spillover displacement | `data/spillover_arrows.json` |

How to run them (they need the working DB first):

```bash
# 1. Build the working DB from the real violation CSV (placed under dataset/)
PYTHONPATH=. python data/load_and_clean.py
#    …or, without the CSV, a synthetic stand-in for testing:
#    PYTHONPATH=. python scripts/seed_db.py

# 2. Run the modelling scripts
PYTHONPATH=. python ml/risk_score.py
PYTHONPATH=. python ml/hotspot_dbscan.py
PYTHONPATH=. python ml/forecast/feature_engineering.py
PYTHONPATH=. python ml/forecast/train_model.py        # writes models/
PYTHONPATH=. python ml/game/stackelberg.py
PYTHONPATH=. python ml/game/expected_utility.py
PYTHONPATH=. python ml/game/spillover.py
```

> Note: `data/parkvision.db` and `data/*.csv` are git-ignored (large/generated),
> so a fresh checkout rebuilds them with the commands above. The trained
> artifacts in `models/` are committed, and `GET /forecast/accuracy` will surface
> the ensemble's held-out metrics from `models/ensemble_config.json` when the
> H3 forecast artifact is absent.

---

## Layer 2 — Serving (FastAPI, in-memory, no DB)

`backend/app/data_loader.py` loads the committed JSON artifacts into memory once
at startup; every router reads from that in-memory store. The served hotspot
universe is the **top-N real CIS zones** (so the map, game theory, simulation,
stations, and `/traffic` all use the same real Bengaluru H3 zones). See
`API_DOCS.md` for the endpoint reference.

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Why the API doesn't touch the SQLite DB

The modelling pipeline (Layer 1) is where SQLite/pandas/LightGBM are used. The API
(Layer 2) deliberately depends only on the small pre-computed JSON, so the deploy
build is fast (`requirements-backend.txt`), needs no database, and survives with
no network. Regenerating the artifacts is a Layer-1 task; serving them is Layer-2.
