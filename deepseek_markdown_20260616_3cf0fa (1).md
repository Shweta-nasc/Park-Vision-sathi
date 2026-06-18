---
title: "ParkVision AI – Complete 4‑Day Implementation Plan"
subtitle: "Predict parking‑induced congestion before it happens"
author: "Team of 4 | Deadline: 21 June 2026"
date: "June 2026"
geometry: margin=1in
fontsize: 11pt
linestretch: 1.2
---

\newpage

# 1. Project Overview

**ParkVision AI** is a predictive enforcement platform that analyses 298,450 parking‑violation records from Bengaluru to:

- Detect illegal‑parking hotspots (time‑aware DBSCAN clustering)
- Compute a **Congestion Risk Score** (0–100) based on density, road importance, peak‑hour weighting, repeat‑offender frequency, and validation trust
- Forecast future violations per police station (LightGBM/XGBoost)
- Suggest **patrol routes** and **resource allocation** with a manpower simulation module
- Provide an interactive dashboard with a **time‑slider heatmap** (hotspot migration through the day)
- Explain risk factors via an **LLM chat** (Gemini/Llama)
- Map violations to **OpenStreetMap road segments** for precision

**Key differentiators** (to impress judges):

- Risk score > raw counts
- Time‑dimension clustering
- `validation_status` as a trust signal
- Predictive ML with reported metrics (R², MAE)
- Dynamic heatmap slider
- AI patrol recommendations
- LLM explainability
- Road‑segment analytics
- Manpower simulation

**Honest limitation:** We lack ground‑truth traffic data; we predict a defensible **congestion proxy** – this will be stated clearly in the documentation.

---

# 2. Team Division (4 Persons, 4 Days)

| Person | Role | Primary Responsibilities |
|--------|------|---------------------------|
| **A** | Backend & Data Lead | Data cleaning, PostgreSQL+PostGIS schema, FastAPI endpoints, Docker, integration of all ML modules. |
| **B** | ML – Hotspot & Risk | DBSCAN clustering, risk‑score formula, temporal segmentation, qualitative validation against known junctions. |
| **C** | ML – Forecasting & Roads | LightGBM/XGBoost time‑series forecasting, OSMnx road network, violation‑to‑road mapping, patrol suggestion generation, simulation logic. |
| **D** | Frontend & LLM / Simulation | React+Leaflet dashboard, time‑slider heatmap, LLM (Gemini/Llama) integration, manpower simulation UI, end‑to‑end demo. |

**Integration:** Person A owns the API and coordinates with B, C, D to expose all model outputs as endpoints.

---

# 3. Day‑by‑Day Detailed Tasks

## Day 1 – Foundation & Data Preparation

| Person | Tasks |
|--------|-------|
| **A** | – Set up Git repo, Docker Compose with PostgreSQL+PostGIS, Redis.<br> – Plan data cleaning: parse multi‑label `violation_type`, fix timestamps, handle null `closed_datetime`, drop invalid coordinates (lat/lon outside Bengaluru).<br> – Design DB schema: tables `violations`, `hotspots`, `risk_scores`, `forecasts`, `patrol_suggestions`, `road_segments`.<br> – Write a script to load the cleaned CSV into the DB.<br> – Start a FastAPI app with health check and skeleton for `/violations`. |
| **B** | – Explore dataset: distribution of violation types, stations, time patterns.<br> – Implement prototype DBSCAN on a 10k sample to estimate `eps` and `min_samples`.<br> – Design the risk‑score formula: components (density, road importance, peak‑hour weight, repeat‑offender, validation).<br> – Prepare a notebook for validation against known junctions (Koramangala, MG Road, Silk Board, etc.). |
| **C** | – Extract time features (hour, day_of_week, month, is_weekend, is_peak).<br> – Build a baseline forecasting model (rolling averages) to benchmark.<br> – Download OSM road network for Bengaluru using OSMnx (or use a cached file).<br> – Plan spatial join: map violation points to nearest road segment. |
| **D** | – Set up React project with TypeScript, Tailwind, Leaflet.<br> – Create a base map centred on Bengaluru.<br> – Design dashboard layout: left panel (stats/chat/patrol), main map, time slider at bottom, legend top‑right.<br> – Mock static data for map rendering. |

**End‑of‑Day 1:** Repository with backend skeleton, DB schema, sample data loaded; preliminary DBSCAN results; OSM data downloaded; frontend skeleton with static map.

