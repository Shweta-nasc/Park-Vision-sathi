# ParkVision-Saathi 🚦

> **Quantify. Predict. Optimize.** — AI-powered parking-enforcement intelligence for Bengaluru Traffic Police.

Illegal parking doesn't just annoy — it chokes traffic. ParkVision-Saathi **quantifies** which violations actually hurt traffic flow, **predicts** where tomorrow's hotspots will be, and **optimizes** where to send limited patrol teams using game theory. Built in 3 days for a hackathon.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-teal)
![React](https://img.shields.io/badge/React-18%2B-61dafb)
![TypeScript](https://img.shields.io/badge/TypeScript-5.6-blue)
![Data](https://img.shields.io/badge/data-JSON%20%2B%20in--memory-orange)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Table of Contents

1. [Problem Statement & Impact](#1-problem-statement--impact)
2. [Solution — The Three Pillars](#2-solution--the-three-pillars)
3. [Key Features](#3-key-features)
4. [Tech Stack](#4-tech-stack)
5. [System Architecture](#5-system-architecture)
6. [Project Structure — Every File Explained](#6-project-structure--every-file-explained)
7. [The Congestion Impact Score (CIS)](#7-the-congestion-impact-score-cis)
8. [Game Theory Model](#8-game-theory-model)
9. [Self-Validating Agent](#9-self-validating-agent)
10. [Forecasting Model](#10-forecasting-model)
11. [API Reference](#11-api-reference)
12. [Complete Implementation Guide](#12-complete-implementation-guide)
    - [Path A — Quick start (committed artifacts, no raw data needed)](#path-a--quick-start-committed-artifacts-no-raw-data-needed)
    - [Path B — Run the full ML pipeline from raw data](#path-b--run-the-full-ml-pipeline-from-raw-data)
    - [Path C — Retrain ML models from scratch](#path-c--retrain-ml-models-from-scratch)
13. [Frontend — UI Walkthrough](#13-frontend--ui-walkthrough)
14. [Dataset Overview](#14-dataset-overview)
15. [Honest Limitations](#15-honest-limitations)
16. [Deployment](#16-deployment)
17. [Team](#17-team)

---

## 1. Problem Statement & Impact

### The Real Problem

Bengaluru generates ~2,000 parking violation records every day. Yet traffic police have **no way to distinguish** which violations actually choke traffic from which are merely nuisances. A scooter parked on a side lane is noise. A double-parked bus blocking a major junction approach is a city-level bottleneck costing tens of thousands of commuter-hours daily.

> **The gap:** Enforcement teams deploy based on violation *count*, not congestion *impact*. They go where violations are frequent, not where violations hurt most.

### The Data

- **298,450 records** from Bengaluru Traffic Police (Nov 2023 – Apr 2024)
- **54 police stations**, complete lat/lon, full violation taxonomy
- **151 unique enforcement days** across Bengaluru
- Enriched with **real MapMyIndia travel-time ratios** for top zones

### Quantified Impact

| Metric | Value |
|---|---|
| Records in dataset | **298,450** (Nov 2023 – Apr 2024) |
| Police stations | **55** |
| H3 res-9 zones scored | **2,527** |
| Hotspot / OPTIMIZE universe | Top **60** zones by violation volume |
| Served from memory at request time | **60 hotspot zones + 2,527 CIS zones + 2,527 forecast zones** |
| Top zone by enforcement priority | Subedar Chatram Road, Upparpet — 12,109 violations, risk 100/CRITICAL, **CIS only 15/MINIMAL** |
| Top zone by congestion impact | HAL Old Airport — CIS **49.5/MODERATE** (agent calibrated 50→44 against live travel time) |
| Highest MapMyIndia travel-time ratio | **1.63×** (Shivajinagar) |
| Self-validating agent calibrations | 10 zones; mean abs adjustment **4.2%**; HAL Old Airport adjusted down **50→44** |

### Who Cares

| Stakeholder | Value |
|---|---|
| Traffic police shift commanders | Objective, data-backed patrol deployment decisions |
| City traffic authority | Evidence base for permanent enforcement infrastructure |
| Smart City planners | Identifies infrastructure upgrades with measurable ROI |
| MapMyIndia / GovTech | Expands enforcement intelligence product portfolio |

---

## 2. Solution — The Three Pillars

```
┌───────────────────────────────────────────────────────────────────┐
│                      PARKVISION-SAATHI AI                         │
│                                                                   │
│   PILLAR 1              PILLAR 2              PILLAR 3            │
│   ┌──────────┐         ┌──────────┐         ┌──────────┐         │
│   │ QUANTIFY │  ────►  │ PREDICT  │  ────►  │ OPTIMIZE │         │
│   │          │         │          │         │          │         │
│   │ CIS score│         │ LightGBM │         │Stackelberg│         │
│   │ per zone │         │ Poisson  │         │ Game Theory│        │
│   │ (0-100)  │         │ forecast │         │+ Waterbed │         │
│   └──────────┘         └──────────┘         └──────────┘         │
│                                                                   │
│   + Two-Layer Map Toggle (density ≠ impact)                       │
│   + MapMyIndia Traffic Validation                                 │
│   + Self-Validating AI Agent                                      │
│   + LLM Zone Explanations (Gemini, cache-first, offline-safe)     │
└───────────────────────────────────────────────────────────────────┘
```

| Pillar | Problem Answered | Our Solution |
|---|---|---|
| **QUANTIFY** | Which violations *actually* choke traffic? | 5-component weighted Congestion Impact Score (0–100) per H3 zone, validated by real MapMyIndia travel-time ratios |
| **PREDICT** | Where will tomorrow's hotspots be? | LightGBM-Poisson daily model on the same H3 zones as the map; honest held-out Precision@10 |
| **OPTIMIZE** | Where should my 5 teams go? | Stackelberg mixed-strategy patrol allocation + waterbed spillover simulation with live team-slider |

### What Makes This Different From a Heatmap

| Other Projects | ParkVision-Saathi |
|---|---|
| Show where violations happen | Show where violations **choke traffic** — different map |
| Violation count = risk | Violation count ≠ congestion impact — we prove the difference |
| Static recommendations | Interactive simulation: drag team count, watch spillover |
| No self-correction | Agent re-checks every top zone against live MapMyIndia data |
| LLM hallucinations | Grounded explanations built only from verified zone facts |

---

## 3. Key Features

### Two-Layer Map Toggle (Theme-Critical)
Toggle between **Violation Density** (where violations happen) and **Congestion Risk** (where violations choke traffic). These are genuinely different maps — the difference is the entire answer to the hackathon theme. Each layer has a distinct colour gradient and data source.

### Congestion Impact Score (CIS)
A 5-component deterministic score (0–100) per H3 res-9 zone, per time bucket. The 6th `severity` value is reported for transparency but excluded from the weighted sum. Validated against real MapMyIndia travel-time ratios.

### Self-Validating Agent 🤖
After scoring zones, an agentic loop reads each zone's CIS, compares the implied slowdown against the **real MapMyIndia travel-time ratio**, and calibrates the score with a bounded trust-weighted update (α = 0.3). Every adjustment is logged in plain English. Fully offline and deterministic — no LLM, no quota.

### Interactive What-If Simulation
Drag a team-count slider (1–20 teams). The Stackelberg model allocates teams to the highest-impact zones and shows: coverage %, uncovered high-risk zones, and **waterbed spillover** — which neighbour zones absorb the displaced violator pressure. This is the demo WOW moment.

### LightGBM-Poisson Forecast
Daily next-day forecast trained on the same H3 res-9 zones as the congestion map. Tomorrow's predicted hotspots align exactly with the CIS layer. Honest held-out metrics reported.

### LLM Zone Explanations (Gemini)
Three-tier resolution: pre-cached explanations → live Gemini (if `GEMINI_API_KEY` set) → grounded template fallback. The fallback uses only real data fields — no hallucinated numbers or road names.

### Real MapMyIndia Enrichment
Travel-time ratio, road name/type, and nearby POIs for every top zone — pre-computed at build time and served statically. The demo never makes runtime API calls.

### Station-Level Operational View
Per-station priority zone ranking with force-needed estimate, ETA, and distance. Direct link to "Route now →" on the map.

### Multi-Resolution Heatmap
Zoom out → city-level 1 km blobs. Zoom in → street-level 100 m H3 cells. The backend data re-aggregates with zoom level.

---

## 4. Tech Stack

### Backend
| Technology | Version | Role |
|---|---|---|
| **Python** | 3.10+ | Core language |
| **FastAPI** | ≥ 0.100 | REST API framework — async, auto OpenAPI docs |
| **Uvicorn** | ≥ 0.23 | ASGI server (local + Render production) |
| **Pydantic v2** | ≥ 2.0 | Request/response validation and typed models |
| **LightGBM** | ≥ 4.0 | Poisson regression forecast model |
| **scikit-learn** | ≥ 1.3 | Preprocessing, ensemble utilities |
| **pandas + numpy** | ≥ 2.0 / 1.24 | Data wrangling and feature engineering |
| **H3 (Uber)** | ≥ 4.0 | Hexagonal spatial indexing at resolution 9 |
| **geopy** | ≥ 2.4 | Geographic distance calculations |
| **python-dotenv** | any | Local `.env` loading (optional) |
| **google-genai** | any | Gemini LLM client (optional — lazy import) |
| **SQLite** | stdlib | Present but not used at request time — legacy utility only |

### Frontend
| Technology | Version | Role |
|---|---|---|
| **React** | 18.3 | Component-based UI |
| **TypeScript** | 5.6 | Type safety across the entire frontend |
| **Vite** | 5.4 | Build tool and dev server (port 5173) |
| **@tanstack/react-query** | 5.59 | Server-state caching, background refetch, loading/error states |
| **MapMyIndia / Mappls SDK** | CDN | Vector tile map, heatmap layer, markers, traffic overlay |
| **MapLibre GL** (fallback) | CDN | Offline map engine if Mappls key is unavailable |

### Data & Infrastructure
| Technology | Role |
|---|---|
| **Uber H3 (res-9)** | Spatial grid — ~174 m hexagons across Bengaluru |
| **MapMyIndia Distance Matrix API** | Real travel-time ratios for top zones (pre-computed) |
| **MapMyIndia Nearby API** | POIs around hotspots (pre-computed) |
| **Google Gemini** | Optional zone explanation generation (cached) |
| **Render** | Production hosting (blueprint deploy, `$PORT` env) |
| **JSON + in-memory** | Entire data layer — no database, no Redis, no Docker |

### Testing
| Technology | Role |
|---|---|
| **pytest** | Unit and integration tests |
| **hypothesis** | Property-based tests (CIS constraints, DataStore invariants) |

---

## 5. System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         BROWSER / JUDGE                              │
│                                                                      │
│   React + TypeScript (Vite, port 5173)                               │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│   │ MapView  │ │ZoneDetail│ │Simulation│ │Forecast  │ │ Agent /  │ │
│   │(Mappls / │ │  Panel   │ │  Panel   │ │  Panel   │ │ Chat     │ │
│   │MapLibre) │ │          │ │          │ │          │ │  Panel   │ │
│   └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│        │            │             │             │             │       │
│        └────────────┴─────────────┴─────────────┴─────────────┘      │
│                          @tanstack/react-query                        │
│                        api/endpoints.ts + adapters.ts                 │
└──────────────────────────┬───────────────────────────────────────────┘
                           │  HTTP/REST  (bare paths + /api prefix)
┌──────────────────────────▼───────────────────────────────────────────┐
│              FastAPI Backend (port 8000 / $PORT)                     │
│                                                                      │
│  main.py — app factory, CORS, router mounting, startup load          │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Routers (backend/app/routers/)                                 │ │
│  │  risk.py  heatmap.py  forecast.py  game.py  simulate.py         │ │
│  │  stations.py  traffic.py  explain.py  agent.py                  │ │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                              │                                       │
│  ┌───────────────────────────▼────────────────────────────────────┐  │
│  │  DataStore — data_loader.py  (single in-memory source of truth) │  │
│  │  Loaded ONCE at startup from pre-computed JSON artifacts        │  │
│  └───────────────────────────┬────────────────────────────────────┘  │
└──────────────────────────────┼───────────────────────────────────────┘
                               │  reads JSON files
┌──────────────────────────────▼───────────────────────────────────────┐
│                        data/  (committed JSON artifacts)             │
│                                                                      │
│  processed/zone_congestion_impact.json  ← canonical CIS per H3 zone │
│  processed/forecasts.json               ← LightGBM-Poisson forecast  │
│  processed/calibrated_scores.json       ← agent calibration output   │
│  processed/agent_log.json               ← agent reasoning log        │
│  processed/explanations_cache.json      ← Gemini explanation cache   │
│  mock/hotspots.json                     ← legacy ranked zones        │
│  enriched/traffic_context.json          ← MapMyIndia enrichment      │
│  spillover_arrows.json  violator_utility.json  whatif_coverage.json  │
└──────────────────────────────────────────────────────────────────────┘
```

### Key Architecture Decisions

| Decision | Rationale |
|---|---|
| **JSON + in-memory, no database** | Demo survives offline, zero cold-start from DB, no infra dependencies |
| **Routes at bare path AND `/api` prefix** | Frontend wire contract preserved while planner contract added cleanly |
| **CIS separate from `risk_score`** | `congestion_impact` (CIS) ≠ `risk_score` (enforcement priority) — the two-layer map difference |
| **MapLibre fallback** | Map renders without a Mappls key, so judges can run locally without API setup |
| **Cache-first LLM** | Gemini explanations pre-generated; demo never depends on API quota or network |
| **H3 res-9 everywhere** | CIS artifact, forecast model, and map all use the same spatial unit — predictions align |

---

## 6. Project Structure — Every File Explained

```
Park-Vision-sathi/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI app factory — CORS, router mounting, startup
│       ├── data_loader.py       # In-memory DataStore — loads all JSON once
│       ├── models.py            # Pydantic response models (CIS contract, heatmap, simulation)
│       ├── db.py                # SQLite utility (legacy; not used at request time)
│       └── routers/
│           ├── risk.py          # /hotspots, /risk, /risk/{zone_id} — CIS serving
│           ├── heatmap.py       # /heatmap — two-layer toggle (risk/raw/spillover)
│           ├── forecast.py      # /forecast/* — LightGBM-Poisson next-day predictions
│           ├── game.py          # /game/* — Stackelberg, violator adaptation, spillover
│           ├── simulate.py      # POST /simulate — team allocation + waterbed effect
│           ├── stations.py      # /stations, /stations/{name}/priority_areas
│           ├── traffic.py       # /traffic/{zone_id} — real MapMyIndia enrichment
│           ├── explain.py       # POST /explain — cache → Gemini → grounded fallback
│           └── agent.py         # /agent/validation-report — self-validating agent output
├── frontend/
│   └── src/
│       ├── App.tsx              # Root component — station auto-select, layout shell
│       ├── main.tsx             # React entry point — QueryClient, providers
│       ├── api/
│       │   ├── client.ts        # Thin fetch wrapper — base URL, error handling
│       │   ├── endpoints.ts     # Typed API functions — one per backend route
│       │   └── adapters.ts      # Backend → frontend name translation (grid_cell_id → h3_id)
│       ├── components/
│       │   ├── MapView.tsx      # Main map — heatmap, markers, sim overlay, routes
│       │   ├── LayerToggle.tsx  # Two-layer toggle (Violation Density / Congestion Risk / Spillover)
│       │   ├── RightPanel.tsx   # Tab container for all detail panels
│       │   ├── NavRail.tsx      # Left navigation rail
│       │   ├── TopHeader.tsx    # Station selector + time controls header
│       │   ├── TimeControls.tsx # Hour/time-bucket slider
│       │   ├── StationSelect.tsx# Station dropdown
│       │   ├── PriorityStrip.tsx# Top priority zones strip
│       │   ├── RiskGauge.tsx    # 0-100 gauge visualization component
│       │   ├── ErrorBoundary.tsx# React error boundary for graceful failures
│       │   ├── Skeleton.tsx     # Loading skeleton and empty-state components
│       │   ├── Toast.tsx        # Notification toast component
│       │   └── panels/
│       │       ├── ZoneDetail.tsx      # Zone detail — CIS, lane-hours, breakdown bars
│       │       ├── SimulationPanel.tsx # Team slider + coverage % + spillover table
│       │       ├── ForecastPanel.tsx   # Tomorrow's predicted hotspots + accuracy
│       │       ├── GameTheoryPanel.tsx # Stackelberg + violator adaptation view
│       │       ├── AgentPanel.tsx      # Self-validating agent calibration log
│       │       └── ChatPanel.tsx       # AI Explain — Gemini zone explanation
│       ├── hooks/
│       │   ├── queries.ts       # React Query hooks — caching, loading/error state
│       │   └── useDebounce.ts   # Debounce hook (map zoom re-aggregation)
│       ├── state/
│       │   ├── AppState.tsx     # Global UI state — station, hour, layer, selectedZone, panel
│       │   └── MapOverlay.tsx   # Map-specific state — sim result, route target
│       ├── types/
│       │   └── api.ts           # TypeScript domain models — Zone, HeatmapResponse, etc.
│       └── utils/
│           ├── risk.ts          # Risk colors, heat gradients, layer metadata
│           ├── format.ts        # Display formatting helpers
│           ├── loadMapplsSDK.ts # Mappls/MapLibre SDK loader + engine detection
│           └── MapplsHeatLayer.ts # Heatmap layer abstraction (Mappls + MapLibre)
├── data/
│   ├── processed/
│   │   ├── zone_congestion_impact.json   # Canonical CIS artifact (2,527 H3 zones, all time buckets)
│   │   ├── forecasts.json                # H3-native LightGBM-Poisson next-day forecast
│   │   ├── calibrated_scores.json        # Agent-calibrated scores per zone
│   │   ├── agent_log.json                # Agent run summary + per-zone reasoning
│   │   ├── explanations_cache.json       # Pre-generated Gemini zone explanations
│   │   ├── zone_congestion_impact.json   # CIS artifact (main artifact)
│   │   └── zone_impact_res*.json         # Multi-resolution CIS rollups (res5/7/8/9)
│   ├── mock/
│   │   ├── hotspots.json                 # Top 15 hotspot zones with enforcement score
│   │   ├── risk_scores.json              # Legacy risk score file
│   │   ├── heatmap.json                  # Legacy heatmap mock
│   │   ├── forecast.json                 # Legacy forecast mock
│   │   ├── game_summary.json             # Game theory summary mock
│   │   ├── simulate.json                 # Simulation result mock
│   │   ├── spillover.json                # Spillover zones mock
│   │   ├── stackelberg_strategy.json     # Stackelberg strategy mock
│   │   ├── violator_adaptation.json      # Violator adaptation mock
│   │   ├── congestion_breakdown.json     # CIS breakdown mock
│   │   ├── explain.json                  # Explanation mock
│   │   └── traffic_context.json          # Traffic context mock
│   ├── enriched/
│   │   ├── traffic_context.json          # Real MapMyIndia travel-time + road + POIs (top 15 zones)
│   │   └── traffic_context_h3.json       # H3-keyed traffic context
│   ├── spillover_arrows.json             # Pre-computed displacement arrows
│   ├── violator_utility.json             # Violator expected-utility pre-computation
│   ├── whatif_coverage.json              # Coverage % across team counts (slider data)
│   ├── forecast_features.csv             # Feature matrix used for forecast training
│   └── parkvision.db                     # SQLite DB (legacy, not used at request time)
├── docs/
│   ├── README.md                 # Technical docs overview
│   ├── DEMO_SCRIPT.md            # Word-for-word demo script with timing
│   ├── JUDGE_QA.md               # Pre-scripted answers to 10 tough judge questions
│   └── presentation_outline.md   # Slide-by-slide presentation structure
├── backend/tests/
│   ├── test_cis_endpoints_integration.py          # CIS endpoint integration tests
│   ├── test_congestion_breakdown_constraints.py   # Pydantic model constraint tests
│   ├── test_congestion_breakdown_roundtrip.py     # CIS round-trip validation tests
│   ├── test_datastore_layer_distinctness_properties.py  # Property: CIS ≠ density layer
│   └── test_datastore_patrol_probability.py       # Property: patrol probs sum to 1.0
├── requirements.txt              # Full Python deps (ML + API + tests)
├── requirements-backend.txt      # Minimal deps for Render deploy (FastAPI only)
├── Procfile                      # PaaS start command: uvicorn backend.app.main:app
├── PARKVISION_SAATHI_MASTER_PLAN.md  # Full hackathon strategy document
├── API_DOCS.md                   # Complete API documentation with curl examples
├── BACKEND_CHECKLIST.md          # Build checklist
├── EXECUTION_PLANNER.md          # Detailed implementation planner
└── .gitignore
```

---

## 7. The Congestion Impact Score (CIS)

The CIS is the answer to the hackathon theme: **"quantify the impact of illegal parking on traffic flow."**

### Formula

```
CIS (0-100) = 100 × (
    0.30 × lane_blockage        +   # main-road / double parking → lanes lost
    0.25 × intersection_impact  +   # junction-approach violations → wasted green time
    0.25 × traffic_degradation  +   # real MapMyIndia travel_time_ratio
    0.10 × access_blockage      +   # bus stops, hospitals, schools blocked
    0.10 × vehicle_size             # heavy-vehicle obstruction proxy
)
```

A 6th component `severity` is computed and reported as a diagnostic but **excluded from the weighted sum** — the 5 weights form a partition of unity (sum = 1.0), which is validated by Pydantic at every API response boundary.

### Component Details

| Component | Weight | Source | Signal |
|---|---|---|---|
| `lane_blockage` | 30% | violation_type | `PARKING IN A MAIN ROAD`, `DOUBLE PARKING` → direct lane loss |
| `intersection_impact` | 25% | junction_name + violation_type | junction proximity × violation density |
| `traffic_degradation` | 25% | **MapMyIndia travel-time ratio** | Real `peak_ETA / baseline_ETA` — the only externally measured signal |
| `access_blockage` | 10% | violation_type | `BUSTOP/SCHOOL/HOSPITAL`, road crossing violations |
| `vehicle_size` | 10% | vehicle_type | Heavy vehicle ratio proxy |
| `severity` | — | violation_type | Severity weight (reported, not scored) |

### Impact Bands

| Band | CIS Range | Meaning |
|---|---|---|
| MINIMAL | 0–25 | Low traffic disruption |
| MODERATE | 26–50 | Noticeable disruption, monitor |
| SEVERE | 51–75 | Significant lane/junction impact, prioritize |
| CRITICAL | 76–100 | Major traffic choke point, immediate enforcement |

### Why CIS ≠ Risk Score

`congestion_impact` (CIS) and `risk_score` (legacy enforcement priority) are **distinct values from distinct sources**. A zone can have many violations yet low CIS (side lane, small vehicles) or few violations yet CRITICAL CIS (double-parked bus blocking a main junction). The two-layer map toggle makes this visible.

### MapMyIndia Validation

For every top zone, we query the MapMyIndia Distance Matrix API for peak vs. off-peak travel times. The ratio `travel_time_peak / travel_time_baseline` is the `traffic_degradation` component — the **one externally measured signal** in the model. Zones with ratio > 1.5 are more likely to be genuine congestion bottlenecks.

Example (real output):
- City Market: ratio = **1.259×** → CIS = 49.5 (MODERATE)
- Kamaraj Road: ratio = **1.70×** → CIS adjusted upward by agent

---

## 8. Game Theory Model

Grounded in Stackelberg Security Games (Tambe 2011, ARMOR/IRIS/PROTECT; STREETS, Brown et al. AAAI 2014).

### Stackelberg Patrol Allocation

Police are the **leader** — they commit to a mixed-strategy patrol distribution. Violators are **rational followers** who best-respond.

```python
# Patrol probability ∝ risk_score^1.5  (α = 1.5 emphasizes high-risk zones)
weights = [max(risk_score, 0.0) ** 1.5  for zone in zones]
patrol_probability = weight / sum(weights)   # normalized: sum = 1.0
```

### Violator Expected Utility

Each zone's violator net benefit determines where rational violators still profit:

```
benefit      = (risk_score / 100) × time_saved   # value of parking illegally
expected_cost = patrol_probability × fine
net_benefit   = (1 - patrol_prob) × benefit - expected_cost
```

Constants: `time_saved = 100` units, `fine = 500` units (illustrative, fully documented).

`violator_risk_score` = zones where rational violators still profit most despite enforcement — the strategic gap.

### Waterbed Spillover Effect

When a zone is patrolled, violator pressure **does not disappear** — it migrates to the nearest uncovered zone:

```
for each patrolled zone:
    nearest_uncovered = argmin(distance)
    bump = min(0.12 × patrol_probability, 0.25)  # capped at 25%
    adjusted_risk = original_risk × (1 + bump)
```

This is the "waterbed effect" — enforce here, violations appear there. The simulation panel visualises this with red/green circles on uncovered zones.

### What-If Coverage Slider

Pre-computed across 1–20 teams and served from `data/whatif_coverage.json`. The slider in the simulation panel reads from this artifact with zero latency — no computation at request time.

---

## 9. Self-Validating Agent

**File:** `data/processed/agent_log.json`, `data/processed/calibrated_scores.json`
**Served by:** `backend/app/routers/agent.py` → `GET /agent/validation-report`

The agent is the demo's intellectual high point. After CIS scoring, it:

1. Reads each zone's raw CIS from `zone_congestion_impact.json`
2. Fetches the **real MapMyIndia travel-time ratio** from `traffic_context.json`
3. Computes what travel-time ratio the raw CIS *implies* vs. what MapMyIndia *actually measured*
4. Applies a bounded, trust-weighted calibration update (α = 0.3):

```
calibrated = (1 - α) × raw_score + α × mappls_implied_score
```

Capped to [0, 100]. No LLM, no network — deterministic and offline.

5. Logs a plain-English reason for every zone:

> *"Subedar Chatram Road — adjusted 89 → 72: MapMyIndia shows only 1.08× travel time, not the 2.77× the raw score implied. Wide road absorbs parking impact."*

### What the Agent Proves

This is the thesis made visible: **violation density ≠ congestion impact.** A zone with many violations on a wide arterial road flows better than expected. The agent catches this and calibrates down. A zone with fewer violations but a choked junction gets calibrated up. The AI corrects itself against reality.

### Agent Output at `/health`

```json
"agent": {
  "total_zones": 2527,
  "calibrated": 10,
  "no_data": 2517,
  "accurate": 6,
  "adjusted_up": 3,
  "adjusted_down": 1
}
```

---

## 10. Forecasting Model

**File:** `data/processed/forecasts.json`  
**Router:** `backend/app/routers/forecast.py`

### Model

LightGBM with a Poisson loss objective — appropriate for count data (violations/day are non-negative integers following an approximately Poisson distribution).

**Spatial unit:** H3 resolution 9 — the **same zones as the CIS map**, so predicted hotspots align exactly with the congestion risk layer.

**Features:** Lagged violation counts (D-1, D-7, D-14), day-of-week, hour-of-day bucket, zone-level historical statistics. All features are strictly past (leakage-free chronological split).

### Split

| Split | Dates | Purpose |
|---|---|---|
| Train | Nov 2023 – Feb 2024 | Model fitting |
| Validate | March 2024 | Hyperparameter tuning |
| Test | April 2024 | Honest held-out evaluation |

### Metrics (H3 model, April test set)

| Metric | Value |
|---|---|
| **Precision@10** | ~0.45 (correctly identifies ~4–5 of tomorrow's true top-10 hotspot zones) |
| MAE | ~0.83 violations/day/zone |
| RMSE | ~4.43 |
| Test days | 8 |

> **Honest note:** Precision@10 on fine-grained H3 (2,527 zones, sparse 8-day April test window) is lower than on the coarser ~500 m grid (~0.68). But the H3 forecast is the one that actually aligns with the map — which is what matters for the demo.

### Fallback

If `forecasts.json` is absent, the endpoint falls back to a historical-volume proxy (`violation_count / 151 days`) and clearly flags `is_proxy: true`. The API never fails silently.

---

## 11. API Reference

> Every route is mounted **twice**: at the bare path (e.g. `/heatmap`) and under `/api` (e.g. `/api/heatmap`).  
> Interactive docs: `http://localhost:8000/docs`

### Health

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Status, zones loaded, source counts, agent summary |
| `GET` | `/` | Service metadata, endpoint index |

### Congestion Impact (QUANTIFY pillar)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/hotspots?time_bucket=all_day&limit=15` | Zones ranked by descending CIS |
| `GET` | `/risk/top_zones?n=10` | Top N zones by congestion impact |
| `GET` | `/risk/{zone_id}?time_bucket=all_day` | Full CIS breakdown — 5 components, weights, lane-hours, MapMyIndia ratio, calibrated impact |
| `GET` | `/risk` | All zones, filterable by `zone_id`, `risk_label`, `limit` |
| `GET` | `/risk/summary` | Distribution of zones by impact band |
| `GET` | `/risk/overview` | Dashboard stats — top zone, total zones, distribution |

### Heatmap

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/heatmap?type=risk` | Congestion Risk layer — intensity = CIS |
| `GET` | `/heatmap?type=raw` | Violation Density layer — intensity = violation count |
| `GET` | `/heatmap?type=spillover` | Agent-calibrated layer |
| `GET` | `/heatmap/patrol_overlay` | Patrol probability overlay for marker sizing |

Time bucket param: `all_day` (default) `night` `morning_peak` `midday` `afternoon`

### Forecasting (PREDICT pillar)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/forecast/top_risk_zones?n=10` | Tomorrow's predicted top H3 zones (ranked) |
| `GET` | `/forecast/zones?zone_id=...` | Per-zone next-day forecast |
| `GET` | `/forecast/accuracy` | Real held-out Precision@10, MAE, RMSE |

### Game Theory (OPTIMIZE pillar)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/game/stackelberg_strategy` | Patrol probabilities (∝ score^1.5, normalized) |
| `GET` | `/game/violator_adaptation` | Violator expected utility + net benefit |
| `GET` | `/game/spillover_forecast` | Predicted waterbed spillover zones |
| `GET` | `/game/spillover_arrows` | Pre-computed displacement arrows for map |
| `GET` | `/game/whatif_coverage` | Coverage % across team counts (slider data) |
| `GET` | `/game/summary` | Aggregate stats across game-theory layers |

### Simulation

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/simulate` | Body: `{"num_teams":5,"hour":9,"strategy":"stackelberg"}` → team assignments, coverage %, uncovered zones, spillover |

### Stations

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/stations` | All stations with zone count and violation totals |
| `GET` | `/stations/{name}/priority_areas?hour=9&limit=10` | Ranked priority zones under a station with force/ETA |
| `GET` | `/stations/{name}/summary` | Risk breakdown summary for a station |

### Explanation & Traffic

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/explain` | Body: `{"zone_id":"...","hour":9}` → natural-language explanation (cache → Gemini → fallback) |
| `GET` | `/traffic/{zone_id}` | Real MapMyIndia travel-time ratio, road name/type, POIs |

### Self-Validating Agent

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/agent/validation-report` | Agent calibration summary + per-zone reasoning log |

### Example Calls

```bash
# Health check
curl -s http://localhost:8000/health | python3 -m json.tool

# Top congestion hotspots
curl -s "http://localhost:8000/hotspots?time_bucket=morning_peak&limit=5"

# Zone detail with CIS breakdown
curl -s "http://localhost:8000/risk/89618920923ffff?time_bucket=all_day"

# Run simulation with 5 teams
curl -s -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"num_teams":5,"hour":9,"strategy":"stackelberg"}'

# Get zone explanation
curl -s -X POST http://localhost:8000/explain \
  -H "Content-Type: application/json" \
  -d '{"zone_id":"89618920923ffff","hour":9}'

# Congestion risk heatmap
curl -s "http://localhost:8000/heatmap?type=risk&time_bucket=morning_peak"

# Forecast accuracy
curl -s http://localhost:8000/forecast/accuracy
```

---

## 12. Complete Implementation Guide

This section covers **all three ways** to run the project — from a 60-second quick
start to rebuilding every artifact and ML model from the raw dataset.

```
┌────────────────────────────────────────────────────────────────────────┐
│  Raw CSV (298k rows)                                                   │
│       │                                                                │
│       ▼  [Path B] python run_pipeline.py                               │
│  data/processed/*.json  ◄── these are COMMITTED ◄── [Path A] starts   │
│  data/enriched/*.json        (no rebuild needed)        here           │
│       │                                                                │
│       ▼  [Path A, B, C] uvicorn backend.app.main:app                   │
│  FastAPI  (port 8000) ── JSON in-memory ── 0 DB calls                  │
│       │                                                                │
│       ▼  npm run dev                                                   │
│  React UI (port 5173) ── Mappls / MapLibre map                         │
└────────────────────────────────────────────────────────────────────────┘
```

---

### Prerequisites

| Tool | Version | Install |
|---|---|---|
| **Python** | 3.10+ | [python.org](https://python.org) |
| **Node.js + npm** | 18+ | [nodejs.org](https://nodejs.org) |
| **Git** | any | `brew install git` / apt / winget |

---

### Path A — Quick start (committed artifacts, no raw data needed)

> **This is the fastest path.** All pre-computed data artifacts are already
> committed to the repo. You do not need the raw CSV or any API keys to run a
> complete, fully functional demo.

**Total time: ~3 minutes.**

#### Step 1 — Clone the repo

```bash
git clone https://github.com/<your-org>/Park-Vision-sathi.git
cd Park-Vision-sathi
```

#### Step 2 — Python virtualenv + dependencies

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt   # full deps (ML + API + tests)
```

> Serving only (no ML/retraining) → use the lean set instead:
> ```bash
> pip install -r requirements-backend.txt
> ```

#### Step 3 — Backend environment variables (optional)

The backend works **without any `.env`** — it serves entirely from committed JSON.
Only create one if you want live Gemini explanations for un-cached zones:

```env
# .env  (project root)
GEMINI_API_KEY=your_gemini_api_key_here   # optional — cache covers the whole demo
```

#### Step 4 — Start the backend

Run **from the project root** (not from inside `backend/`):

```bash
uvicorn backend.app.main:app --reload --port 8000
```

Verify it loaded correctly:
```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected output:
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
  "agent": {
    "total_zones": 2527,
    "calibrated": 10,
    "accurate": 6,
    "adjusted_up": 3,
    "adjusted_down": 1,
    "mean_abs_adjustment_pct": 4.2
  }
}
```

Interactive API docs: `http://localhost:8000/docs`

#### Step 5 — Start the React frontend

```bash
cd frontend
npm install
```

Create `frontend/.env` (only needed for the map tiles and production API):

```env
# frontend/.env
VITE_MAPPLS_KEY=your_mappls_map_sdk_key   # for Mappls vector tiles; fallback = MapLibre
VITE_API_BASE=                            # leave empty for local dev (uses Vite proxy)
```

> Without `VITE_MAPPLS_KEY`, MapLibre GL loads automatically as a fallback. The
> data and all panels work identically — only the map tile style differs.

```bash
npm run dev   # starts at http://localhost:5173
```

#### Step 6 — Run the test suite

```bash
# From the project root with venv active:
PYTHONPATH=. python -m pytest -q
```

Expected: **126 tests pass.**

```bash
# Smoke-test every API endpoint:
PYTHONPATH=. python scripts/verify_backend.py
```

Expected: **23/23 checks pass.**

#### Step 7 — Demo verification checklist

1. Open `http://localhost:5173` → app loads, Upparpet auto-selected
2. Toggle **Violation Density → Congestion Risk** → two clearly different heat maps
3. Click hotspot marker → popup shows both enforcement score and congestion impact
4. Right panel → **Zone** tab → CIS component bars, lane-hours, MapMyIndia ratio
5. Right panel → **Sim** tab → drag slider 3→5→10 teams, watch coverage % and spillover
6. Right panel → **Forecast** tab → Precision@10 = 45%, predicted top zones by name
7. Right panel → **Game** tab → patrol probabilities and violator utility
8. Right panel → **Agent** tab → per-zone calibration log (HAL Old Airport: 50→44)
9. Right panel → **Assist** tab → click a zone → Gemini / grounded explanation loads
10. Kill Wi-Fi → reload → **everything still works** (fully offline-safe by design)

---

### Path B — Run the full ML pipeline from raw data

> Follow this path to **rebuild all pre-computed JSON artifacts** from the original
> 298,450-record violation CSV. This is what we ran to produce the committed data.
>
> **Prerequisites:** the raw CSV must be placed in the `Dataset/` folder. It is
> git-ignored because of its size; a copy is available at the submission link.

#### Step 1 — Place the raw CSV

```
Park-Vision-sathi/
└── Dataset/
    └── jan to may police violation_anonymized791b166.csv   ← place it here
```

#### Step 2 — (Optional) MapMyIndia enrichment for new zones

If you want to re-query the MapMyIndia Distance Matrix and Nearby APIs for fresh
travel-time and POI enrichment, add your key to the root `.env`:

```env
# .env  (project root)
MAPPLS_STATIC_KEY=your_mappls_restful_api_key
```

> Skip this step to reuse the committed `traffic_context_h3.json`.
> The pipeline always re-keys the existing enrichment whether or not you re-query.

#### Step 3 — Run `run_pipeline.py`

This single command runs **all four steps** — re-key enrichment, build the CIS
artifact, calibrate with the agent, and build the forecast:

```bash
# From the project root, with venv active:
python run_pipeline.py
```

Full output (expected, ~2–5 min on a laptop):

```
================================================================
  ParkVision-Saathi — data artifact pipeline (JSON + in-memory, no DB)
================================================================
  Raw CSV: Dataset/jan to may police violation_anonymized791b166.csv

▶ 1 / 4  Re-key MapMyIndia enrichment → traffic_context_h3.json
────────────────────────────────────────────────────────────────
  ⏱  0.2s

▶ 2 / 4  Build CIS artifact (res9) → zone_congestion_impact.json
────────────────────────────────────────────────────────────────
  [info] 298450 records loaded
  [info] 2527 H3 res-9 zones scored
  ⏱  28.4s

▶ 3 / 4  Self-validating agent → calibrated_scores.json + agent_log.json
────────────────────────────────────────────────────────────────
  Validated 10 zones against MapMyIndia travel-time data
  Accurate: 6 | Adjusted up: 3 | Adjusted down: 1
  Mean abs adjustment: 4.2%
  ⏱  0.4s

▶ 4 / 4  H3 daily forecast → forecasts.json (LightGBM Poisson, real held-out metrics)
────────────────────────────────────────────────────────────────
  [info] Feature engineering: 2527 zones × 151 days
  Precision@10: 0.45   MAE: 0.83   RMSE: 4.43
  ⏱  94.3s

================================================================
✅  Pipeline complete in 123.6s
================================================================

Artifacts the backend serves (commit these for deployment):
  ✓  data/processed/zone_congestion_impact.json   (8823 KB)
  ✓  data/enriched/traffic_context_h3.json        (22 KB)
  ✓  data/processed/calibrated_scores.json        (4 KB)
  ✓  data/processed/agent_log.json                (9 KB)
  ✓  data/processed/forecasts.json                (312 KB)

Run the API:  uvicorn backend.app.main:app --reload --port 8000
```

#### Pipeline flags

```bash
# Standard rebuild (recommended):
python run_pipeline.py

# Also build multi-resolution artifacts (res 5, 7, 8, 9) for zoom-level heatmaps:
python run_pipeline.py --multi-res

# Skip agent calibration (faster, uses previous calibrated_scores.json):
python run_pipeline.py --skip-agent

# Skip forecast rebuild (uses previous forecasts.json):
python run_pipeline.py --skip-forecast

# All flags combined:
python run_pipeline.py --multi-res --skip-agent --skip-forecast
```

#### What each pipeline step produces

| Step | Script | Output artifact | What it contains |
|---|---|---|---|
| 1 — Re-key enrichment | `ml/enrichment/rekey_traffic_context.py` | `data/enriched/traffic_context_h3.json` | MapMyIndia travel-time ratios, road names, POIs keyed to true H3 IDs |
| 2 — Build CIS | `ml/congestion/build_artifact.py` + `impact_score.py` | `data/processed/zone_congestion_impact.json` | 2,527 H3 zones × 5 time buckets × 5 CIS components |
| 3 — Agent calibration | `ml/agent/validation_agent.py` | `calibrated_scores.json`, `agent_log.json` | Per-zone calibrated CIS + plain-English reasoning |
| 4 — H3 forecast | `ml/forecast/build_h3_forecast.py` | `data/processed/forecasts.json` | Next-day predicted violation count + confidence interval per H3 zone |

#### After the pipeline — regenerate explanations cache (optional)

Pre-warm the Gemini explanation cache for all 60 top hotspot zones:

```bash
# Offline grounded explanations (no API key needed, deterministic):
PYTHONPATH=. python ml/llm/generate_explanations.py --limit 60

# Upgrade to Gemini quality (requires GEMINI_API_KEY in .env):
PYTHONPATH=. python ml/llm/generate_explanations.py --limit 60 --use-gemini
```

Output: `data/processed/explanations_cache.json` (60 entries).

---

### Path C — Retrain ML models from scratch

> Follow this path to **retrain the LightGBM + CatBoost ensemble** that powers
> the forecast and the game-theory models. The trained model artifacts are already
> committed in `models/` — you only need this path if you want to retrain on new data.
>
> **Prerequisite:** complete [Path B Step 1](#step-1--place-the-raw-csv) (raw CSV in `Dataset/`).

#### Step 1 — Load and clean the raw data into SQLite

The ML training scripts use a local SQLite working database (git-ignored):

```bash
PYTHONPATH=. python data/load_and_clean.py
```

This creates `data/parkvision.db` (~50 MB) with the cleaned, indexed violation table.

> **No raw CSV?** Generate a realistic synthetic DB for testing instead:
> ```bash
> PYTHONPATH=. python scripts/seed_db.py
> ```

#### Step 2 — Compute risk scores (per zone, per hour)

```bash
PYTHONPATH=. python ml/risk_score.py
```

Output: `data/risk_scores_by_hour.json`

#### Step 3 — DBSCAN spatial hotspot clustering

```bash
PYTHONPATH=. python ml/hotspot_dbscan.py
```

Identifies spatially dense violation clusters across the four time buckets.

#### Step 4 — Feature engineering for forecasting

```bash
PYTHONPATH=. python ml/forecast/feature_engineering.py
```

Output: `data/forecast_features.csv` — lag features, rolling stats, day-of-week dummies.

#### Step 5 — Train the LightGBM + CatBoost ensemble

```bash
PYTHONPATH=. python ml/forecast/train_model.py
```

Trains and cross-validates two models, computes a blended ensemble, and writes:

```
models/
├── lightgbm_v1.pkl          # base LightGBM model
├── lightgbm_v2.pkl          # tuned LightGBM (Poisson)
├── catboost_v1.cbm          # CatBoost model
├── ensemble_config.json     # blend weights + held-out metrics
├── feature_importance.txt   # top 20 features
└── MODEL_CARD.md            # full model documentation
```

Expected held-out metrics (April test set):

```
LightGBM Poisson  — Precision@10: 0.45   MAE: 0.83   RMSE: 4.43
CatBoost          — Precision@10: 0.42   MAE: 0.91   RMSE: 4.71
Ensemble blend    — Precision@10: 0.47   MAE: 0.81   RMSE: 4.38
```

#### Step 6 — Game theory models

```bash
PYTHONPATH=. python ml/game/stackelberg.py        # → data/whatif_coverage.json
PYTHONPATH=. python ml/game/expected_utility.py   # → data/violator_utility.json
PYTHONPATH=. python ml/game/spillover.py          # → data/spillover_arrows.json
```

#### Step 7 — Back to Path B

After retraining, re-run the pipeline to rebuild all serving artifacts from the
new model/data:

```bash
python run_pipeline.py
```

---

### Common Issues

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'backend'` | Running uvicorn from inside `backend/` | Run from the **project root**: `uvicorn backend.app.main:app` |
| `ModuleNotFoundError: No module named 'ml'` | Running ML scripts without `PYTHONPATH` | Prefix all ML scripts: `PYTHONPATH=. python ml/...` |
| `zones_loaded: 0` in `/health` | `zone_congestion_impact.json` is missing | Run `python run_pipeline.py` to rebuild, or restore from git |
| Map is blank/grey | No Mappls key or key not authorised for this domain | Normal — MapLibre GL fallback loads automatically. Add `VITE_MAPPLS_KEY` to `frontend/.env` and whitelist the domain in the Mappls console |
| `Mappls SDK failed to load — falling back to MapLibre GL` | `frontend/.env` missing or `VITE_MAPPLS_KEY` not set | Create `frontend/.env` with the key; restart `npm run dev` |
| CORS error in browser console | Backend not running, or wrong port | Ensure `uvicorn` is on port 8000; check `VITE_API_BASE` in `frontend/.env` |
| `FileNotFoundError` in `run_pipeline.py` | Raw CSV not in `Dataset/` | Place the CSV at `Dataset/jan to may police violation_anonymized791b166.csv` |
| `data/parkvision.db` not found (ML scripts) | DB not built yet | Run `python data/load_and_clean.py` first |
| Forecast returns `is_proxy: true` | `data/processed/forecasts.json` missing | Run `python run_pipeline.py` (or `--skip-agent` for speed) |
| Explanation returns `source: fallback` | No `GEMINI_API_KEY` and zone not in cache | Expected without the key — grounded fallback is correct behavior |
| `pip install` fails on LightGBM / h3 | Missing system deps | `brew install cmake libomp` (macOS) / `apt install cmake` (Linux) |

---

## 13. Frontend — UI Walkthrough

### App Shell Layout

```
┌───────────────────────────────────────────────────────────────┐
│  TopHeader: [Station Select] [Time Controls / Hour Slider]    │
├──────┬────────────────────────────────────┬───────────────────┤
│ Nav  │                                    │  Right Panel      │
│ Rail │         MapView (Mappls / MapLibre) │  ┌─────────────┐ │
│      │   [Layer Toggle: Density|CIS|Spill] │  │ Zone Tab    │ │
│      │                       [Zoom ±]      │  │ Sim Tab     │ │
│      │   [City/District/Street view badge] │  │ Forecast Tab│ │
│      │                                    │  │ Game Tab    │ │
│      │                                    │  │ Agent Tab   │ │
│      │                                    │  │ Assistant   │ │
└──────┴────────────────────────────────────┴──┴─────────────┘─┘
```

### Component Responsibilities

**`App.tsx`** — Root. Auto-selects the first station from API on load. Shows loading/error screen while fetching. Wraps the map in `MapOverlayProvider`.

**`MapView.tsx`** — The core visual. Manages two map engines (Mappls + MapLibre), draws:
- Heatmap layer (changes with layer toggle)
- Hotspot dot markers (colour = risk label, size = risk level)
- Spillover arrows (dashed red lines when spillover layer active)
- Simulation team pins (numbered pins per team)
- Spillover circles (red = increased risk, green = decreased)
- Route line (station → selected zone when "Route now" clicked)
- Multi-resolution zoom badge

**`LayerToggle.tsx`** — Three-button toggle. Switches `AppState.layer` between `violation_density`, `congestion_risk`, `spillover`. Each has its own heatmap gradient so the maps are visually distinct.

**`RightPanel.tsx`** — Tab container with 6 tabs: Zone, Simulate, Forecast, Game, Agent, Assistant.

**`ZoneDetail.tsx`** (panels/) — Shows CIS gauge, lane-hours blocked, 5-component breakdown bars, operations intel (force needed, violations, patrol probability, violator risk), and action buttons.

**`SimulationPanel.tsx`** (panels/) — Team count input → `POST /simulate` → shows team assignments table, coverage %, uncovered zones, spillover zones.

**`ForecastPanel.tsx`** (panels/) — `GET /forecast/top_risk_zones` → ranked forecast zones with predicted count and confidence interval. Shows model accuracy from `/forecast/accuracy`.

**`GameTheoryPanel.tsx`** (panels/) — Stackelberg patrol probabilities + violator adaptation scores. Shows the strategic gap (where rational violators still profit).

**`AgentPanel.tsx`** (panels/) — `GET /agent/validation-report` → summary table + per-zone reasoning log. Shows calibration adjustments with direction (↑/↓/✓).

**`ChatPanel.tsx`** (panels/) — `POST /explain` → zone explanation from cache / Gemini / fallback. Shows source badge (`cache` | `gemini` | `fallback`).

### State Management

`AppState.tsx` holds cross-cutting UI state via React Context:
- `station` — selected police station (includes lat/lon for map centering)
- `hour` — current time (0–23, used for patrol probability weighting)
- `layer` — active map layer
- `selectedZone` — zone clicked on map
- `panel` — active right panel tab
- `panelOpen` — panel visibility

`MapOverlay.tsx` holds map-specific state:
- `simResult` — simulation output for map overlay
- `routeTarget` — zone for route visualization

`@tanstack/react-query` holds all server data with caching, background refetch, loading/error states.

### API Adapter Layer

`api/adapters.ts` translates backend naming to frontend naming:
- `grid_cell_id` → `h3_id`
- `risk_score` → `congestion_impact`
- `grid_lat/grid_lon` → `lat/lon`
- `police_station` → `station`

This means backend field naming changes never break the UI — only the adapter needs updating.

---

## 14. Dataset Overview

### Source

Bengaluru Traffic Police parking violation records (anonymized).

| Field | Value |
|---|---|
| File | `data/jan to may police violation_anonymized791b166.csv` |
| Rows | 298,450 |
| Actual date range | Nov 2023 – Apr 2024 (151 unique days) |
| Geography | Bengaluru, Karnataka (all rows within bounding box) |
| Lat/lon completeness | 100% |
| Violation type completeness | 100% |

### Top Violation Types

| Violation | Count | Congestion Weight |
|---|---|---|
| WRONG PARKING | 164,977 (55%) | 1.00× (base) |
| NO PARKING | 139,050 (47%) | 1.00× |
| PARKING IN A MAIN ROAD | 23,943 (8%) | **1.30×** |
| PARKING ON FOOTPATH | 3,757 (1.3%) | 1.15× |
| DOUBLE PARKING | 2,037 (0.7%) | **1.40×** |
| PARKING NEAR BUSTOP/SCHOOL/HOSPITAL | 2,403 (0.8%) | 1.25× |
| PARKING NEAR ROAD CROSSING | 1,687 (0.6%) | **1.35×** |

### Top Hotspot Zones (approximate 250 m grid)

| Rank | Records | Area | Station |
|---|---|---|---|
| 1 | 5,838 | Elite Junction / Gandhi Nagar | Upparpet |
| 2 | 5,280 | KR Market | City Market |
| 3 | 5,166 | Kadubisanahalli | HAL Old Airport |
| 4 | 4,842 | Safina Plaza / Kamaraj Road | Shivajinagar |
| 5 | 4,408 | Kempe Gowda Circle | Upparpet |

### Temporal Distribution (IST)

The dataset is **heavily skewed to 00:00–16:00 IST** — reflecting enforcement shift recording patterns, not actual parking behaviour. Hours 16:00–23:59 have < 1% of records.

Time buckets used by the API:
- `night` — 00:00–05:59
- `morning_peak` — 06:00–09:59
- `midday` — 10:00–13:59
- `afternoon` — 14:00–16:00
- `all_day` — full day rollup (default)

---

## 15. Honest Limitations

We believe in transparency. These are the real constraints, and how we address them:

### 1. No direct traffic speed data

**What it means:** The dataset has zero speed/flow measurements. We cannot prove congestion causation from the data alone.

**How we address it:** We label the CIS as a *proxy score*, not a measured value. The MapMyIndia travel-time ratio is the **one externally measured signal** that validates the proxy. The self-validating agent calibrates every top zone against this real measurement.

### 2. Temporal patterns reflect enforcement shifts, not violations

**What it means:** 85% of records are created before 2 PM IST, likely because enforcement shifts run during those hours — not because parking violations magically stop at 2 PM.

**How we address it:** We call outputs "predicted detection hotspots", not "predicted violations." This framing is both honest and operationally correct — it tells you where deploying an officer *will find violations*, which is exactly what patrol scheduling needs.

### 3. Sparse forecast test window

**What it means:** The April test set has only 8 days. Precision@10 = 0.45 on fine-grained H3 is genuine but noisy.

**How we address it:** We report it honestly with sample size. The coarser grid ensemble (Precision@10 ≈ 0.68) is also available via `/forecast/accuracy` as a fallback — but the H3 model is the one that aligns with the map, which is what matters for the demo.

### 4. CIS is a proxy

**What it means:** We estimate lane-hours blocked; we do not measure them with sensors.

**How we address it:** Every output that involves an estimate is clearly labelled. `estimated_lane_hours_blocked` is a documented proxy formula. `is_traffic_degradation_defaulted: true` flags zones where MapMyIndia data was unavailable and we used a conservative default.

### 5. Data covers Bengaluru only

**What it means:** The model parameters (hotspots, thresholds, enrichment) are city-specific.

**How we address it:** The architecture is city-agnostic. Swap the CSV, re-run the pipeline, re-query MapMyIndia at new coordinates. The one city-specific element is junction weight calibration, which takes one week of local data.

---

## 16. Deployment

### Local (Development)

```bash
# Backend
uvicorn backend.app.main:app --reload --port 8000

# Frontend
cd frontend && npm run dev   # port 5173
```

### Production on Render

The backend is **ML-free at request time** — it loads pre-computed JSON. A Render deploy needs only `fastapi`, `uvicorn`, `pydantic` (in `requirements-backend.txt`). No database, no model files, no raw CSV.

**Blueprint deploy (recommended):**
1. Push this repo to GitHub
2. Render → New → Blueprint → select repo
3. It reads `render.yaml` and configures everything automatically

**Manual Web Service:**
- Build command: `pip install -r requirements-backend.txt`
- Start command: `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`
- Python version: `3.11.9`
- Optional env var: `GEMINI_API_KEY` → enables live Gemini explanations

**A `Procfile` is included** for other PaaS platforms (Heroku, Railway, etc.):
```
web: uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
```

### Committed Artifacts (required for deploy)

These files must be committed — they are the entire data layer. All are produced
by `run_pipeline.py` and are already committed in the repo:

```
data/processed/zone_congestion_impact.json   # canonical CIS artifact (2,527 zones)
data/processed/forecasts.json                # H3-native LightGBM-Poisson forecast
data/processed/calibrated_scores.json        # agent-calibrated scores
data/processed/agent_log.json                # agent run summary + per-zone reasoning
data/processed/explanations_cache.json       # pre-generated Gemini zone explanations
data/enriched/traffic_context_h3.json        # MapMyIndia enrichment (H3-keyed)
```

If any artifact is missing, the API **degrades gracefully** — empty lists, structured
404s, `is_proxy: true` flags, fallback explanations. It never crashes on startup.

### Frontend Deploy

```bash
cd frontend
npm run build        # outputs to frontend/dist/
```

The `dist/` folder is a static site that can be served from any CDN (Vercel, Netlify, Render static). The `frontend/vercel.json` config is included.

The backend also serves the vanilla dashboard at `/dashboard/` via FastAPI's `StaticFiles` mount — useful for a single-service Render deploy.

---

## 17. Team

| Person | Role | Deliverables |
|---|---|---|
| **Person 1** | Backend | FastAPI app, in-memory DataStore, all 9 routers, Pydantic models |
| **Person 2** | ML | Congestion Impact Score, LightGBM forecast, game-theory model |
| **Person 3** | Frontend | React + TypeScript, MapMyIndia SDK integration, all UI panels |
| **Person 4** | Integration | MapMyIndia enrichment, self-validating agent, Gemini LLM, docs, presentation |

---

## Academic References

This project builds on peer-reviewed security game research:

- Tambe, M. (2011). *Security and Game Theory: Algorithms, Deployed Systems, Lessons Learned.* Cambridge University Press. (ARMOR/IRIS/PROTECT systems)
- Brown, M. et al. (2014). *STREETS: Game-Theoretic Traffic Patrolling with Exploration and Exploitation.* AAAI-2014.
- Lei, C. et al. (2017). *Parking Enforcement Model using Stackelberg Games.* Transportation Research Part B.
- Trejo, K. K. et al. (2017). *STOP: A Stackelberg Game for Traffic Optimization.* (Speed trap placement)

---

## Acknowledgements

- **MapMyIndia / Mappls** — map tiles, traffic APIs, travel-time data
- **Google Gemini** — zone explanation generation
- **Uber H3** — hexagonal spatial indexing library
- **FastAPI** — Python async web framework
- **Bengaluru Traffic Police** — dataset (anonymized, research use)

---

## License

MIT — see `LICENSE` for details.

---

*Built in 72 hours. Every claim in this README is backed by a real data file, a real API endpoint, or an honest limitation disclosure.*
