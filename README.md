# ParkVision-Saathi 🚦

> **Quantify. Predict. Optimize.** — a data-driven parking-enforcement intelligence system for Bengaluru Traffic Police.

Illegal parking doesn't just annoy — it chokes traffic. ParkVision-Saathi quantifies *which* violations actually hurt traffic flow, predicts where tomorrow's hotspots will be, and optimizes where to send limited patrol teams. Built in 3 days for a hackathon.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-2.0-teal)
![Data](https://img.shields.io/badge/data-JSON%20%2B%20in--memory-orange)
![License](https://img.shields.io/badge/license-MIT-green)

---

## The Three Pillars

| Pillar | Problem | Our Answer |
|---|---|---|
| **QUANTIFY** | Which violations actually choke traffic? | 6-factor **Congestion Impact Score** (0–100) per zone |
| **PREDICT** | Where will tomorrow's hotspots be? | Forecast of top zones (see *Honest limitations* below) |
| **OPTIMIZE** | Where should patrol teams go? | **Stackelberg** game theory + **waterbed** spillover simulation |

---

## Key Features

- **Two-Layer Map Toggle** — *Violation Density* vs *Congestion Risk Impact*. They are not the same map, and that difference is the whole point.
- **Congestion Impact Score** — 6 weighted components, including a **real MapMyIndia travel-time ratio**.
- **Self-Validating Agent** 🤖 — after scoring, the agent checks every top zone against live MapMyIndia traffic data and **calibrates its own scores** with plain-English reasoning. Deterministic and offline-safe.
- **LLM Zone Explanations** — Gemini-generated, cache-first, grounded in real facts (no hallucinated numbers).
- **Team Allocation Simulator** — drag a team slider, watch coverage % and predicted spillover update live.
- **Real MapMyIndia Enrichment** — travel-time ratios, road names, and nearby POIs for the top hotspot zones.

---

## Architecture (planner-aligned: JSON + in-memory, **no database**)

```
Frontend
  ├── React + Vite + TypeScript  (frontend/src, port 5173)
  └── Vanilla dashboard          (served by the API at /dashboard)
        ↕ REST
Backend — FastAPI (port 8000)
  └── In-memory DataStore (backend/app/data_loader.py)
        loads pre-computed JSON once at startup — NO SQLite, NO Postgres
Data (single real H3 source of truth)
  ├── data/mock/hotspots.json              top hotspot zones (congestion impact)
  ├── data/enriched/traffic_context.json   REAL MapMyIndia travel-time + POIs
  ├── data/processed/calibrated_scores.json self-validating agent output
  ├── data/processed/agent_log.json         agent run summary + reasoning log
  └── data/processed/explanations_cache.json cached Gemini explanations
Maps: MapMyIndia / Mappls SDK (vector tiles, traffic layer, heatmap)
```

**Constraints followed (per the build plan):**
- ✅ No OpenStreetMap / OSMnx — MapMyIndia only
- ✅ No PostgreSQL / Redis / Docker — pre-computed JSON loaded into memory
- ✅ Demo survives offline — cached explanations + deterministic agent, no runtime LLM/network dependency

---

## Quick Start

```bash
# 1. Environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. (Re)generate the self-validating agent outputs (optional — already committed)
python -m ml.agent.validation_agent

# 3. Run the backend from the PROJECT ROOT (absolute imports require this)
uvicorn backend.app.main:app --reload --port 8000
#   API docs:  http://localhost:8000/docs
#   Dashboard: http://localhost:8000/dashboard/

# 4. Verify everything end-to-end (in-process, no server needed)
PYTHONPATH=. python scripts/verify_backend.py

# 5. (Optional) React frontend
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Set keys in `.env` (only needed to *re-generate* enrichment/explanations — the
committed JSON already contains the results):

```env
MAPPLS_STATIC_KEY=your_key_here
GEMINI_API_KEY=your_key_here
```

---

## API Endpoints

Every route is served at the bare path (React wire contract) **and** under `/api` (planner contract).

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Status + datasets loaded into memory |
| GET | `/heatmap?type=risk\|raw\|spillover` | Map points (congestion impact / violation density / calibrated) |
| GET | `/hotspots?limit=` | Ranked hotspot zones |
| GET | `/risk/top_zones?n=` | Top-N zones by congestion impact |
| GET | `/risk/{zone_id}` | Full zone detail (scores, components, game theory, real Mappls) |
| GET | `/stations` · `/stations/{name}/priority_areas` | Station list + ranked priority zones |
| GET | `/traffic/{zone_id}` | Real MapMyIndia travel-time ratio, road, POIs |
| POST | `/explain` | Cached Gemini zone explanation (grounded fallback if uncached) |
| GET | `/game/stackelberg_strategy` · `/game/violator_adaptation` · `/game/spillover_arrows` | Game-theory outputs |
| POST | `/simulate` | Team allocation → coverage % + waterbed spillover |
| GET | `/agent/validation-report` | 🤖 Self-validating agent: calibration summary + per-zone reasoning |
| GET | `/forecast/top_risk_zones` | Predicted top zones (proxy — see limitations) |

---

## The Congestion Impact Score

A 6-component weighted score (0–100):

```
score = 0.30·lane_blockage      +  # main-road & double parking → lanes lost
        0.25·intersection_impact +  # junction-approach violations → wasted green time
        0.25·traffic_degradation +  # MapMyIndia real travel_time_ratio
        0.10·access_blockage     +  # bus stops, hospitals, schools
        0.10·vehicle_size            # heavy-vehicle obstruction
```

| Band | Score |
|---|---|
| CRITICAL | 76–100 |
| SEVERE | 51–75 |
| MODERATE | 26–50 |
| MINIMAL | 0–25 |

---

## The Self-Validating Agent 🤖

`ml/agent/validation_agent.py` — wow-moment of the demo. After the model scores
each zone, the agent:

1. Reads the model's raw Congestion Impact Score.
2. Compares the slowdown the score *implies* against the **real MapMyIndia travel-time ratio**.
3. Calibrates the score with a bounded, trust-weighted update (α = 0.3, capped ±30%).
4. Logs a plain-English reason for every zone.

It is **deterministic and offline** — no LLM, no quota, no network. Example
(real output): *Subedar Chatram Road — adjusted 89 → 72 because MapMyIndia shows
only 1.08x travel time, not the 2.77x the raw score implied.* That correction is
the thesis in action: **violation density ≠ congestion impact.**

---

## Game-Theory Model

- **Patrol probability** ∝ score^1.5, normalized (Stackelberg — police as leader).
- **Violator utility** = (1 − patrol_prob)·time_saved − patrol_prob·fine (followers best-respond).
- **Waterbed effect** — enforcing a zone displaces violator pressure to the nearest uncovered zone.

Academic grounding (see `docs/presentation_outline.md`): Tambe (2011) security
games (ARMOR/IRIS/PROTECT); STREETS (Brown et al., AAAI 2014, traffic patrolling);
STOP (Trejo et al., 2017).

---

## Data & Honest Limitations

- The analysis is built on the Bengaluru Traffic Police violation dataset (~298k records, Nov 2023 – Apr 2024). The live API serves the **top hotspot zones, fully enriched** with real MapMyIndia data.
- **Temporal patterns reflect enforcement-shift recording**, not raw parking behaviour — so the forecast is best read as *predicted detection hotspots*, useful for patrol scheduling.
- **The forecast endpoint is a transparent proxy** derived from historical volume (`is_proxy: true`). The LightGBM artefact in `models/` was trained on synthetic seed data keyed by a different grid; a real per-H3 ensemble is the next integration step.
- **Congestion Impact is a proxy score**, not a measured value — the MapMyIndia ratio is the one externally measured signal, which is exactly why the self-validating agent exists.

---

## Team

| Person | Role |
|---|---|
| Person 1 | Backend — FastAPI, in-memory DataStore, API |
| Person 2 | ML — Congestion Impact Score, forecasting, game theory |
| Person 3 | Frontend — Vite/React, MapMyIndia SDK, UI/UX |
| Person 4 | Integration — LLM, MapMyIndia enrichment, self-validating agent, docs, presentation |

## Acknowledgements

MapMyIndia / Mappls (maps + traffic APIs) · Google Gemini (zone explanations) · Uber H3 (spatial indexing) · FastAPI.

## License

MIT
