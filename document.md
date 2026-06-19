# ParkVisionSaathi AI – End‑to‑End Build Guide (Hackathon Edition)

> ⚠️ **CRITICAL: EXTERNAL DATA RESTRICTIONS** ⚠️
>
> **DO NOT use OSMnx, OpenStreetMap road network data, or any external datasets.** The hackathon rules prohibit external datasets. References to OSM in this document (lines ~97, ~118, ~149) are INCORRECT and must be ignored. **Use only:** (1) the provided violation CSV dataset, (2) MapMyIndia/Mappls APIs (Distance Matrix, Reverse Geocode, Nearby, Routing), and (3) Python/JS libraries (H3, pandas, LightGBM, etc.) which are tools, not data.
>
> **For road information:** Use Mappls Reverse Geocode API to get street names. Use Mappls Snap-to-Road API for road geometry. NEVER download road network graphs from OSM.

**Goal:** Build a national‑level, hackathon‑winning prototype that detects parking‑induced congestion hotspots, quantifies their impact on traffic flow using Mappls data, models violator–police interactions using game theory, and optimizes patrol strategies on an interactive map with LLM explanations. [file:1]

---

## 1. Clean System Architecture

Think in **layers** so the team can parallelize and avoid spaghetti:

1. **Data Layer (PostgreSQL + PostGIS):**  
   Stores raw violations, engineered features, risk scores, forecasts, patrol history, road segments, and game‑theory outputs (patrol probabilities, violator adaptation, spillover). [file:1]

2. **ML Layer (Python):**  
   - Hotspot detection (time‑aware DBSCAN). [file:1]  
   - Risk score computation (0–100 proxy for congestion). [file:1]  
   - Forecasting (LightGBM/XGBoost) for violation counts / risk. [file:1]  
   - Game‑theory logic: Stackelberg mixed strategies, expected utility, waterbed effect, Colonel Blotto allocation.

3. **API Layer (FastAPI):**  
   Unified REST API exposing: `/hotspots`, `/risk`, `/forecast`, `/patrol/history`, `/game/*`, `/simulate`, `/heatmap`, `/llm/explain_zone`. JSON schemas defined via Pydantic so frontend can rely on them. [file:1]

4. **Frontend Layer (React + TS + Leaflet):**  
   - India‑centric map dashboard with time slider.  
   - Heatmap overlays for risk and violator adaptation.  
   - Simulation panel for manpower slider and deployment schedule.  
   - LLM side panel for “Explain this zone.” [file:1]

5. **LLM Layer (Gemini / Llama):**  
   No fine‑tuning; use robust prompt engineering with structured JSON context from the backend. [file:1]

6. **DevOps & Collaboration:**  
   Dockerized backend & DB, CI on GitHub Actions, deployed to Render/Fly.io (backend) and Vercel/Netlify (frontend). Git branching with PR reviews. [file:1]

---

## 2. Roles and Collaboration Pattern (4 Personas)

### Persona A – Backend & Data Lead

**Responsibility:** Own the DB schema, ETL, FastAPI implementation, and integration with ML modules.

**Step‑by‑step:**

1. **Day 0: Repo & Base Setup**
   - Create GitHub org/repo `parkvision-saathi`.  
   - Setup folders: `backend/`, `ml/`, `frontend/`, `.github/workflows/`.  
   - Add `docker-compose.yml` with PostgreSQL + PostGIS + Redis + backend. [file:1]  
   - Define `.env.example` with DB credentials and API keys.

2. **Day 1: Schema & Ingestion**
   - Design tables:  
     - `violations` (raw cleaned data: lat, lon, pincode, timestamp, vehicle_type, validation_status, etc.). [file:1]  
     - `zones` (grid IDs, centroid lat/lon, pincode, station_id). [file:1]  
     - `risk_scores` (zone_id, hour, risk_score, components). [file:1]  
     - `forecasts` (zone_id, timestamp, predicted_violation_count, predicted_risk_score). [file:1]  
     - `road_segments` (segment_id, geometry, importance). [file:1]  
     - `patrol_history` (team_id, zone_id/segment_id, start_time, end_time, source).  
     - `game_stackelberg`, `game_violator_adaptation`, `game_spillover`.  
   - Write a Python ETL script to clean the 298k‑row CSV and load into `violations` using `COPY` or `psycopg2`. [file:1]  
   - Build `alembic` migrations for repeatability.