---

## Day 2 – Core ML & Backend APIs

| Person | Tasks |
|--------|-------|
| **A** | – Finalise DB schema and load all 298k records.<br> – Implement FastAPI endpoints: `/hotspots`, `/risk-score`, `/forecast/{station}`, `/patrol`.<br> – Add Redis caching for frequently queried data (e.g., hotspots per hour).<br> – Write API documentation (OpenAPI) and test with Postman.<br> – Dockerize the backend. |
| **B** | – Run DBSCAN on the full dataset **with time‑aware segmentation** (cluster per hour or per time bucket: 6‑10, 10‑16, 16‑22).<br> – Compute cluster centroids, sizes, average severity, top violation type.<br> – Validate clusters against known junctions (distance <3 km = valid).<br> – Implement the risk‑score function on each cluster/grid cell: combine density, road importance, peak‑hour weight, repeat‑offender, validation trust.<br> – Output a table of zones with risk scores (0–100) and levels (Low/Medium/High). |
| **C** | – Finalise feature engineering for forecasting: lag features (1,2,3,7,14 days), rolling means, cyclical encoding (sin/cos for hour/day).<br> – Train LightGBM and XGBoost on historical data (time‑based split).<br> – Evaluate R² and MAE; choose the best or ensemble.<br> – Map violations to road segments using a KD‑tree on OSM centroids.<br> – Aggregate violations per road segment and compute segment‑level risk.<br> – Generate initial patrol suggestions from top‑risk segments with peak time. |
| **D** | – Implement the main map component, fetching hotspots/risk zones from the API.<br> – Build the time slider (6 AM – 10 PM) that filters displayed data by hour.<br> – Create legend and risk‑colour mapping.<br> – Start the “Statistics Dashboard” panel (total violations, top stations, violation types).<br> – Begin the Patrol Recommendation panel (list of suggestions with priority). |

**End‑of‑Day 2:** All models (DBSCAN, RiskScore, Forecast) are trained and saved; endpoints are live; frontend can fetch and display hotspots & risk zones (static time). Road‑segment aggregation done. Patrol suggestions generated.

---

## Day 3 – Integration, Time Heatmap, LLM & Simulation

| Person | Tasks |
|--------|-------|
| **A** | – Connect all endpoints to actual model outputs (load models, query DB).<br> – Add `/simulate` endpoint that takes manpower count and returns optimal deployment plan.<br> – Write integration tests.<br> – Deploy backend to Render/Fly.io.<br> – Ensure CORS configuration for frontend. |
| **B** | – Assist A in making risk‑score endpoint time‑sensitive (filter by hour).<br> – Provide a function to compute risk for a given (lat, lon, hour).<br> – Create a “heatmap data” endpoint returning grid density for the selected hour (to be used by `L.heatLayer`).<br> – Document the risk‑score formula and validation results. |
| **C** | – Expose forecast data per station for next 48 hours.<br> – Integrate OSM road‑importance into risk endpoint.<br> – Enhance patrol suggestions with estimated team size.<br> – Implement the simulation algorithm: given N teams, assign them to the top‑N risk zones at their peak hour, minimising travel distance (greedy).<br> – Document forecasting metrics and road‑segment analytics. |
| **D** | – **Implement dynamic time‑slider heatmap:** on slider change, fetch new heatmap data from the API and update `L.heatLayer`.<br> – **Complete LLM Explainability:** integrate Gemini API (or local Llama) – when a zone is selected, pass its risk factors as context and allow natural‑language questions.<br> – **Build the Simulation Panel:** a slider to choose number of patrol teams (1‑10) and display the recommended assignment (zone, time, team). Show a Gantt‑like schedule or map markers.<br> – Polish UI: responsiveness, loading states, error handling. |

**End‑of‑Day 3:** End‑to‑end integration works: frontend fetches live data; heatmap updates with time slider; LLM responds to zone queries; simulation panel shows deployment plans. Backend deployed to cloud.

---

## Day 4 – Final Polish, Testing, and Demo Preparation

