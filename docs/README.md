# ParkVision-Saathi 🚦

> **Quantify. Predict. Optimize.** — A data-driven parking enforcement intelligence system for Bengaluru Traffic Police.

Built in 3 days at a hackathon by a 4-person BTech CSE team.

---

## What It Does

Illegal parking causes an estimated **34+ lane-hours of blockage per day** at Bengaluru's worst zones — but police have no system to see *which* violations actually choke traffic vs. which are low-impact.

ParkVision-Saathi solves three problems:

| Pillar | Problem | Our Answer |
|---|---|---|
| **QUANTIFY** | Which violations actually hurt traffic flow? | 6-factor Congestion Impact Score (0–100) per zone per hour |
| **PREDICT** | Where will tomorrow's hotspots be? | LightGBM + CatBoost ensemble forecasting |
| **OPTIMIZE** | Where should patrol teams go? | Stackelberg game theory + spillover simulation |

---

## Key Features

- **Two-Layer Map Toggle** — Violation Density vs. Congestion Risk Impact (they're not the same map)
- **Congestion Impact Score** — 6 weighted components including MapMyIndia real-time travel time validation
- **LLM Zone Explanations** — Gemini 2.5 Flash explains each zone in plain language for field officers
- **Team Allocation Simulator** — Drag a slider (1–15 teams), see coverage % and spillover in real time
- **Waterbed Effect Visualisation** — Where violations migrate when one zone is enforced
- **MapMyIndia Enrichment** — Real travel time ratios for top-20 hotspots, validated against model scores

---

## Architecture

```
Frontend (Vite + React + TypeScript, port 5173)
    ↕ REST API
Backend (FastAPI + uvicorn, port 8000)
    ↕ In-memory DataStore (pandas, no DB)
ML Pipeline
    ├── Congestion Impact Score  (ml/congestion/impact_score.py)
    ├── Forecasting              (LightGBM + CatBoost ensemble)
    ├── Game Theory              (Stackelberg + Spillover)
    └── LLM Explanations         (Gemini 2.5 Flash, cache-first)
Data
    ├── 298,450 violation records (Nov 2023 – Apr 2024)
    ├── MapMyIndia enrichment    (Distance Matrix + Nearby API)
    └── H3 grid resolution 9     (hexagonal spatial indexing)
Maps: MapMyIndia SDK (vector tiles, traffic layer, heatmap)
```

**Constraints followed:**
- ✅ No OpenStreetMap / OSMnx
- ✅ No PostgreSQL / Redis / Docker
- ✅ JSON files + in-memory pandas only
- ✅ MapMyIndia APIs exclusively for maps and traffic

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- API keys in `.env` (see below)

### Setup

```bash
# Clone
git clone https://github.com/Shweta-nasc/Park-Vision-sathi
cd Park-Vision-sathi

# Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Environment variables
cp .env.example .env
# Fill in MAPPLS_STATIC_KEY and GEMINI_API_KEY
```

### Run Backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
# API docs: http://localhost:8000/docs
```

### Run Frontend

```bash
cd frontend
npm install
npm run dev
# Opens: http://localhost:5173
```

### Pre-generate LLM Explanations (recommended before demo)

```bash
source venv/bin/activate
python ml/llm/generate_explanations.py --limit 20
# Generates Gemini explanations for top-20 zones → cached for instant demo serving
```

---

## Environment Variables

Create a `.env` file in the project root:

```env
MAPPLS_STATIC_KEY=your_mappls_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

Get your keys:
- **MapMyIndia/Mappls:** https://about.mappls.com/api/
- **Gemini:** https://ai.google.dev/gemini-api/docs

---

## Project Structure

```
Park-Vision-sathi/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI app with CORS
│       ├── models.py            # Pydantic schemas
│       └── routers/             # heatmap, risk, forecast, game, simulate, explain, traffic
├── frontend/
│   └── src/
│       ├── components/          # MapView, StatsPanel, LayerToggle, SimulationPanel...
│       └── api/client.ts        # Typed API client
├── ml/
│   ├── congestion/
│   │   └── impact_score.py      # 6-factor Congestion Impact Score
│   ├── enrichment/
│   │   ├── mapmyindia.py        # MapMyIndia Distance Matrix enrichment
│   │   └── test_mapmyindia.py   # API smoke tests
│   ├── forecast/
│   │   ├── feature_engineering.py
│   │   └── train_model.py       # LightGBM + CatBoost
│   ├── game/
│   │   ├── stackelberg.py       # Patrol allocation game theory
│   │   ├── spillover.py         # Waterbed effect simulation
│   │   └── expected_utility.py  # Violator rational choice model
│   └── llm/
│       ├── prompts.py           # Grounded Gemini prompt templates
│       ├── gemini_client.py     # Cache-first Gemini client
│       └── generate_explanations.py  # Batch pre-warmer
├── data/
│   ├── mock/                    # Mock API responses (13 files, for frontend dev)
│   ├── enriched/
│   │   └── traffic_context.json # Real Mappls travel time data for 15 hotspot zones
│   └── processed/
│       └── explanations_cache.json  # Pre-generated Gemini zone explanations
├── docs/
│   ├── presentation_outline.md  # 8-slide structure with speaker beats
│   ├── DEMO_SCRIPT.md           # Word-for-word demo script
│   └── JUDGE_QA.md              # 5 scripted judge attack responses
└── requirements.txt
```

---

## The Congestion Impact Score

The core formula — a 6-component weighted score (0–100):

```python
score = (
    0.30 * lane_blockage_component        +  # double parking, main-road parking
    0.25 * intersection_impact_component  +  # junction approach violations
    0.25 * traffic_degradation_component  +  # MapMyIndia travel_time_ratio
    0.10 * access_blockage_component      +  # bus stops, hospitals, schools
    0.10 * vehicle_size_component            # heavy vehicle obstruction
)
```

| Band | Score | Meaning |
|---|---|---|
| CRITICAL | 76–100 | Immediate enforcement required |
| SEVERE | 51–75 | Prioritise in next patrol cycle |
| MODERATE | 26–50 | Routine coverage |
| MINIMAL | 0–25 | Monitor only |

**External validation:** MapMyIndia Distance Matrix API provides real travel-time ratios.
City Market Circle measures **1.31x** — and the self-validating agent calibrates its raw 85.3 score down to 72.1 accordingly. Violation density is not congestion impact, and the agent proves it against live data.

---

## Game Theory Model

Stackelberg patrol allocation — police as "leader", violators as rational "followers":

1. **Patrol Probability** = risk score^α / Σ(all risk scores^α), where α=1.5 emphasises high-risk zones
2. **Violator Utility** = (1 - patrol_prob) × time_saved_value - patrol_prob × fine_amount
3. **Spillover** = when zone A is enforced, displaced violations flow to H3 k-ring neighbours (conservation law)

---

## Data

| Field | Value |
|---|---|
| Total records | 298,450 |
| Time range | Nov 2023 – Apr 2024 (151 days) |
| Geography | Bengaluru only |
| Top station | Upparpet (29,808 records, 10%) |
| Top junction | Safina Plaza (15,449 records, 5.2%) |
| Top pincode | 560009 — Gandhi Nagar (11.1%) |
| Spatial grid | H3 resolution 9 (~174m hexagons) |

**Known limitations (we document these openly):**
- Temporal patterns reflect enforcement shift schedules, not raw parking behaviour
- `validation_status` is missing for 42% of records (Feb–Apr 2024 mostly unvalidated)
- No ground-truth traffic speed data — Congestion Impact is a *proxy score*, not a measured value

---

## Team

| Person | Role |
|---|---|
| Person 1 | Backend Lead — FastAPI, DataStore, API endpoints |
| Person 2 | ML Lead — ETL, Congestion Score, LightGBM/CatBoost, Game Theory |
| Person 3 | Frontend Lead — Vite/React, MapMyIndia SDK, UI/UX |
| Person 4 | Integration Lead — LLM, Enrichment, Docs, Presentation |

---

## Acknowledgements

- **MapMyIndia / Mappls** — Maps, routing, and traffic APIs
- **Google Gemini** — Zone explanation generation
- **Uber H3** — Hexagonal spatial indexing
- **LightGBM / CatBoost** — Gradient boosting frameworks
- **FastAPI** — Backend framework