3. **Day 2: FastAPI Implementation**
   - Setup FastAPI project in `backend/app` with routers: `risk.py`, `forecast.py`, `game.py`, `simulate.py`, `llm.py`.  
   - Implement endpoints from the schema file:  
     - `/hotspots`, `/risk`, `/forecast/zones`, `/forecast/stations`. [file:1]  
     - `/patrol/history`, `/enforcement/heat_index`. [file:1]  
     - `/game/stackelberg_strategy`, `/game/violator_adaptation`, `/game/spillover_forecast`.  
     - `POST /simulate` (connect to ML/game‑theory module). [file:1]  
     - `POST /llm/explain_zone` (calls LLM via HTTP client). [file:1]  
   - Enforce `response_model` on each endpoint to auto‑generate OpenAPI docs.

4. **Day 3: Performance, CI/CD, Integration**
   - Add DB indices (zone_id, hour, timestamp) for fast filtering. [file:1]  
   - Add Redis caching for expensive hourly calls (`/risk`, `/heatmap`, `/game/*`). [file:1]  
   - Setup GitHub Actions: run tests, linting, and build Docker on PR.  
   - Deploy backend to Render/Fly.io; configure CORS for frontend domain. [file:1]  
   - Maintain `API_DOCS.md` so frontend and ML have a single source of truth.

**Collaboration Tips:**
- Define Pydantic models early; pin them in a shared `models.py`, so B and C serialize DataFrames to those models and A just `.from_orm`. [file:1]  
- Open PRs early with skeletal endpoints returning mock data so D can start integration.

---

### Persona B – ML: Hotspots, Risk Score, Game‑Theory Analytics

**Responsibility:** Turn raw violations into dynamic, interpretable risk layers, and implement the core game‑theory calculations.

**Step‑by‑step:**

1. **Day 1: Hotspots & Risk Score**
   - Load cleaned data from DB (via SQLAlchemy or `pandas.read_sql`). [file:1]  
   - Implement **time‑aware DBSCAN**: for each hour or time bucket (6–10, 10–16, 16–22), run DBSCAN on lat/lon to detect clusters. [file:1]  
   - For each cluster/grid cell, compute:  
     - Violation density (normalized). [file:1]  
     - Road importance (from OSM highway type mapped to weight). [file:1]  
     - Peak hour weight (multipliers for 8–10 and 17–19). [file:1]  
     - Repeat‑offender weight (frequency in last 7 days). [file:1]  
     - Validation trust (map validation_status to weight and average). [file:1]  
   - Combine to a 0–100 risk score using a weighted sum; label `LOW/MEDIUM/HIGH`. [file:1]  
   - Write results back to `risk_scores` table.

2. **Day 2: Game‑Theory – Stackelberg & Expected Utility**
   - Implement a `stackelberg.py` module:  
     - Take risk scores per zone + patrol history (`last_24h_patrol_count`). [file:1]  
     - Compute baseline weight \(w_i = r_i^\alpha\).  
     - Apply enforcement fatigue: `w_i' = w_i / (1 + λ * patrol_count_yesterday_i)`.  
     - Normalize to `patrol_probability p_i`.  
   - Implement `expected_utility.py`:  
     - For each zone, estimate `time_saved_minutes` (from road importance + peak hour). [file:1]  
     - Estimate `search_time_minutes` for legal parking.  
     - Given `p_i` and `fine_amount`, compute `expected_cost` and `net_benefit`.  
     - Map `net_benefit` to `violator_risk_score` 0–100 via sigmoid.  
   - Store results in `game_stackelberg` and `game_violator_adaptation` tables.

3. **Day 3: Waterbed Effect & Validation**
   - Build a neighbor graph of road segments (via k‑NN on centroids or OSM graph neighbors). [file:1]  
   - Implement `spillover.py`:  
     - Given predicted violations & patrol schedule, reduce violations on patrolled segment by ~20% and increase on 2nd/3rd neighbors by ~10%.  
     - Recompute adjusted risk scores and save to `game_spillover`.  
   - Create a Jupyter notebook showing:  
     - Example of high enforcement in one zone and increased violator risk in adjacent zones.  
     - Before/after spillover maps for a time slice.  
   - Provide short explanations for docs and LLM prompts (e.g., “waterbed effect explanation snippet”).

**Collaboration Tips:**
- Expose B’s logic as functions `compute_risk_scores()`, `compute_stackelberg(hour)`, etc., so A calls them from FastAPI on schedule or cron. [file:1]  
- Coordinate with D to ensure outputs include exactly the fields needed for overlays.

---

### Persona C – ML: Forecasting, Road‑Segment Analytics, Simulation Logic

**Responsibility:** Predict future violations and risk, map to road segments, and encode the Colonel Blotto + Stackelberg logic into deployable functions.

**Step‑by‑step:**