| Person | Tasks |
|--------|-------|
| **A** | – Performance tuning: add database indexes, optimise queries.<br> – Set up a CI/CD pipeline (GitHub Actions) for automated deployment.<br> – Write a comprehensive README with setup instructions.<br> – Prepare deployment logs and monitoring. |
| **B** | – Create a validation notebook comparing predicted hotspots with known trouble spots.<br> – Document risk‑score logic with a sample calculation.<br> – Provide qualitative analysis (e.g., “MG Road high risk at 6‑10 AM due to office traffic”). |
| **C** | – Generate final forecast metrics (R², MAE) and include in documentation.<br> – Prepare a map visual of road‑segment risk (using Folium or QGIS).<br> – Write a short description of the simulation algorithm (greedy assignment). |
| **D** | – Record a **3‑minute demo video** showing the dashboard, time slider, LLM interaction, and simulation.<br> – Prepare the final **pitch deck** (slides: problem, solution, differentiators, architecture, limitations, impact).<br> – Perform a dry‑run with the team.<br> – Deploy frontend on Vercel/Netlify. |

**End‑of‑Day 4:** Fully deployed system, demo video, pitch deck finalised, team rehearsed.

---

# 4. System Architecture – Mind Map
ParkVision AI
├── Data Layer
│ ├── CSV ingestion (298k rows)
│ ├── Cleaning & Feature Engineering
│ └── PostgreSQL+PostGIS
├── ML Pipeline
│ ├── Hotspot Detection (DBSCAN)
│ │ └── Time‑aware clustering (per hour)
│ ├── Risk Score Calculation
│ │ ├── Violation Density (KDE)
│ │ ├── Road Importance (OSM)
│ │ ├── Peak‑hour Weight (time)
│ │ ├── Repeat‑offender Weight
│ │ └── Validation Trust (validation_status)
│ ├── Forecasting (LightGBM/XGBoost)
│ │ ├── Time features & lags
│ │ └── Ensemble / best model
│ └── Road‑Segment Analytics
│ ├── OSMnx download
│ └── Spatial join & aggregation
├── Backend API (FastAPI)
│ ├── Endpoints: /violations, /hotspots, /risk‑score, /forecast, /patrol, /simulate
│ └── Caching (Redis)
├── Frontend (React+Leaflet)
│ ├── Interactive map (zones, hotspots, roads)
│ ├── Time slider (6‑22)
│ ├── Dynamic heatmap overlay
│ ├── Patrol suggestion panel
│ ├── LLM chat (Gemini)
│ └── Simulation panel (manpower slider, schedule)
└── Deployment
├── Docker Compose (dev)
└── Cloud (Render / Vercel)



---

# 5. ML Pipeline – Detailed Steps

1. **Feature Engineering**  
   - Temporal: `hour`, `day_of_week`, `month`, `is_weekend`, `is_peak`, cyclical transforms (sin/cos).  
   - Spatial: lat/lon scaled for DBSCAN.  
   - Categorical: police_station, junction, vehicle_type → label‑encoded.  
   - Derived: `severity_score` (from violation type), `validation_weight` (mapped from validation_status).

2. **Hotspot Detection (Unsupervised)**  
   - Use DBSCAN on (lat, lon) separately for each hour.  
   - Output cluster centroids, sizes, average severity, peak hour, top violation type.  
   - Validate against known junctions (distance <3 km).

3. **Risk Score (Heuristic + Data)**  
   - Weighted sum of normalised components:  
     - **Violation density** (Kernel Density Estimation)  
     - **Road importance** (OSM highway type, higher for primary/trunk)  
     - **Peak‑hour weight** (pre‑defined multipliers for 8‑10 AM, 5‑7 PM)  
     - **Repeat‑offender weight** (frequency per location)  
     - **Validation trust** (approved=1.0, processing=0.5, duplicate=0.3, rejected=0.1)  
   - Scale to 0–100 and assign risk level.

4. **Forecasting (Supervised)**  
   - Target: violation count per police station per hour.  
   - Features: time features, lagged counts (1,2,3,7,14 days), rolling averages (7,14,30 days).  
   - Models: LightGBM and XGBoost with time‑series cross‑validation.  
   - Evaluate R² and MAE; use the better or an ensemble.  
   - Predict next 48 hours.

5. **Road‑Segment Analytics**  
   - Download OSM graph via OSMnx.  
   - For each violation, find nearest road segment using a KD‑tree.  
   - Aggregate violations per segment, compute segment‑level risk.  
   - Generate patrol suggestions: sort by risk, assign peak hour.

6. **Simulation (Resource Allocation)**  
   - Input: N patrol teams.  
   - For each hour, select top‑N risk zones/segments with highest risk at that hour.  
   - If zones are close, a team can cover multiple.  
   - Output a schedule: which team goes where and when.

---

# 6. Extra Notes & Important Considerations

## 6.1 Honest Limitations
- No ground‑truth traffic speed/delay data → risk score is a *proxy* for congestion impact.  
- Forecasting accuracy is limited by available historical data.  
- OSM road importance is static; real‑time changes not considered.

## 6.2 Using `validation_status` as a Trust Signal
- Approved records get full weight; rejected/duplicate records are down‑weighted.  
- This adds a unique layer that most teams ignore.

## 6.3 Time‑Based Heatmap
- The map updates **on slider drag** by fetching new data for the selected hour.  
- Use `L.heatLayer` with intensity = risk_score or violation density.  
- Pre‑fetch all hours for smooth transitions.

## 6.4 Simulation – Manpower Management (Detailed)
- Greedy algorithm:  
  1. For each hour, list all zones with risk > 70.  
  2. Sort by risk descending.  
  3. Assign teams to the top zones; if two zones are within 2 km, one team can handle both.  
  4. Output a table: “Team 1 → Zone A at 9 AM; Team 2 → Zone B at 10 AM”.  
- In the UI, show this as a schedule or animated map.

## 6.5 LLM Explainability – What to Fine‑Tune?
- **Do not fine‑tune** – no time and no labeled dataset.  
- Use **prompt engineering** with Gemini API (or Llama 3 via Ollama).  
- Provide a structured context (zone risk factors) and ask for a plain‑language explanation.  
- Use few‑shot examples to guide the model.

## 6.6 Integration Checklist
- Define shared data models (Pydantic) for all API responses.  
- Frontend expects JSON fields: `zone_id`, `risk_score`, `latitude`, `longitude`, `hour`, `violation_count`, etc.  
- All ML modules return pandas DataFrames; Person A converts to JSON.  
- Use environment variables for API keys and DB credentials.

## 6.7 Deployment Tips
- Docker for consistency.  
- Backend to Render/Fly.io (free tier).  
- Frontend to Vercel/Netlify (free).  
- Redis can be in‑memory or a cloud service.

---

# 7. Simulation – Detailed Description

**Purpose:** Demonstrate operational resource allocation.

**Input:**  
- Number of patrol teams (N, e.g., 1‑10).  
- Current date/time (or user‑selectable).  
- Forecasted risk zones for the next 24 hours.

**Logic:**  
1. For each hour, select up to N zones with highest predicted risk.  
2. If a zone is high‑risk for consecutive hours, assign the same team to that zone to minimise movement.  
3. Output each team’s schedule.

**UI Representation:**  
- A slider to choose N.  
- A table listing each team’s assigned zones and times.  
- Map markers showing planned patrol routes with time labels.  
- Optionally, highlight uncovered high‑risk zones to show resource gaps.

**Why it impresses:** It shows you are thinking about **actionable deployment**, not just analytics.

---

# 8. Final Deliverables Checklist

| Person | Deliverables |
|--------|--------------|
| **A** | – Cleaned dataset in DB, FastAPI deployed with all endpoints.<br> – Docker Compose file.<br> – API documentation (OpenAPI). |
| **B** | – DBSCAN cluster outputs (CSV/JSON) and risk‑score tables.<br> – Validation report against known junctions.<br> – Risk‑score formula explanation. |
| **C** | – Trained forecasting model (pickle) with metrics.<br> – Road‑segment risk aggregation (GeoJSON).<br> – Patrol suggestion algorithm and simulation logic. |
| **D** | – Deployed frontend with all features (map, time slider, LLM, simulation).<br> – Demo video (3‑5 min).<br> – Pitch deck slides. |

---

# 9. Advice for the Team

- **Communicate daily** – use Slack/Discord; update each other on API changes.  
- **Focus on “wow” factors** – time‑slider heatmap, LLM chat, and simulation are the judges’ highlights.  
- **Be honest about limitations** – it builds credibility.  
- **Practice the demo** – ensure no broken links, API timeouts, or UI glitches.  
- **Connect everything to real‑world impact** – faster response times, reduced congestion, safer roads.

---

*This document provides the complete blueprint for building ParkVision AI within 4 days. Follow the tasks diligently, and you will have a compelling, fully‑functional prototype ready for the 21 June 2026 deadline.*