1. **Day 1: Feature Engineering & Baseline Forecast**
   - Pull aggregated time series per zone/station from DB. [file:1]  
   - Engineer features:  
     - Time: hour, day_of_week, month, is_weekend, is_peak, sin/cos for hour/day. [file:1]  
     - Lags: t‑1, t‑24, t‑168, plus rolling means (7, 14, 30 days). [file:1]  
     - Zone metadata: station_id, road importance, vehicle type mix, validation trust. [file:1]  
     - Enforcement heat: `last_24h_patrol_count`, `last_72h_patrol_count`. [file:1]  
   - Train LightGBM/XGBoost for `violation_count` or `risk_score` with time‑based split; evaluate R² and MAE; store best model. [file:1]

2. **Day 2: Road Segments & Simulation Module**
   - Use OSMnx to download road network; build KD‑tree on segment centroids. [file:1]  
   - Map each violation to the nearest road segment; aggregate counts and compute segment‑level risk. [file:1]  
   - Implement `simulation.py`:  
     - Input: `num_teams`, predicted risk per zone/hour, patrol probabilities. [file:1]  
     - Blotto step: allocate fractional teams proportionally to risk. [file:1]  
     - Rounding step: assign integer teams, then greedy merge nearby zones (within 2 km) into single team route. [file:1]  
     - Output: `SimulationResponse` structure with team schedules and uncovered high‑risk zones.

3. **Day 3: Game‑Aware Forecast & Integration**
   - Add enforcement features into model (patrol counts); retrain and compare metrics. [file:1]  
   - Optional: incorporate `expected_cost` or `violator_risk_score` as exogenous variables to capture behavior adaptation.  
   - Finalize Python functions:  
     - `get_zone_forecast(horizon_hours)` for `/forecast/zones`. [file:1]  
     - `get_spillover_forecast(hour, patrolled_segments)` for `/game/spillover_forecast`.  
     - `run_simulation(request: SimulationRequest)` for `/simulate`. [file:1]  
   - Hand over function signatures and outputs to A.

**Collaboration Tips:**
- Commit versioned model files (`models/lightgbm_v1.pkl`) and include a small `MODEL_CARD.md` summarizing training data, metrics, limitations. [file:1]  
- Write simple unit tests for simulation logic (e.g., total teams assigned equals `num_teams`).

---

### Persona D – Frontend, LLM, UX

**Responsibility:** Build a convincing, smooth, and insightful dashboard around the APIs. This is what judges see first.

**Step‑by‑step:**

1. **Day 1: Layout & Core Map**
   - Create React app with TypeScript and Tailwind; configure base routing. [file:1]  
   - Integrate Leaflet + React‑Leaflet, center on Bengaluru / chosen city; later generalize to India. [file:1]  
   - Implement layout:  
     - Left sidebar: stats + LLM chat + simulation controls. [file:1]  
     - Center: map with heatmap overlay and patrol markers.  
     - Bottom: time slider (6–22). [file:1]  
   - Mock data for heatmap and markers; define TypeScript interfaces mirroring Pydantic models from the API schema.

2. **Day 2: Real API Integration & Panels**
   - Wire `GET /heatmap?hour=h&type=risk` to time slider changes, update L.heatLayer. [file:1]  
   - Add toggles:
     - “Risk View” → `/heatmap?hour=h&type=risk`.  
     - “Violator View” → `/heatmap?hour=h&type=violator` or `/game/violator_adaptation`. [file:1]  
   - Simulation panel:
     - Slider `numTeams`.  
     - On change, POST `/simulate` and render team routes on map with color coding by team. [file:1]  
     - Table view: Team vs hour vs zone (Gantt‑style). [file:1]
   - Zone detail on click:
     - Click zone marker or heat cell; fetch `/risk`, `/game/stackelberg_strategy`, `/game/violator_adaptation` for that zone/hour. [file:1]  
     - Display breakdown: risk components, patrol probability, expected cost, violator risk.

3. **Day 3: LLM Explainability & Polish**
   - Implement “Explain this zone” button in the zone panel; POST `/llm/explain_zone` and show response. [file:1]  
   - Use a simple prompt template on the backend to feed into Gemini/Llama. [file:1]  
   - Add small animations/transitions:
     - Smooth map updates on time slider drag. [file:1]  
     - Loading spinners and error toasts for API calls.  
   - Build a high‑impact tour for judges:
     - Step 1: Show morning peak risk heatmap. [file:1]  
     - Step 2: Switch to “Violator View” to show adaptation.  
     - Step 3: Move manpower slider; show how schedule updates and waterbed effect shifts risk. [file:1]  
     - Step 4: Click a zone and ask LLM: “Why here?” [file:1]

**Collaboration Tips:**
- Commit a `frontend/API_TYPES.ts` file that matches backend Pydantic models to avoid drift. [file:1]  
- Use `.env` for `VITE_API_BASE_URL`; keep API base path configurable for staging/prod.

---

## 3. GitHub Workflow & Collaboration

To keep a hackathon‑pace project sane:

1. **Branching Model**
   - `main`: always deployable.  
   - `backend/*`, `ml/*`, `frontend/*` feature branches.  
   - Use PRs with short descriptions, reference issue/ticket numbers.

2. **Issues / Tasks**
   - Create GitHub issues per feature (e.g., “Implement /game/stackelberg_strategy endpoint”).  
   - Label by persona (A/B/C/D) and component (backend, ml, frontend, docs). [file:1]

3. **Code Style & Reviews**
   - Python: `black`, `ruff`; JS: `eslint`, `prettier`.  
   - At least one teammate reviews each PR (fast, high‑level during hackathon).

4. **Continuous Integration**
   - GitHub Actions:  
     - Run tests (pytest), lint, and type‑checks on every PR.  
     - Optionally, auto‑deploy `main` to staging.

5. **Documentation**
   - `README.md`: high‑level overview + quick start (`docker-compose up`). [file:1]  
   - `API_DOCS.md`: endpoint list + JSON examples (you already drafted). [file:1]  
   - `ML_DESIGN.md`: risk score formula, model features, game‑theory logic. [file:1]  
   - `DEMO_SCRIPT.md`: step‑by‑step storyline for the pitch. [file:1]

---

## 4. Dashboard – “Wow” Features to Highlight

To win a national hackathon, don’t just show plots. Show **decisions** and **adaptation**:

1. **Time‑Slider Heatmap with Hotspot Migration**
   - Judges drag 6→9→18 hours and see hotspots shift. [file:1]  
   - Use smooth transitions and prefetch data for nearby hours for responsiveness. [file:1]

2. **Game‑Theory Layers**
   - Toggle for “Patrol Strategy (Stackelberg)” overlays patrol probabilities as circle sizes. [file:1]  
   - Toggle for “Violator Adaptation” with an alternate color ramp to show where offenders are likely to move. [file:1]  
   - Optional arrows or thin lines connecting patrolled segments to spillover neighbors.

3. **Simulation & Manpower Panel**
   - Slider for patrol teams; map and table update live. [file:1]  
   - Highlight uncovered high‑risk zones to show resource gaps. [file:1]  
   - Use different colors per team; maybe animate movement between zones across hours.

4. **LLM Explainability**
   - Click a zone → “Why is this zone risky, and where will drivers go if we enforce here?” → instant narrative. [file:1]  
   - Emphasize you are using LLMs responsibly for explainability, not blindly.

5. **Road‑Segment Analytics**
   - Switch view from area heatmap to road‑segment risk lines (polyline colored by risk). [file:1]  
   - Show enforcement scenario: click a segment, mark it as patrolled, and display spillover forecast for neighbors.

6. **Honest Limitations & Impact**
   - Clear note in UI or docs: “Risk score is a proxy for congestion; no ground‑truth speed data.” [file:1]  
   - Explain real‑world impact: fewer illegal parks, smoother traffic, better deployment of limited police resources. [file:1]

---

## 5. Implementation Flow (End‑to‑End)

If you put it all together, the chronological “movie” of the project looks like this:

1. **Data → Zones & Risk:**
   - Ingest violations → grid them into zones → run DBSCAN → compute risk score 0–100. [file:1]

2. **Risk → Forecast:**
   - Use time series ML to forecast future violation counts and risk per zone/hour, including enforcement history as features. [file:1]

3. **Forecast + Game Theory → Strategy:**
   - Apply Stackelberg to generate probabilistic patrol strategies.  
   - Compute violator expected utility and adaptation map.  
   - Apply waterbed effect to adjust forecasts under enforcement scenarios.

4. **Strategy → Simulation & Schedule:**
   - Use Colonel Blotto logic to allocate limited patrol teams proportionally to risk and probabilities. [file:1]  
   - Optimize routes with a greedy, distance‑aware algorithm.

5. **Backend → API:**
   - Wrap all of this in clean FastAPI endpoints with stable schemas. [file:1]

6. **API → Dashboard & LLM:**
   - React/Leaflet dashboard consumes these APIs to show heatmaps, patrol strategies, and simulation results. [file:1]  
   - LLM explains risk and strategy narratives for human decision‑makers.

---

If you share your rough internal timeline (how many actual days/hours you have before the hackathon), the next thing that would help most is a **task breakdown by day** with explicit GitHub issues you can copy‑paste—would you like that next?  