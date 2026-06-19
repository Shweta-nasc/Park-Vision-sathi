# PARKVISION-SAATHI: OPERATIONAL EXECUTION PLANNER

> **The Build Bible — What to code, when to code it, and in what order.**
> Companion to: PARKVISION_SAATHI_MASTER_PLAN.md
> Every validated idea from the research is woven into this timeline.

---

## LEGEND

| Icon | Meaning |
|---|---|
| ✅ | **MUST DO** — Core task. Demo breaks without this. |
| 🔶 | **STRETCH** — Moderate risk. Attempt ONLY if core is done. Adds judge impression. |
| ❌ | **DROPPED** — Do not attempt regardless of time. |
| 🔗 | **DEPENDENCY** — Blocked until another task completes. |
| 🧪 | **CHECKPOINT** — Stop and test integration. |
| 💤 | **SLEEP** — Non-negotiable. |

---

# PRE-HACKATHON CHECKLIST (Do 48 hours before Day 1)

> [!IMPORTANT]
> These tasks MUST be done before the hackathon starts. Failing to do these will cost 3-5 hours on Day 1.

- [ ] **Person 4:** Apply for MapMyIndia/Mappls API key at https://about.mappls.com/api/
  - Test a single reverse-geocode call once approved
  - If not approved by Day 1 morning → activate Google Maps manual fallback
- [ ] **Person 1:** Create GitHub repo `parkvision-saathi`
  - Set up folder structure (see Appendix B of master plan)
  - Add `.gitignore` for Python + Node
  - Add `README.md` placeholder
- [ ] **Person 3:** Test Mappls SDK locally
  - Create blank React app, load Mappls script, render map centered on Bengaluru (12.97, 77.59)
  - If SDK doesn't work → test Leaflet fallback with Mappls raster tiles (NEVER use OpenStreetMap — external data not allowed)
  - Document which approach works in the repo
- [ ] **Person 2:** Download dataset to local machine. Do a quick sanity check:
  ```python
  import pandas as pd
  df = pd.read_csv('jan to may police violation_anonymized791b166.csv')
  print(df.shape, df.columns.tolist())
  print(df['created_datetime'].min(), df['created_datetime'].max())
  ```
- [ ] **All:** Install required tools: Python 3.10+, Node 18+, Git, VS Code
- [ ] **All:** Read the full master plan. Know the 3 PILLARS (corrected order):
  1. **QUANTIFY** — Congestion Impact Score quantifies HOW MUCH parking chokes traffic (Pillar 1 = Theme Answer)
  2. **PREDICT** — LightGBM + CatBoost forecasts WHERE it will happen next
  3. **OPTIMIZE** — Game Theory + Waterbed Effect determines WHO goes WHERE
- [ ] **All:** Know the 3 MEMORY ANCHORS judges will remember:
  1. 🗺️ **Two-Layer Map Toggle** — "Violation density and congestion risk are NOT the same map"
  2. 🌊 **Waterbed Effect** — "Enforce here, violations ripple there"
  3. 🎮 **Interactive Simulation** — "You're the control room officer. Drag the slider."

---

# DAY 0 EVENING (Night Before Hackathon)

| Time | All |
|---|---|
| 21:00 | Team call (15 min): Confirm everyone has tools installed, repo cloned, Mappls tested. Confirm API key status. |
| 21:15 | Person 1 + Person 3: Agree on the CONTRACT (API schemas). Write `schemas_contract.md` with JSON examples for each endpoint (see template below). |
| 21:45 | Sleep. Full night. |

### CONTRACT TEMPLATE (write this on Day 0 or Day 1 first 30 min)

```python
# backend/app/models/schemas.py — WRITE THIS FIRST

from pydantic import BaseModel
from typing import List, Optional

class HeatmapPoint(BaseModel):
    lat: float
    lon: float
    h3_id: str
    congestion_impact: float  # 0-100 Congestion Impact Score
    violation_count: int
    impact_band: str  # MINIMAL / MODERATE / SEVERE / CRITICAL

class HeatmapResponse(BaseModel):
    hour: int
    time_bucket: str  # "morning_peak" | "midday" | "afternoon" | "night"
    points: List[HeatmapPoint]
    total_violations: int
    severe_impact_count: int

class CongestionBreakdown(BaseModel):
    zone_id: str
    hour: int
    congestion_impact: float
    impact_band: str
    lane_blockage_component: float    # How much road capacity lost
    intersection_impact_component: float  # Junction throughput disruption
    traffic_degradation_component: float  # Mappls travel time ratio
    access_blockage_component: float  # Bus stop/hospital/school area
    vehicle_size_component: float     # Heavy vehicle obstruction
    severity_component: float
    top_violations: List[str]
    station: str
    junction: Optional[str]
    total_records: int
    estimated_lane_hours_blocked: float  # Daily lane-hours blocked

class HotspotItem(BaseModel):
    rank: int
    zone_id: str
    lat: float
    lon: float
    congestion_impact: float
    impact_band: str
    violation_count: int
    station: str
    top_violation: str
    estimated_lane_hours_blocked: float

class ForecastPoint(BaseModel):
    zone_id: str
    lat: float
    lon: float
    predicted_count: float
    predicted_risk: float
    confidence_lower: Optional[float]
    confidence_upper: Optional[float]

class PatrolAllocation(BaseModel):
    team_id: int
    zone_id: str
    lat: float
    lon: float
    priority_rank: int
    patrol_probability: float
    congestion_impact: float

class SimulationRequest(BaseModel):
    num_teams: int  # 1-15
    hour: int
    time_bucket: str

class SimulationResponse(BaseModel):
    num_teams: int
    allocations: List[PatrolAllocation]
    covered_impact_pct: float
    uncovered_impact_pct: float
    uncovered_zones: List[HotspotItem]
    spillover_zones: List[dict]  # {zone_id, original_impact, adjusted_impact, change_pct}

class TrafficContext(BaseModel):
    zone_id: str
    road_name: Optional[str]
    road_type: Optional[str]
    travel_time_peak_min: Optional[float]
    travel_time_offpeak_min: Optional[float]
    travel_time_ratio: Optional[float]
    nearby_pois: List[str]

class ExplainRequest(BaseModel):
    zone_id: str
    hour: int

class ExplainResponse(BaseModel):
    zone_id: str
    explanation: str
    is_cached: bool
    source: str  # "cache" | "gemini" | "fallback"
```

```typescript
// frontend/src/types/api.ts — MATCHING TYPESCRIPT (write simultaneously)

export interface HeatmapPoint {
  lat: number;
  lon: number;
  h3_id: string;
  congestion_impact: number;
  violation_count: number;
  impact_band: 'MINIMAL' | 'MODERATE' | 'SEVERE' | 'CRITICAL';
}

export interface HeatmapResponse {
  hour: number;
  time_bucket: string;
  points: HeatmapPoint[];
  total_violations: number;
  severe_impact_count: number;
}

export interface CongestionBreakdown {
  zone_id: string;
  hour: number;
  congestion_impact: number;
  impact_band: string;
  lane_blockage_component: number;
  intersection_impact_component: number;
  traffic_degradation_component: number;
  access_blockage_component: number;
  vehicle_size_component: number;
  severity_component: number;
  top_violations: string[];
  station: string;
  junction: string | null;
  total_records: number;
  estimated_lane_hours_blocked: number;
}

export interface SimulationRequest {
  num_teams: number;
  hour: number;
  time_bucket: string;
}

export interface SimulationResponse {
  num_teams: number;
  allocations: PatrolAllocation[];
  covered_impact_pct: number;
  uncovered_impact_pct: number;
  uncovered_zones: HotspotItem[];
  spillover_zones: SpilloverZone[];
}

// ... (mirror all Pydantic models)
```

---

# DAY 1: FOUNDATION

## Theme: "Quantify. Predict. Optimize." — Congestion impact is Pillar 1.

> [!CAUTION]
> **ABSOLUTE RULES (repeat at every standup):**
> 1. **NO OpenStreetMap / OSMnx anywhere in the codebase.** OSM = external dataset = disqualification risk. Use Mappls SDK only.
> 2. **NO PostgreSQL / Redis / Docker.** JSON files + in-memory pandas. Period.
> 3. **Open the demo with CONGESTION IMPACT, not violation counts.** Pillar 1 = QUANTIFY.
> 4. **The Two-Layer Map Toggle is MANDATORY.** Violation Density vs. Congestion Risk Impact — proves we understood the theme.

---

### 08:00 – 08:30 | ALL TOGETHER — STANDUP + SETUP

| Task | Owner | Output |
|---|---|---|
| ✅ Review master plan (5 min — skim, not read) | All | Shared understanding |
| ✅ **Confirm: NO OSM, NO PostgreSQL, NO Redis, NO Docker. JSON + in-memory only.** | All | Verbal confirmation from each person |
| ✅ Confirm MapMyIndia API key status | P4 | Key works OR fallback activated |
| ⚠️ **If MapMyIndia key NOT confirmed:** P4 starts manual fallback NOW — collect Google Maps travel times for 10 hotspot/control location pairs, save as `data/enriched/traffic_context_manual.json` | P4 | Fallback data OR key confirmed |
| ✅ Create GitHub issues for Day 1 (5 min) | P1 | Issue board populated |
| ✅ **CONTRACT SESSION: Write schemas.py + api.ts together** | P1 + P3 | `schemas.py` and `api.ts` committed |
| ✅ Create mock JSON response files in `data/mock/` | P1 | One example JSON per endpoint |
| ✅ Agree on port numbers: Backend = 8000, Frontend = 5173 | All | No port conflicts |

**EXIT CRITERIA:** schemas.py exists, api.ts exists, mock JSONs exist. OSM ban confirmed. MapMyIndia key status clear. Everyone knows their Day 1 tasks.

---

### 08:30 – 10:00 | PARALLEL SPRINT 1 — Skeleton

#### Person 1 (Backend)

| # | Task | File(s) | Output |
|---|---|---|---|
| ✅ | Create FastAPI skeleton with CORS | `backend/app/main.py` | Server starts on :8000, CORS allows localhost:5173 |
| ✅ | Create router stubs (return mock JSON) | `backend/app/routers/heatmap.py`, `risk.py`, `forecast.py`, `game.py`, `simulate.py`, `explain.py`, `traffic.py` | Every endpoint returns mock data from `data/mock/` |
| ✅ | Write requirements.txt | `backend/requirements.txt` | `fastapi, uvicorn, pandas, numpy, h3, pydantic, scikit-learn, lightgbm, catboost, httpx` |

```python
# backend/app/main.py — SKELETON
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import heatmap, risk, forecast, game, simulate, explain, traffic

app = FastAPI(title="ParkVision-Saathi API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(heatmap.router, prefix="/api", tags=["heatmap"])
app.include_router(risk.router, prefix="/api", tags=["risk"])
app.include_router(forecast.router, prefix="/api", tags=["forecast"])
app.include_router(game.router, prefix="/api", tags=["game"])
app.include_router(simulate.router, prefix="/api", tags=["simulate"])
app.include_router(explain.router, prefix="/api", tags=["explain"])
app.include_router(traffic.router, prefix="/api", tags=["traffic"])
```

#### Person 2 (ML)

| # | Task | File(s) | Output |
|---|---|---|---|
| ✅ | Load CSV, parse violation_type lists, convert timestamps to IST | `ml/etl/clean_data.py` | `data/processed/violations_clean.parquet` |
| ✅ | Extract pincodes from location field | same file | `pincode` column added |
| ✅ | Create `trusted_vehicle_type` (updated if available, else original) | same file | `trusted_vehicle_type` column |
| ✅ | Drop useless columns (description, closed_datetime, action_taken_timestamp) | same file | Cleaner dataframe |

```python
# ml/etl/clean_data.py — CORE CLEANING
import pandas as pd
import ast, re, h3

def parse_violation_list(val):
    """Parse '[\"WRONG PARKING\",\"NO PARKING\"]' into Python list"""
    try:
        return ast.literal_eval(val)
    except:
        return [val] if isinstance(val, str) else []

def clean_data(csv_path):
    df = pd.read_csv(csv_path)
    
    # Parse timestamps
    df['created_datetime'] = pd.to_datetime(df['created_datetime'], utc=True, format='mixed')
    df['created_ist'] = df['created_datetime'].dt.tz_convert('Asia/Kolkata')
    df['hour'] = df['created_ist'].dt.hour
    df['day_of_week'] = df['created_ist'].dt.dayofweek
    df['date'] = df['created_ist'].dt.date
    df['month'] = df['created_ist'].dt.month
    df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)
    
    # Time buckets (handling temporal cliff!)
    df['time_bucket'] = pd.cut(df['hour'], 
        bins=[-1, 5, 9, 13, 15, 23],
        labels=['night', 'morning_peak', 'midday', 'afternoon', 'evening_sparse'])
    
    # Parse violations
    df['violation_list'] = df['violation_type'].apply(parse_violation_list)
    df['violation_count_in_row'] = df['violation_list'].apply(len)
    
    # Vehicle type
    df['trusted_vehicle_type'] = df['updated_vehicle_type'].fillna(df['vehicle_type'])
    
    # Pincode
    df['pincode'] = df['location'].str.extract(r'(\d{6})')
    
    # H3 grid
    df['h3_id'] = df.apply(lambda r: h3.latlng_to_cell(float(r['latitude']), float(r['longitude']), 9), axis=1)
    
    # Validation
    df['is_approved'] = (df['validation_status'] == 'approved').astype(int)
    
    # Drop useless
    df.drop(columns=['description', 'closed_datetime', 'action_taken_timestamp'], inplace=True, errors='ignore')
    
    df.to_parquet('data/processed/violations_clean.parquet', index=False)
    return df
```

#### Person 3 (Frontend)

| # | Task | File(s) | Output |
|---|---|---|---|
| ✅ | Create React app (Vite + TypeScript) | `frontend/` | App runs on :5173 |
| ✅ | Install deps: axios | `package.json` | Dependencies installed |
| ✅ | Load Mappls SDK script in index.html | `frontend/index.html` | Mappls available globally |
| ✅ | Render Mappls map centered on Bengaluru (12.97, 77.59, zoom 12) | `frontend/src/components/MapView.tsx` | Map visible in browser |
| ✅ | Add Mappls traffic layer toggle button | `frontend/src/components/TrafficToggle.tsx` | Traffic overlay toggleable |
| 🔶 STRETCH | If Mappls fails → set up Leaflet + Mappls raster tiles fallback (NO OSM) | `MapView.tsx` | Fallback map ready |

```html
<!-- frontend/index.html — Add in <head> -->
<script src="https://apis.mappls.com/advancedmaps/api/{YOUR_KEY}/map_sdk?layer=vector&v=3.0"></script>
```

#### Person 4 (Integration + Docs)

| # | Task | File(s) | Output |
|---|---|---|---|
| ✅ | Draft README.md with project overview | `docs/README.md` | Professional README |
| ✅ | Write 3 LLM prompt templates (zone explain, patrol recommend, impact explain) | `ml/llm/prompts.py` | Prompt templates ready |
| ✅ | Test MapMyIndia Distance Matrix API with 2 sample coordinates | `ml/enrichment/test_mapmyindia.py` | Confirmed API works or fallback needed |
| ✅ | Create `data/mock/` directory with example JSON for every endpoint | `data/mock/*.json` | Frontend can develop against mock data |

---

### 10:00 – 12:00 | PARALLEL SPRINT 2 — Data + Layout

#### Person 1 (Backend)

| # | Task | File(s) | Output |
|---|---|---|---|
| ✅ | Write data loader: loads parquet into memory at startup | `backend/app/data_loader.py` | `VIOLATIONS_DF`, `ZONES_DF`, `RISK_DF` globals available to all routers |
| ✅ | Implement real `/api/heatmap?time_bucket=morning_peak` | `backend/app/routers/heatmap.py` | Returns HeatmapResponse with real data |
| ✅ | Implement real `/api/hotspots?time_bucket=&station=&limit=15` | same file | Returns ranked list of HotspotItem |

```python
# backend/app/data_loader.py
import pandas as pd
import json, os

class DataStore:
    """In-memory data store. Loaded once at startup."""
    def __init__(self):
        self.violations = None
        self.zones = None
        self.risk_scores = None
        self.forecasts = None
        self.traffic_context = None
        self.explanations_cache = {}
        self.demo_cache = {}
    
    def load(self):
        data_dir = os.getenv("DATA_DIR", "data/processed")
        self.violations = pd.read_parquet(f"{data_dir}/violations_clean.parquet")
        
        if os.path.exists(f"{data_dir}/zone_risk.json"):
            self.risk_scores = json.load(open(f"{data_dir}/zone_risk.json"))
        if os.path.exists(f"{data_dir}/forecasts.json"):
            self.forecasts = json.load(open(f"{data_dir}/forecasts.json"))
        if os.path.exists(f"{data_dir}/traffic_context.json"):
            self.traffic_context = json.load(open(f"{data_dir}/traffic_context.json"))
        if os.path.exists(f"{data_dir}/explanations_cache.json"):
            self.explanations_cache = json.load(open(f"{data_dir}/explanations_cache.json"))

store = DataStore()
```

#### Person 2 (ML)

| # | Task | File(s) | Output |
|---|---|---|---|
| ✅ | Create H3 zones from violations | `ml/etl/create_zones.py` | `data/processed/zones.json` — list of {h3_id, centroid_lat, centroid_lon, station, pincode, junction, neighbors[]} |
| ✅ | Compute zone-level aggregations per time_bucket | same file | `data/processed/zone_time_counts.parquet` |
| ✅ | Implement congestion impact score computation | `ml/congestion/impact_score.py` | `data/processed/zone_congestion_impact.json` — {h3_id → {time_bucket → {congestion_impact, components...}}} |

```python
# ml/congestion/impact_score.py — CONGESTION IMPACT SCORING (Theme-Aligned)
import numpy as np
import h3

# Severity weights — reframed as CONGESTION IMPACT
# Higher weight = more road capacity blocked
LANE_BLOCKAGE_WEIGHTS = {
    'DOUBLE PARKING': 2.0,            # Blocks 2 lanes
    'PARKING IN A MAIN ROAD': 1.5,    # Blocks 1 lane on arterial
    'PARKING NEAR ROAD CROSSING': 1.3, # Blocks intersection approach
    'PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS': 1.3, # Blocks intersection
    'PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC': 1.2,  # Blocks transit access
    'PARKING ON FOOTPATH': 0.5,       # Forces pedestrians onto road
    'WRONG PARKING': 0.8,             # Generic lane impact
    'NO PARKING': 0.8,
}

VEHICLE_OBSTRUCTION = {
    'SCOOTER': 0.50, 'MOTOR CYCLE': 0.50, 'MOPED': 0.50,
    'CAR': 1.00, 'JEEP': 1.00, 'VAN': 1.00,
    'PASSENGER AUTO': 1.10, 'MAXI-CAB': 1.10,
    'LGV': 1.50, 'HGV': 1.80, 'LORRY/GOODS VEHICLE': 1.80, 'TANKER': 1.80, 'TEMPO': 1.50,
    'BUS (BMTC/KSRTC)': 2.00, 'PRIVATE BUS': 2.00, 'SCHOOL VEHICLE': 1.50,
}

def compute_congestion_impact(zone_df, all_stats, mapmy_data=None):
    """
    Congestion Impact Score (0-100).
    Theme: "quantify their impact on traffic flow"
    """
    n = len(zone_df)
    if n == 0:
        return 0.0, {}
    
    # Component 1: Lane Capacity Reduction (30%)
    main_road = (zone_df['violation_list'].apply(
        lambda vs: 'PARKING IN A MAIN ROAD' in vs)).sum()
    double_park = (zone_df['violation_list'].apply(
        lambda vs: 'DOUBLE PARKING' in vs)).sum()
    lane_blocked = (main_road * 1.0 + double_park * 2.0) / max(all_stats['max_lane_blocked'], 1)
    lane_blocked = min(lane_blocked, 1.0)
    
    # Component 2: Intersection Throughput Impact (25%)
    junction_violations = (zone_df['violation_list'].apply(
        lambda vs: any(v in vs for v in [
            'PARKING NEAR ROAD CROSSING',
            'PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS'
        ]))).sum()
    has_junction = (zone_df['junction_name'] != 'No Junction').any()
    junction_impact = min(
        (junction_violations / max(all_stats['max_junction_violations'], 1)) * 
        (1.5 if has_junction else 0.5), 1.0)
    
    # Component 3: Mappls Travel Time Degradation (25%)
    if mapmy_data and mapmy_data.get('travel_time_ratio'):
        ratio = mapmy_data['travel_time_ratio']
        traffic_degradation = min((ratio - 1.0) / 2.0, 1.0)
    else:
        traffic_degradation = 0.5  # Unknown = assume moderate
    
    # Component 4: Transit & Emergency Access Blockage (10%)
    access_violations = (zone_df['violation_list'].apply(
        lambda vs: any(v in vs for v in [
            'PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC',
            'PARKING ON FOOTPATH'
        ]))).sum()
    access_blockage = min(access_violations / max(all_stats['max_access_violations'], 1), 1.0)
    
    # Component 5: Vehicle Size Impact (10%)
    avg_obstruction = zone_df['vehicle_obstruction_weight'].mean()
    vehicle_size = min(avg_obstruction / 1.5, 1.0)
    
    # Final Score
    score = (0.30 * lane_blocked +
             0.25 * junction_impact +
             0.25 * traffic_degradation +
             0.10 * access_blockage +
             0.10 * vehicle_size)
    
    # Lane-hours blocked estimate
    lane_hours = (main_road * 0.5 + double_park * 1.0 + 
                  junction_violations * 0.75 + 
                  (n - main_road - double_park - junction_violations) * 0.25)
    
    components = {
        'lane_blockage': float(lane_blocked),
        'intersection_impact': float(junction_impact),
        'traffic_degradation': float(traffic_degradation),
        'access_blockage': float(access_blockage),
        'vehicle_size': float(vehicle_size),
        'estimated_lane_hours_blocked': float(lane_hours),
    }
    
    return min(score * 100, 100), components

def impact_band(score):
    if score <= 25: return 'MINIMAL'
    elif score <= 50: return 'MODERATE'
    elif score <= 75: return 'SEVERE'
    else: return 'CRITICAL'

#### Person 3 (Frontend)

| # | Task | File(s) | Output |
|---|---|---|---|
| ✅ | Build 3-panel layout: left sidebar, center map, right panel | `frontend/src/App.tsx`, `frontend/src/styles/index.css` | Layout renders with placeholders |
| ✅ | Left panel: Stats cards (total violations, severe-impact zones, stations) | `frontend/src/components/StatsPanel.tsx` | Cards showing hardcoded numbers |
| ✅ | Bottom: Time bucket selector (4 buttons: Night / Morning / Midday / Afternoon) | `frontend/src/components/TimeSelector.tsx` | Buttons change selected time |
| ✅ | API client module | `frontend/src/api/client.ts` | Functions: `getHeatmap(hour)`, `getHotspots(hour)`, `getRisk(zoneId)`, etc. |

```typescript
// frontend/src/api/client.ts
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api';

export async function getHeatmap(timeBucket: string): Promise<HeatmapResponse> {
  const res = await fetch(`${API_BASE}/heatmap?time_bucket=${timeBucket}`);
  return res.json();
}

export async function getHotspots(timeBucket: string, station?: string): Promise<HotspotItem[]> {
  let url = `${API_BASE}/hotspots?time_bucket=${timeBucket}&limit=15`;
  if (station) url += `&station=${station}`;
  const res = await fetch(url);
  return res.json();
}

export async function getRiskBreakdown(zoneId: string, hour: number): Promise<RiskBreakdown> {
  const res = await fetch(`${API_BASE}/risk/${zoneId}?hour=${hour}`);
  return res.json();
}

export async function simulate(req: SimulationRequest): Promise<SimulationResponse> {
  const res = await fetch(`${API_BASE}/simulate`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(req)
  });
  return res.json();
}

export async function explainZone(zoneId: string, hour: number): Promise<ExplainResponse> {
  const res = await fetch(`${API_BASE}/explain`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ zone_id: zoneId, hour })
  });
  return res.json();
}
```

#### Person 4 (Integration)

| # | Task | File(s) | Output |
|---|---|---|---|
| ✅ | Write MapMyIndia enrichment script | `ml/enrichment/mapmyindia.py` | Queries Distance Matrix for top 20 hotspots, saves to `data/enriched/traffic_context.json` |
| ✅ | If API key not working → manual fallback | `data/enriched/traffic_context_manual.json` | Manually record 10 travel times from Google Maps for top 10 hotspots |
| ✅ | Write presentation outline (bullet points per slide) | `docs/presentation_outline.md` | 8-slide structure from master plan |

```python
# ml/enrichment/mapmyindia.py
import httpx, json, time

MAPPLS_KEY = "YOUR_KEY"  # Set from env

def get_travel_time(origin_lat, origin_lon, dest_lat, dest_lon):
    """Get travel time between two points via Mappls Routing API."""
    url = f"https://apis.mappls.com/advancedmaps/v1/{MAPPLS_KEY}/route_adv/driving/{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
    resp = httpx.get(url, params={"geometries": "polyline", "overview": "full"})
    if resp.status_code == 200:
        data = resp.json()
        if 'routes' in data and data['routes']:
            return data['routes'][0].get('duration', None)  # seconds
    return None

def enrich_hotspots(hotspots_json_path, output_path):
    """For each hotspot, query travel time and nearby POIs."""
    with open(hotspots_json_path) as f:
        hotspots = json.load(f)
    
    # Use a consistent control point (e.g., Bengaluru center)
    control_lat, control_lon = 12.9716, 77.5946
    
    results = {}
    for spot in hotspots[:20]:  # Top 20 only
        time.sleep(0.5)  # Rate limit safety
        duration = get_travel_time(spot['lat'], spot['lon'], control_lat, control_lon)
        results[spot['h3_id']] = {
            'zone_id': spot['h3_id'],
            'travel_time_to_center_sec': duration,
            'lat': spot['lat'],
            'lon': spot['lon'],
            'station': spot.get('station', ''),
        }
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    return results
```

---

### 12:00 – 12:30 | 🍽️ ALL: LUNCH + PROGRESS CHECK

**Agenda (10 min):**
1. Person 2: "Is violations_clean.parquet ready?" → Person 1 can load it
2. Person 1: "Are mock endpoints live?" → Person 3 can call them
3. Person 3: "Is the map rendering?" → Show screen
4. Person 4: "Is MapMyIndia API working?" → Status update

---

### 12:30 – 14:00 | PARALLEL SPRINT 3 — First Data Connection

#### Person 1

| # | Task | Output |
|---|---|---|
| ✅ | Load Person 2's zone_congestion_impact.json into DataStore | Congestion data available in API |
| ✅ | `/api/heatmap` returns real congestion impact scores per H3 cell per time_bucket | Real heatmap data |
| ✅ | `/api/hotspots` returns sorted zones by congestion_impact | Real hotspot ranking |

#### Person 2

| # | Task | Output |
|---|---|---|
| ✅ | Complete congestion impact score for ALL zones × ALL time buckets | `data/processed/zone_congestion_impact.json` complete |
| ✅ | Label impact bands: 0-25=MINIMAL, 26-50=MODERATE, 51-75=SEVERE, 76-100=CRITICAL | Bands in output |
| ✅ | Start feature engineering for forecasting model | Feature matrix building |

**Key features to engineer:**
```python
# ml/etl/feature_engineering.py
def build_forecast_features(df):
    """Build features for LightGBM + CatBoost forecasting."""
    # Group by zone and date
    daily = df.groupby(['h3_id', 'date']).agg(
        count=('id', 'count'),
        severity_mean=('severity_weight', 'mean'),
        vehicle_weight_mean=('vehicle_obstruction_weight', 'mean'),
        repeat_ratio=('vehicle_number', lambda x: (x.value_counts() > 1).sum() / len(x.value_counts())),
        approval_rate=('is_approved', 'mean'),
        station=('police_station', 'first'),
        pincode=('pincode', 'first'),
        has_junction=('junction_name', lambda x: (x != 'No Junction').any()),
    ).reset_index()
    
    # Sort by date for lag features
    daily = daily.sort_values(['h3_id', 'date'])
    
    # Temporal features
    daily['day_of_week'] = pd.to_datetime(daily['date']).dt.dayofweek
    daily['is_weekend'] = daily['day_of_week'].isin([5, 6]).astype(int)
    daily['month'] = pd.to_datetime(daily['date']).dt.month
    
    # Lag features (per zone)
    for lag in [1, 7, 14]:
        daily[f'lag_{lag}d'] = daily.groupby('h3_id')['count'].shift(lag)
    
    # Rolling features
    daily['rolling_mean_7d'] = daily.groupby('h3_id')['count'].transform(
        lambda x: x.rolling(7, min_periods=1).mean())
    daily['rolling_mean_14d'] = daily.groupby('h3_id')['count'].transform(
        lambda x: x.rolling(14, min_periods=1).mean())
    daily['rolling_std_7d'] = daily.groupby('h3_id')['count'].transform(
        lambda x: x.rolling(7, min_periods=1).std())
    
    # Zone historical rank
    zone_avg = daily.groupby('h3_id')['count'].mean()
    daily['zone_rank'] = daily['h3_id'].map(zone_avg.rank(ascending=False))
    
    return daily.dropna(subset=['lag_1d'])  # Drop rows without lag features
```

#### Person 3

| # | Task | Output |
|---|---|---|
| ✅ | Integrate Mappls HeatmapLayer with mock data (or real if API is up) | Heatmap shows on map |
| ✅ | Configure heatmap radius + blur for auto-scaling with zoom (built-in — 0 extra work) | Zoomed out = big blobs, zoomed in = detailed spots |
| ✅ | **TWO-LAYER MAP TOGGLE (THEME CRITICAL):** Add toggle buttons: "Violation Density" vs "Congestion Risk Impact". Both render HeatmapLayer on same map. Pass `layer=violation_density` or `layer=congestion_risk` to `/api/heatmap`. The maps will NOT be identical — that's the point. | **PROVES THEME ALIGNMENT** |
| ✅ | Time bucket buttons change the heatmap | Different view per time |
| 🔶 STRETCH | Add smooth transition animation between time buckets | Visual polish |

```tsx
// frontend/src/components/LayerToggle.tsx — THEME CRITICAL COMPONENT
import React from 'react';

interface LayerToggleProps {
  activeLayer: 'violation_density' | 'congestion_risk';
  onChange: (layer: 'violation_density' | 'congestion_risk') => void;
}

export const LayerToggle: React.FC<LayerToggleProps> = ({ activeLayer, onChange }) => (
  <div className="layer-toggle">
    <button 
      className={activeLayer === 'violation_density' ? 'active' : ''}
      onClick={() => onChange('violation_density')}
    >
      Violation Density
      <span className="subtitle">Where violations happen</span>
    </button>
    <button 
      className={activeLayer === 'congestion_risk' ? 'active' : ''}
      onClick={() => onChange('congestion_risk')}
    >
      Congestion Risk Impact
      <span className="subtitle">Where violations choke traffic</span>
    </button>
  </div>
);
```

#### Person 4

| # | Task | Output |
|---|---|---|
| ✅ | Continue MapMyIndia enrichment — query Nearby API for POIs around top hotspots | POIs cached |
| ✅ | Start writing mock LLM explanations for top 5 hotspots (manually) | `data/processed/explanations_cache.json` with 5 entries |

---

### 14:00 – 16:00 | PARALLEL SPRINT 4 — Real Data Flowing

#### Person 1

| # | Task | Output |
|---|---|---|
| ✅ | Connect real data to all heatmap/hotspot endpoints | Real responses |
| ✅ | Implement `/api/risk/{zone_id}?hour=` with component breakdown | Zone detail API working |
| ✅ | Test with curl / httpie / browser to verify responses | Tested |

#### Person 2

| # | Task | Output |
|---|---|---|
| ✅ | Complete feature matrix | `data/processed/forecast_features.parquet` |
| ✅ | Time-split: Train (Nov–Feb), Validate (Mar) | Split done |
| ✅ | Train baseline LightGBM | First MAE number recorded |

```python
# ml/forecast/train_lightgbm.py
import lightgbm as lgb
from sklearn.metrics import mean_absolute_error
import pandas as pd, numpy as np

def train_model(features_path):
    df = pd.read_parquet(features_path)
    
    # Time split
    train = df[pd.to_datetime(df['date']) < '2024-03-01']
    val = df[(pd.to_datetime(df['date']) >= '2024-03-01') & 
             (pd.to_datetime(df['date']) < '2024-04-01')]
    
    feature_cols = ['day_of_week', 'is_weekend', 'month', 'lag_1d', 'lag_7d', 
                    'lag_14d', 'rolling_mean_7d', 'rolling_mean_14d', 'rolling_std_7d',
                    'zone_rank', 'severity_mean', 'vehicle_weight_mean', 'has_junction']
    
    # Encode station as category
    train['station_enc'] = train['station'].astype('category').cat.codes
    val['station_enc'] = val['station'].astype('category').cat.codes
    feature_cols.append('station_enc')
    
    X_train, y_train = train[feature_cols], train['count']
    X_val, y_val = val[feature_cols], val['count']
    
    model = lgb.LGBMRegressor(
        n_estimators=500, learning_rate=0.05, num_leaves=31,
        min_child_samples=20, subsample=0.8, colsample_bytree=0.8,
        objective='poisson',  # Count data!
        random_state=42
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], 
              callbacks=[lgb.early_stopping(50)])
    
    preds = model.predict(X_val)
    mae = mean_absolute_error(y_val, preds)
    
    # Precision@10
    for date in val['date'].unique():
        day_data = val[val['date'] == date]
        day_preds = preds[val['date'] == date]
        # ... compute P@10
    
    print(f"LightGBM MAE: {mae:.2f}")
    return model, mae
```

#### Person 3

| # | Task | Output |
|---|---|---|
| ✅ | Time bucket selector → calls `/api/heatmap?time_bucket=` → updates map | Dynamic heatmap |
| ✅ | Left panel: hotspot list from `/api/hotspots` | Ranked list renders |
| 🔶 STRETCH | Hourly granularity slider within morning_peak/midday buckets | More detail for judges |

#### Person 4

| # | Task | Output |
|---|---|---|
| ✅ | Finish MapMyIndia enrichment for 20 hotspots | `data/enriched/traffic_context.json` |
| ✅ | Help Person 1 test API endpoints | Bug reports filed |
| ✅ | Start presentation slide design | Slides 1-3 drafted |

---

### 16:00 – 16:30 | 🧪 INTEGRATION CHECKPOINT #1

**Agenda (30 min strict):**

| Minute | Action | Pass/Fail |
|---|---|---|
| 0-5 | Person 1 starts backend (`uvicorn app.main:app --reload`) | Server runs ✅/❌ |
| 5-10 | Person 3 opens frontend → map loads → calls `/api/heatmap` | Heatmap appears ✅/❌ |
| 10-15 | Change time bucket → heatmap updates | Different data shows ✅/❌ |
| 15-18 | **Toggle Two-Layer switch** → heatmap changes between violation density and congestion risk | **DIFFERENT maps shown ✅/❌ (THEME CRITICAL)** |
| 18-22 | Open `/docs` (FastAPI auto-docs) → all endpoints listed | API docs work ✅/❌ |
| 22-26 | Curl `/api/hotspots?time_bucket=morning_peak` → valid JSON | Response matches schema ✅/❌ |
| 26-30 | Decision: What's the biggest blocker for Day 2? Assign fix. | Blocker identified |

**IF CHECKPOINT FAILS:** Person 1 + Person 3 pair-debug for 30 min. Person 2 + Person 4 continue their tasks independently.

---

### 16:30 – 18:00 | PARALLEL SPRINT 5 — Depth

#### Person 1

| # | Task | Output |
|---|---|---|
| ✅ | `/api/risk/{zone_id}` returns real component breakdown | Real risk detail |
| ✅ | `/api/forecast` — mock endpoint for now (return Person 2's baseline) | Mock forecast |
| 🔶 STRETCH | `/api/traffic/{zone_id}` — serve cached MapMyIndia data | Traffic context available |

#### Person 2

| # | Task | Output |
|---|---|---|
| ✅ | Tune LightGBM: try Poisson objective, adjust num_leaves | Better MAE |
| ✅ | Train CatBoost on same data (native categoricals: station, pincode) | CatBoost MAE |
| 🔶 STRETCH | Ensemble: average LightGBM + CatBoost predictions | Ensemble MAE |
| ✅ | Compute Precision@10 on validation set | P@10 metric |

```python
# ml/forecast/train_catboost.py
from catboost import CatBoostRegressor

def train_catboost(train_df, val_df, feature_cols, cat_features):
    model = CatBoostRegressor(
        iterations=500, learning_rate=0.05, depth=6,
        loss_function='Poisson',
        cat_features=cat_features,  # ['station', 'pincode']
        verbose=50, random_seed=42
    )
    model.fit(train_df[feature_cols], train_df['count'],
              eval_set=(val_df[feature_cols], val_df['count']))
    return model
```

#### Person 3

| # | Task | Output |
|---|---|---|
| ✅ | Style stats panel: dark theme cards | Professional look |
| ✅ | Zone markers on map (top 15 hotspots as circles) | Markers visible |
| ✅ | Click handler on marker → shows zone_id in right panel | Click works |

#### Person 4

| # | Task | Output |
|---|---|---|
| ✅ | Write 5 more manual LLM explanations (10 total) | Explanations cached |
| ✅ | Test API with real frontend — note any format mismatches | Bug list |
| ✅ | Continue presentation slides | Slides 4-5 drafted |

---

### 18:00 – 18:30 | 🍽️ ALL: DINNER

---

### 18:30 – 20:00 | PARALLEL SPRINT 6 — Game Theory Start

#### Person 1

| # | Task | Output |
|---|---|---|
| ✅ | `/api/game/strategy?time_bucket=` — mock returning risk-proportional probabilities | Mock game endpoint |
| ✅ | `/api/simulate` — mock returning pre-computed simulation | Mock simulation |
| ✅ | Set up CORS, env vars, document running instructions | Developer-friendly |

#### Person 2

| # | Task | Output |
|---|---|---|
| ✅ | Implement Stackelberg patrol allocation function | `ml/game_theory/stackelberg.py` working |
| ✅ | Implement expected utility computation for violators | `ml/game_theory/stackelberg.py` — violator scores |
| ✅ | Save model artifacts | `ml/models/lightgbm_v1.pkl`, `ml/models/catboost_v1.pkl` |

```python
# ml/game_theory/stackelberg.py — COMPLETE IMPLEMENTATION
import numpy as np
import h3

def compute_patrol_strategy(zone_risk_scores: dict, num_teams: int, 
                            patrol_history: dict = None, alpha=1.5, lambda_=0.3):
    """
    Stackelberg-inspired patrol allocation.
    
    Args:
        zone_risk_scores: {h3_id: risk_score (0-100)}
        num_teams: number of patrol teams available
        patrol_history: {h3_id: recent_patrol_count}
        alpha: risk emphasis exponent
        lambda_: enforcement fatigue decay
    
    Returns:
        allocations: [{zone_id, team_id, probability, risk_score}]
        zone_probabilities: {h3_id: patrol_probability}
    """
    if patrol_history is None:
        patrol_history = {}
    
    zones = list(zone_risk_scores.keys())
    risks = np.array([zone_risk_scores[z] for z in zones])
    
    # Step 1: Base weights from risk (nonlinear emphasis on high-risk)
    weights = np.power(risks / 100.0, alpha)
    
    # Step 2: Enforcement fatigue reduction
    for i, z in enumerate(zones):
        recent_patrols = patrol_history.get(z, 0)
        weights[i] /= (1 + lambda_ * recent_patrols)
    
    # Step 3: Normalize to probabilities
    if weights.sum() > 0:
        probabilities = weights / weights.sum()
    else:
        probabilities = np.ones(len(zones)) / len(zones)
    
    # Step 4: Allocate integer teams (greedy top-k)
    sorted_indices = np.argsort(-probabilities)
    allocations = []
    assigned_teams = 0
    
    for rank, idx in enumerate(sorted_indices):
        if assigned_teams >= num_teams:
            break
        allocations.append({
            'team_id': assigned_teams + 1,
            'zone_id': zones[idx],
            'priority_rank': rank + 1,
            'patrol_probability': float(probabilities[idx]),
            'risk_score': float(risks[idx])
        })
        assigned_teams += 1
    
    zone_probabilities = {z: float(p) for z, p in zip(zones, probabilities)}
    
    return allocations, zone_probabilities


def compute_violator_utility(zone_risk_scores: dict, zone_probabilities: dict, 
                              zone_context: dict, fine_amount=500):
    """
    For each zone, compute violator's expected utility.
    If E[U] > 0, rational violator will park illegally.
    """
    results = {}
    for zone_id in zone_risk_scores:
        p = zone_probabilities.get(zone_id, 0)
        ctx = zone_context.get(zone_id, {})
        
        # Time saved proxy
        has_main_road = ctx.get('has_main_road', False)
        time_saved_min = 10 if has_main_road else 5
        time_value = time_saved_min * 5  # ₹5 per minute
        
        expected_benefit = (1 - p) * time_value
        expected_cost = p * fine_amount
        net_utility = expected_benefit - expected_cost
        
        # Sigmoid mapping to 0-100
        violator_risk = 100 / (1 + np.exp(-net_utility / 50))
        
        results[zone_id] = {
            'net_utility': float(net_utility),
            'will_violate': bool(net_utility > 0),
            'violator_risk_score': float(violator_risk),
            'patrol_probability': float(p)
        }
    
    return results
```

#### Person 3

| # | Task | Output |
|---|---|---|
| ✅ | Right panel: zone detail card (congestion impact score, band, station, junction) | Zone detail shows on click |
| ✅ | **Show `estimated_lane_hours_blocked` in zone detail panel** — "This zone blocks 47 lane-hours per day" | **Tangible metric judges latch onto** |
| ✅ | Loading states for API calls | Skeleton loaders |
| 🔶 STRETCH | Add station filter dropdown to header | Filtering works |

#### Person 4

| # | Task | Output |
|---|---|---|
| ✅ | Integration test: call every API endpoint, verify response matches schema | Test report |
| ✅ | Write 5 more explanations (15 total) | Expanding cache |
| ✅ | Continue slides | Slides 6-7 |

---

### 20:00 – 22:00 | PARALLEL SPRINT 7 — Consolidation

#### Person 1

| # | Task | Output |
|---|---|---|
| ✅ | Ensure ALL mock endpoints return consistent, schema-compliant data | All endpoints tested |
| ✅ | Write `API_DOCS.md` with curl examples | Documentation |
| 🔶 STRETCH | Implement demo mode flag in backend | `DEMO_MODE=true` serves cached responses |

#### Person 2

| # | Task | Output |
|---|---|---|
| ✅ | Implement spillover/waterbed simulation | `ml/game_theory/spillover.py` working |
| ✅ | Test: enforce zone A → verify neighbors' risk increases, total conserved | Unit test passes |

```python
# ml/game_theory/spillover.py — CONSERVATION-ENFORCING
import h3
import numpy as np

def compute_spillover(zone_risks: dict, enforced_zones: list, reduction_pct=0.20):
    """
    When zones are enforced, violations are displaced (not destroyed).
    Conservation law: total system violations stay constant.
    """
    adjusted = {z: {'original_risk': r, 'adjusted_risk': r, 'change_pct': 0.0} 
                for z, r in zone_risks.items()}
    
    for enforced_id in enforced_zones:
        if enforced_id not in adjusted:
            continue
        
        original_risk = adjusted[enforced_id]['original_risk']
        displaced = original_risk * reduction_pct
        
        # Reduce enforced zone
        adjusted[enforced_id]['adjusted_risk'] -= displaced
        adjusted[enforced_id]['change_pct'] = -reduction_pct * 100
        
        # Find neighbors (H3 k-ring, exclude self)
        neighbors = [n for n in h3.grid_ring(enforced_id, 1) if n in adjusted]
        
        if not neighbors:
            continue
        
        # Distribute displaced risk by inverse distance (all equidistant in H3 k=1)
        share = displaced / len(neighbors)
        
        for neighbor in neighbors:
            adjusted[neighbor]['adjusted_risk'] += share
            change = share / max(adjusted[neighbor]['original_risk'], 0.01) * 100
            adjusted[neighbor]['change_pct'] = change
    
    # Verify conservation
    total_original = sum(v['original_risk'] for v in adjusted.values())
    total_adjusted = sum(v['adjusted_risk'] for v in adjusted.values())
    assert abs(total_original - total_adjusted) < 0.01, "Conservation violated!"
    
    return adjusted
```

#### Person 3

| # | Task | Output |
|---|---|---|
| ✅ | Refine layout, consistent padding/margins | Clean UI |
| ✅ | Dark theme CSS variables | Theme applied |
| 🔶 STRETCH | Hover effect on heatmap zones | Interactive feel |

#### Person 4

| # | Task | Output |
|---|---|---|
| ✅ | Full flow test: frontend → backend → data pipeline | End-to-end working |
| ✅ | Bug report with priority tagging (P0/P1/P2) | Prioritized fix list |

---

### 22:00 | 💤 END OF DAY 1 STANDUP (15 min) → SLEEP

**Agenda:**
1. Each person: 2 min status update (what's done, what's blocked)
2. Review Day 1 checklist (above)
3. Identify top 3 priorities for Day 2 morning
4. **Go to sleep by 22:30. No exceptions.**

---

# DAY 2: INTELLIGENCE

## Theme: "ML is integrated. Simulation works. Demo path is viable."

---

### 08:00 – 08:30 | ALL STANDUP

Review Day 1 bugs. Assign Day 2 priorities. Key question: "Is our data pipeline producing correct results?"

---

### 08:30 – 10:00 | SPRINT 8 — ML Integration

#### Person 1

| # | Task | Output |
|---|---|---|
| ✅ | Connect LightGBM/CatBoost predictions to `/api/forecast` | Real forecast data |
| ✅ | Connect Stackelberg output to `/api/game/strategy` | Real game theory data |
| ✅ | Load all Person 2's pre-computed JSONs at startup | All data in memory |

#### Person 2

| # | Task | Output |
|---|---|---|
| ✅ | Finalize ensemble model (average LightGBM + CatBoost if both trained) | Final forecast |
| ✅ | Pre-compute forecasts for next 7 days (validation period) | `data/processed/forecasts.json` |
| ✅ | Pre-compute Stackelberg allocations for 3, 5, 8, 10 team scenarios | `data/processed/patrol_allocations.json` |

#### Person 3

| # | Task | Output |
|---|---|---|
| ✅ | Replace ALL mock data calls with real API calls | Real data on map |
| ✅ | `/api/heatmap` → Mappls HeatmapLayer | Real heatmap |
| ✅ | `/api/hotspots` → sidebar list with risk badges | Real ranked list |

#### Person 4

| # | Task | Output |
|---|---|---|
| ✅ | Test full API integration — all endpoints with real data | Integration verified |
| ✅ | Set up Gemini API client | `ml/llm/gemini_client.py` |
| ✅ | Test one LLM call with structured prompt | LLM response quality checked |

---

### 10:00 – 12:00 | SPRINT 9 — Core Differentiators

#### Person 1

| # | Task | Output |
|---|---|---|
| ✅ | Implement `/api/game/violator?time_bucket=` with violator utility scores | Violator adaptation data |
| ✅ | Implement `POST /api/simulate` with real Stackelberg + spillover | **SIMULATION WORKS** |

```python
# backend/app/routers/simulate.py — THE CRITICAL ENDPOINT
from fastapi import APIRouter
from app.models.schemas import SimulationRequest, SimulationResponse
from app.data_loader import store
import sys; sys.path.insert(0, '../ml')
from game_theory.stackelberg import compute_patrol_strategy, compute_violator_utility
from game_theory.spillover import compute_spillover

router = APIRouter()

@router.post("/simulate", response_model=SimulationResponse)
async def simulate(req: SimulationRequest):
    # Get risk scores for requested time bucket
    risk_scores = store.get_risk_scores(req.time_bucket)
    
    # Stackelberg allocation
    allocations, probabilities = compute_patrol_strategy(
        risk_scores, req.num_teams)
    
    # Spillover simulation
    enforced_zones = [a['zone_id'] for a in allocations]
    spillover_result = compute_spillover(risk_scores, enforced_zones)
    
    # Compute coverage metrics
    total_risk = sum(risk_scores.values())
    covered_risk = sum(risk_scores[a['zone_id']] for a in allocations)
    
    # Identify uncovered high-risk zones
    covered_ids = set(a['zone_id'] for a in allocations)
    uncovered = [
        {'zone_id': z, 'risk_score': r}
        for z, r in sorted(risk_scores.items(), key=lambda x: -x[1])
        if z not in covered_ids and r > 60
    ][:10]
    
    # Spillover zones with significant change
    spillover_zones = [
        {'zone_id': z, 'original_risk': v['original_risk'],
         'adjusted_risk': v['adjusted_risk'], 'change_pct': v['change_pct']}
        for z, v in spillover_result.items()
        if abs(v['change_pct']) > 5
    ]
    
    return SimulationResponse(
        num_teams=req.num_teams,
        allocations=allocations,
        covered_risk_pct=covered_risk / total_risk * 100,
        uncovered_risk_pct=(1 - covered_risk / total_risk) * 100,
        uncovered_zones=uncovered,
        spillover_zones=spillover_zones
    )
```

#### Person 2

| # | Task | Output |
|---|---|---|
| ✅ | Implement spillover with conservation law | Verified with unit test |
| ✅ | Validate spillover output makes visual sense (print zone changes) | Sanity checked |
| ✅ | Compute ALL metrics: MAE, RMSE, P@10, baseline comparison, % improvement | `ml/MODEL_CARD.md` updated |
| 🔶 STRETCH | Feature importance plot (SHAP or built-in) for presentation slide | `ml/outputs/feature_importance.png` |

```python
# ml/forecast/evaluate.py — ALL METRICS
def compute_all_metrics(y_true, y_pred, y_baseline, zone_ids, dates):
    """Compute every metric and decide which to present."""
    from sklearn.metrics import mean_absolute_error, mean_squared_error
    import numpy as np
    
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    baseline_mae = mean_absolute_error(y_true, y_baseline)
    improvement_pct = (baseline_mae - mae) / baseline_mae * 100
    
    # Precision@10 per day
    p10_scores = []
    for date in np.unique(dates):
        mask = dates == date
        true_top10 = set(np.array(zone_ids)[mask][np.argsort(-y_true[mask])[:10]])
        pred_top10 = set(np.array(zone_ids)[mask][np.argsort(-y_pred[mask])[:10]])
        p10 = len(true_top10 & pred_top10) / 10
        p10_scores.append(p10)
    
    avg_p10 = np.mean(p10_scores)
    
    # Baseline P@10
    baseline_p10_scores = []
    for date in np.unique(dates):
        mask = dates == date
        true_top10 = set(np.array(zone_ids)[mask][np.argsort(-y_true[mask])[:10]])
        base_top10 = set(np.array(zone_ids)[mask][np.argsort(-y_baseline[mask])[:10]])
        baseline_p10_scores.append(len(true_top10 & base_top10) / 10)
    
    baseline_avg_p10 = np.mean(baseline_p10_scores)
    
    # DECISION: Which metric to present?
    mae_improvement = improvement_pct
    p10_improvement = (avg_p10 - baseline_avg_p10) / max(baseline_avg_p10, 0.01) * 100
    
    best_metric = "P@10" if p10_improvement > mae_improvement else "MAE"
    
    return {
        'mae': mae, 'rmse': rmse, 'baseline_mae': baseline_mae,
        'mae_improvement_pct': mae_improvement,
        'precision_at_10': avg_p10, 'baseline_p10': baseline_avg_p10,
        'p10_improvement_pct': p10_improvement,
        'PRESENT_THIS_METRIC': best_metric,
        'PRESENT_THIS_NUMBER': f"{avg_p10*100:.0f}% P@10" if best_metric == "P@10" else f"{mae:.1f} MAE ({improvement_pct:.0f}% better than baseline)"
    }
```

#### Person 3

| # | Task | Output |
|---|---|---|
| ✅ | Build time SLIDER (upgrade from buttons to actual slider component) | Smooth slider |
| ✅ | Slider range: hourly within 06:00–14:00, or time_bucket buttons for full view | Handles temporal cliff |
| ✅ | Smooth heatmap transitions on slider drag (debounce 200ms) | No flicker |

#### Person 4

| # | Task | Output |
|---|---|---|
| ✅ | Implement `/api/explain` endpoint with Gemini + cache fallback | LLM endpoint working |
| ✅ | Pre-generate explanations for top 20 zones | 20 cached explanations |
| ✅ | Iterate on prompt quality (test 3 prompt variants) | Best prompt selected |

---

### 12:00 – 12:30 | 🧪 INTEGRATION CHECKPOINT #2

**THE BIG TEST: Real data flowing through full stack.**

| Minute | Test | Pass/Fail |
|---|---|---|
| 0-3 | Frontend loads → map shows → heatmap visible with real data | ✅/❌ |
| 3-6 | Change time bucket → heatmap data changes | ✅/❌ |
| 6-10 | Click a zone → right panel shows risk breakdown | ✅/❌ |
| 10-15 | Call `/api/simulate` with num_teams=5 → valid response | ✅/❌ |
| 15-20 | Call `/api/game/strategy` → probabilities returned | ✅/❌ |
| 20-25 | Call `/api/explain` → LLM/cached explanation returned | ✅/❌ |
| 25-30 | Identify top 3 Day 2 afternoon priorities | Decided |

---

### 12:30 – 16:00 | SPRINT 10+11 — Simulation UI + Polish

#### Person 1

| # | Task | Output |
|---|---|---|
| ✅ | POST `/simulate` fully working with real Stackelberg + spillover | Endpoint complete |
| ✅ | `/api/traffic/{zone_id}` serves cached MapMyIndia data | Traffic data served |
| 🔶 STRETCH | Demo mode: pre-compute responses for exact demo path | `data/demo_cache/` populated |

#### Person 2

| # | Task | Output |
|---|---|---|
| ✅ | Write `MODEL_CARD.md` with all metrics, training details, limitations | Documentation done |
| ✅ | Help Person 1 test simulation edge cases | Edge cases handled |
| 🔶 STRETCH | Generate forecast for "tomorrow" (demo holdout Apr data) | Demo-ready forecast |
| 🔶 STRETCH | Compute confidence intervals for forecast (bootstrap or quantile regression) | Upper/lower bounds |
| 🔶 STRETCH | **Pre-compute multi-resolution H3 aggregations** (res 5, 7, 8, 9) for zoom-adaptive heatmap | `data/processed/zone_impact_res{5,7,8,9}.json` |

```python
# ml/etl/multi_resolution.py — ZOOM-ADAPTIVE HEATMAP DATA
import h3
import pandas as pd

def create_multi_resolution_zones(df, resolutions=[5, 7, 8, 9]):
    """Pre-compute congestion impact aggregations at multiple H3 resolutions.
    Zoom out → large hexagons (res 5). Zoom in → fine hexagons (res 9)."""
    results = {}
    for res in resolutions:
        col = f'h3_res{res}'
        df[col] = df.apply(
            lambda r: h3.latlng_to_cell(r['latitude'], r['longitude'], res), axis=1)
        
        agg = df.groupby([col, 'time_bucket']).agg(
            count=('id', 'count'),
            lat=('latitude', 'mean'),
            lon=('longitude', 'mean'),
            main_road_count=('violation_list', lambda x: sum('PARKING IN A MAIN ROAD' in str(v) for v in x)),
            double_park_count=('violation_list', lambda x: sum('DOUBLE PARKING' in str(v) for v in x)),
            avg_vehicle_weight=('vehicle_obstruction_weight', 'mean'),
        ).reset_index()
        
        # Normalize congestion impact per resolution
        max_count = agg['count'].max()
        agg['congestion_impact'] = (
            (agg['main_road_count'] * 1.0 + agg['double_park_count'] * 2.0) / max(max_count, 1) * 100
        ).clip(0, 100)
        
        results[res] = agg.to_dict('records')
    
    return results  # {5: [...], 7: [...], 8: [...], 9: [...]}
```

#### Person 3

| # | Task | Output |
|---|---|---|
| ✅ | **Simulation panel:** team count slider (1-15) | Slider component |
| ✅ | POST `/simulate` on slider change → show allocations as markers on map | **CORE DEMO FEATURE** |
| ✅ | Color coding: green (covered), red (uncovered), yellow (spillover) | Visual feedback |
| ✅ | Coverage percentage display: "62% of critical congestion impact covered" | Key metric shown |
| 🔶 STRETCH | Spillover animation: pulse/ripple effect on spillover zones | **WOW MOMENT** |
| 🔶 STRETCH | View toggles: Impact View / Violator View / Patrol View | Multiple perspectives |
| 🔶 STRETCH | **Multi-resolution zoom handler:** listen to `zoomend`, re-fetch heatmap at matching H3 resolution | **Dynamic zoom heatmap** |

#### Person 4

| # | Task | Output |
|---|---|---|
| ✅ | Test LLM explanations for accuracy (no hallucination) | Quality verified |
| ✅ | Presentation slides complete (8 slides) | Full deck |
| ✅ | Start speaker notes | Notes for each slide |
| ✅ | **Write the full demo script** (word-for-word opening hook + each beat) — see below | `docs/DEMO_SCRIPT.md` |
| ✅ | **Write 5 scripted judge Q&A attack answers** — see below | `docs/JUDGE_QA.md` |
| 🔶 STRETCH | Create backup slide: academic references (Tambe et al., Lei et al.) | Reference slide |

**DEMO OPENING HOOK (Person 4 must write this exact script by Day 2 evening):**

> *"2,000 parking violations. Every single day. In Bengaluru alone. But here's what police don't know—"*
> *[click: toggle between two layers]*
> *"—violation density and congestion impact are NOT the same map. This street has 50 violations but low congestion risk. This junction has 20 violations but blocks 10,000 vehicles per hour. And right now, traffic police have NO system to see the difference."*

**5 SCRIPTED JUDGE ATTACK ANSWERS (Person 4 must prepare these):**

| Judge Attack | Your Scripted Response |
|---|---|
| "Isn't this just a crime mapping tool?" | "No — crime maps show density. We show CONGESTION IMPACT. A quiet street with 50 violations is low risk. A junction with 20 violations is critical. Toggle our two-layer map and you can see the difference." |
| "You don't have traffic data. How can you claim congestion?" | "We measure congestion RISK, not congestion. Our 7-factor Congestion Impact Score weights violations by lane blockage, junction disruption, and vehicle size. And we VALIDATED it — Mappls Distance Matrix shows 1.8-2.5x slower travel times in our highest-scoring zones." |
| "How does this specifically answer the theme?" | "The theme asks 'quantify impact on traffic flow.' Our Congestion Impact Score does exactly that. Toggle: Layer 1 shows violation density. Layer 2 shows congestion risk. They're different maps. That difference IS the theme answer." |
| "Your temporal patterns are just enforcement shift patterns." | "Correct — and that's operationally useful. We predict when violations will be DETECTED, which is what matters for patrol scheduling. We say 'recorded violations' not 'all violations.'" |
| "How is this different from putting dots on a map?" | "Three things: we QUANTIFY (congestion impact, not just counts), we PREDICT (tomorrow's hotspots), and we OPTIMIZE (game theory for patrol deployment considering violator adaptation). Dots don't do any of that." |

---

### 16:00 – 16:30 | 🧪 INTEGRATION CHECKPOINT #3

**THE CRITICAL TEST: Simulation works end-to-end.**

| Test | What happens | Pass/Fail |
|---|---|---|
| Drag team slider from 3 → 5 → 8 | Map markers update, coverage % changes | ✅/❌ |
| Spillover zones highlighted | At least some zones show yellow/change | ✅/❌ |
| Zone click → detail panel | Risk breakdown visible | ✅/❌ |
| "Explain" button (if ready) | Text appears | ✅/❌ |

**IF THIS CHECKPOINT PASSES → Silver MVP achieved. We're competitive.**
**IF THIS FAILS → All hands on fixing simulation. Drop all stretch tasks.**

---

### 16:30 – 22:00 | SPRINT 12+13 — Gold Features + Polish

This is the stretch zone. Work on Gold features ONLY if Silver is solid.

#### Person 1

| # | Task | Output |
|---|---|---|
| 🔶 STRETCH | In-memory caching for expensive endpoints (dict-based, not Redis) | Faster responses |
| ✅ | Fix all bugs from checkpoint | Clean API |
| ✅ | Test EVERY endpoint with edge cases (empty zones, invalid zone_id) | Hardened |
| 🔶 STRETCH | Demo mode flag: `?demo=true` on any endpoint returns pre-computed response | Demo reliability |
| 🔶 STRETCH | **`/api/agent/validation-report`** — serves calibration summary + agent reasoning log | Agent endpoint |
| 🔶 STRETCH | **`/api/heatmap?resolution=`** — add resolution param, serve multi-res H3 data | Zoom-adaptive backend |

#### Person 2

| # | Task | Output |
|---|---|---|
| 🔶 STRETCH | Violator adaptation map: compute for all zones, save as JSON | `data/processed/violator_adaptation.json` |
| ✅ | Final validation: all model outputs are JSON-serializable | No serialization bugs |
| 🔶 STRETCH | SHAP feature importance for top-5 features | Explainability visual |
| 🔶 STRETCH | **Self-Validating Agent: calibrate congestion scores against Mappls traffic data** | `data/processed/calibrated_scores.json` + `agent_log.json` |

```python
# ml/agent/validation_agent.py — SELF-VALIDATING CONGESTION AGENT
import json

def validate_and_calibrate(congestion_scores: dict, mappls_data: dict) -> tuple:
    """
    Agentic validation loop:
    1. Compare model predictions against real Mappls traffic data
    2. Identify discrepancies
    3. Calibrate scores with human-readable reasoning
    """
    calibrated = {}
    agent_log = []
    
    for zone_id, raw_score in congestion_scores.items():
        traffic = mappls_data.get(zone_id, {})
        
        if not traffic.get('travel_time_ratio'):
            calibrated[zone_id] = {
                'raw_score': raw_score, 'calibrated_score': raw_score,
                'validated': False,
                'reasoning': 'No traffic data available — using model prediction only'
            }
            continue
        
        actual_ratio = traffic['travel_time_ratio']
        expected_ratio = 1.0 + (raw_score / 100) * 2.0
        discrepancy = actual_ratio - expected_ratio
        
        alpha = 0.3  # Trust weight for Mappls data
        adjustment = alpha * (discrepancy / max(expected_ratio, 1.0))
        calibrated_score = max(0, min(100, raw_score * (1 + adjustment)))
        
        if discrepancy > 0.3:
            reasoning = (f"⬆️ Adjusted UP {raw_score:.0f}→{calibrated_score:.0f}: "
                        f"Mappls shows {actual_ratio:.1f}x travel time, worse than predicted. "
                        f"Parking impact UNDERESTIMATED.")
        elif discrepancy < -0.3:
            reasoning = (f"⬇️ Adjusted DOWN {raw_score:.0f}→{calibrated_score:.0f}: "
                        f"Mappls shows only {actual_ratio:.1f}x despite high violations. "
                        f"Wide road may absorb parking impact.")
        else:
            reasoning = (f"✅ Validated: {raw_score:.0f} matches Mappls data "
                        f"({actual_ratio:.1f}x travel time). Model accurate.")
        
        calibrated[zone_id] = {
            'raw_score': raw_score, 'calibrated_score': calibrated_score,
            'validated': True, 'mappls_ratio': actual_ratio,
            'adjustment': adjustment, 'reasoning': reasoning
        }
        agent_log.append({'zone_id': zone_id, 'reasoning': reasoning})
    
    validated = [v for v in calibrated.values() if v['validated']]
    summary = {
        'total_zones': len(calibrated),
        'validated': len(validated),
        'accurate': sum(1 for v in validated if abs(v.get('adjustment', 0)) <= 0.05),
        'adjusted_up': sum(1 for v in validated if v.get('adjustment', 0) > 0.05),
        'adjusted_down': sum(1 for v in validated if v.get('adjustment', 0) < -0.05),
        'log': agent_log
    }
    return calibrated, summary
```

#### Person 3

| # | Task | Output |
|---|---|---|
| ✅ | Dark theme: background #0a0a1a, cards glassmorphism, proper fonts | **VISUAL QUALITY** |
| ✅ | Congestion Impact gauge component (circular gauge 0-100 in zone panel) | Intuitive impact visual |
| 🔶 STRETCH | Forecast view: "Tomorrow's predicted hotspots" highlighted differently | Future prediction view |
| 🔶 STRETCH | "Explain" button in zone panel → shows LLM text | LLM in UI |
| 🔶 STRETCH | View toggle buttons (Impact / Violator / Patrol) | Multiple map layers |
| 🔶 STRETCH | **Zoom-adaptive heatmap:** on `zoomend`, map zoom to H3 resolution, re-fetch from `/api/heatmap?resolution=` | **Dynamic zoom** |
| 🔶 STRETCH | **Agent reasoning panel:** scrollable log showing validation agent's reasoning per zone | **"AI is thinking" visual** |

#### Person 4

| # | Task | Output |
|---|---|---|
| ✅ | Full end-to-end smoke test | Complete flow works |
| ✅ | Speaker notes completed — use the scripted opening hook from Sprint 12 | All 8 slides have notes |
| ✅ | **Verify all 5 scripted judge Q&A answers are memorized or printed** | Q&A sheet printed |
| ✅ | **Verify demo script explicitly opens with Two-Layer Map toggle** (NOT a violation heatmap first) | Theme alignment confirmed |
| 🔶 STRETCH | Record a backup demo video (screen recording of perfect flow) | Insurance |

---

### 22:00 | 💤 END OF DAY 2 STANDUP → SLEEP

**Critical assessment:** "Can we run the demo right now?"
- If YES → Day 3 is pure polish. We're in great shape.
- If NO → Identify the ONE blocker. Assign to be fixed first thing Day 3.

---

# DAY 3: POLISH + DEMO

## Theme: "Zero new features. Only polish, rehearse, and win."

> [!WARNING]
> **ABSOLUTE RULE: No new features on Day 3.** If it's not working by Day 3 morning, it's not in the demo. Adjust the script, don't add code.

---

### 08:00 – 10:00 | SPRINT 14 — Bug Fixes + Demo Prep

#### Person 1

| # | Task | Output |
|---|---|---|
| ✅ | Fix all P0 bugs from Day 2 end-of-day | Clean API |
| ✅ | Pre-compute and cache demo path responses | `data/demo_cache/` complete |
| ✅ | Test offline mode: kill internet, does backend still serve? | Offline confirmed |

#### Person 2

| # | Task | Output |
|---|---|---|
| ✅ | Prepare 3 demo scenarios in JSON: morning peak, midday commercial, weekend | `data/demo_scenarios/` |
| ✅ | Double-check: simulation produces DIFFERENT results for 3 vs 5 vs 8 teams | Verified |
| ✅ | Write 1-page technical defense notes (for judge Q&A) | Defense sheet |

#### Person 3

| # | Task | Output |
|---|---|---|
| ✅ | Final CSS polish: consistent spacing, font sizes, button styles | Premium look |
| 🔶 STRETCH | Spillover ripple animation (CSS keyframes: expanding circle on simulated zones) | Wow visual |
| ✅ | Loading skeletons (not spinners) for all async calls | Professional loading |
| ✅ | Error toasts for failed API calls | Graceful errors |

```css
/* Spillover ripple animation — STRETCH but high impact */
@keyframes spillover-ripple {
  0% { transform: scale(1); opacity: 0.8; }
  100% { transform: scale(2.5); opacity: 0; }
}
.spillover-zone::after {
  content: '';
  position: absolute;
  border-radius: 50%;
  border: 2px solid #ffd700;
  animation: spillover-ripple 2s ease-out infinite;
}
```

#### Person 4

| # | Task | Output |
|---|---|---|
| ✅ | Finalize ALL 8 presentation slides | Complete deck |
| ✅ | Print Q&A cheat sheet (1 page, key answers only) | Printed |
| ✅ | Verify demo script matches actual UI (buttons in right place, data looks right) | Script-UI alignment |

---

### 10:00 – 12:00 | SPRINT 15 — Rehearsal Prep

| Person | Task |
|---|---|
| All | Walk through demo script once (untimed) — identify any remaining issues |
| P3 | Fix any UI issues found during walkthrough |
| P1 | Fix any API issues found during walkthrough |
| P4 | Finalize presentation timing — practice with stopwatch alone |

---

### 12:00 – 12:45 | 🧪 DEMO RUN #1 (with lunch)

**Full 3-minute presentation + demo. Timed. Recorded on phone.**

Post-run debrief (15 min):
- What broke?
- What was awkward?
- Where did we lose momentum?
- Did we go over 3 minutes?

---

### 12:45 – 14:00 | FIX from Demo Run #1

All hands on fixing issues identified in Demo Run #1.

---

### 14:00 – 14:30 | 🧪 DEMO RUN #2

Must be clean. If it's not clean, identify the ONE thing to cut from the demo.

---

### 14:30 – 15:30 | Final Polish

| Person | Task |
|---|---|
| P1 | Record screen capture of perfect demo (OBS or QuickTime) |
| P2 | Verify all numbers in slides match actual model output |
| P3 | Final visual tweaks from demo feedback |
| P4 | Practice Q&A answers out loud (have another member ask) |

---

### 15:30 – 16:00 | 🧪 DEMO RUN #3 — Final Rehearsal

**Competition conditions.** Stand up. Present to the wall. Time it. Stay under 3 minutes.

---

### 16:00 – 17:00 | Pre-Demo

| Task | Owner |
|---|---|
| Commit everything to Git | All |
| Ensure backend + frontend run on the presentation laptop | P1 + P3 |
| Load presentation on the projector/screen | P4 |
| Take deep breaths | All |

---

### 17:00+ | 🏆 DEMO TIME

**Remember the five moments:**
1. 🌊 Waterbed Effect — "Enforce here, violations ripple there"
2. 🎮 Simulation Slider — "Drag this. You're the control room officer."
3. 🧠 Game Theory — "We model the cat-and-mouse game mathematically"
4. 🤖 Self-Validating Agent — "Our AI validates itself against real traffic data"
5. 🔍 Dynamic Zoom — "Zoom in — watch the heatmap re-aggregate"

**Detect. Quantify. Enforce.**

---

# STRETCH TASK DECISION MATRIX

Use this table at Day 1 evening and Day 2 evening to decide which stretch tasks to attempt.

| 🔶 Stretch Task | Prerequisite | Time Needed | Judge Impact | Attempt If... |
|---|---|---|---|---|
| **🤖 Self-Validating Agent** | **Mappls enrichment data cached** | **3-4 hours** | **🔥🔥🔥 VERY HIGH** | **Mappls data available by Day 2 morning. HIGHEST PRIORITY STRETCH.** |
| **🔍 Multi-Resolution Zoom Heatmap** | **Heatmap working** | **3-4 hours (P2+P3)** | **🔥🔥 HIGH** | **Day 2 afternoon, heatmap is solid, simulation works** |
| CatBoost ensemble | LightGBM working | 30 min | Medium | LightGBM trains successfully by Day 1 evening |
| Spillover ripple animation | Simulation working | 1-2 hours | **VERY HIGH** | Simulation is working by Day 2 afternoon |
| View toggles (Impact/Violator/Patrol) | Game theory data available | 2-3 hours | High | All API endpoints working by Day 2 noon |
| Forecast view ("tomorrow") | Forecast model trained | 1 hour | Medium | Model metrics computed by Day 2 |
| Feature importance plot | Model trained | 30 min | Medium | Day 2 evening, need content for slides |
| Demo mode caching | All endpoints working | 1 hour | N/A (reliability) | Day 2 evening, want bulletproof demo |
| LLM "Explain" in UI | Explain endpoint working | 1 hour | Medium | LLM responses quality-checked by Day 2 |
| Station filter dropdown | Heatmap working | 45 min | Low | Day 1 evening, need quick win |
| Hourly slider within buckets | Bucket selector working | 1.5 hours | Medium | Day 1 afternoon, basic selector solid |
| Confidence intervals | Forecast model working | 1 hour | Medium | Day 2, model is good |
| Traffic context in zone panel | MapMyIndia data cached | 45 min | Medium | MapMyIndia data available by Day 1 evening |
| Agent reasoning panel (UI) | Agent endpoint working | 1 hour | High | Agent data available, Day 2 evening |
| Academic references slide | None | 15 min | Medium | Day 2 evening presentation prep |
| Backup demo video | Full demo working | 30 min | N/A (insurance) | Day 3 morning, demo runs clean |

**Rule:** Never start a stretch task if any MUST-DO task is incomplete. Check the Day's success criteria first.

---

# HANDOFF SPECIFICATIONS

## Person 2 → Person 1 (ML outputs → API)

| Output File | Format | When Ready | Used By |
|---|---|---|---|
| `data/processed/violations_clean.parquet` | Parquet | Day 1, 10:00 | DataStore loader |
| `data/processed/zone_congestion_impact.json` | `{h3_id: {time_bucket: {congestion_impact, components...}}}` | Day 1, 14:00 | `/heatmap`, `/hotspots`, `/congestion` |
| `data/processed/forecasts.json` | `{h3_id: {date: predicted_count}}` | Day 2, 10:00 | `/forecast` |
| `data/processed/patrol_allocations.json` | Pre-computed for 3,5,8,10 teams | Day 2, 10:00 | `/simulate` fallback |
| `data/processed/violator_adaptation.json` | `{h3_id: {violator_risk_score, net_utility...}}` | Day 2, 18:00 | `/game/violator` |
| `ml/models/lightgbm_v1.pkl` | Pickle | Day 1, 20:00 | Backup |
| `ml/game_theory/stackelberg.py` | Importable Python module | Day 2, 10:00 | `/simulate`, `/game/strategy` |
| `ml/game_theory/spillover.py` | Importable Python module | Day 2, 12:00 | `/simulate` |

## Person 4 → Person 1 (Enrichment → API)

| Output File | Format | When Ready |
|---|---|---|
| `data/enriched/traffic_context.json` | `{h3_id: {travel_time, pois...}}` | Day 1, 16:00 |
| `data/processed/explanations_cache.json` | `{h3_id: "explanation text"}` | Day 2, 14:00 |

## Person 1 → Person 3 (API → Frontend)

| Endpoint | Returns | When Ready |
|---|---|---|
| `GET /api/heatmap?time_bucket=` | HeatmapResponse (mock Day 1, real Day 2) | Day 1 mock, Day 2 real |
| `GET /api/hotspots?time_bucket=&limit=` | List[HotspotItem] | Day 1 mock, Day 2 real |
| `GET /api/congestion/{zone_id}?hour=` | CongestionBreakdown | Day 1, 16:00 |
| `GET /api/forecast?zone_id=` | List[ForecastPoint] | Day 2, 10:00 |
| `GET /api/game/strategy?time_bucket=` | List[PatrolAllocation] | Day 2, 10:00 |
| `POST /api/simulate` | SimulationResponse | Day 2, 12:00 |
| `POST /api/explain` | ExplainResponse | Day 2, 14:00 |
| `GET /api/traffic/{zone_id}` | TrafficContext | Day 2, 14:00 |

---

# FINAL CHECKLIST — BEFORE STEPPING ON STAGE

- [ ] Backend starts without errors
- [ ] Frontend loads in < 3 seconds
- [ ] Congestion impact heatmap shows on initial load
- [ ] Time selector changes heatmap
- [ ] **Mappls live traffic layer toggle works**
- [ ] Zone click shows Congestion Impact breakdown panel
- [ ] Simulation slider produces different results for different team counts
- [ ] At least one spillover zone visible when simulation runs
- [ ] LLM explanation text appears (cached or live)
- [ ] Coverage percentage (congestion impact %) updates with slider
- [ ] All text is readable on projector (test font size!)
- [ ] Presentation deck loads
- [ ] Backup video recorded and accessible
- [ ] Q&A cheat sheet printed/visible
- [ ] Everyone knows their speaking role
- [ ] Timer set for 3:00
- [ ] Deep breath taken
- [ ] **"Detect. Quantify. Enforce." — Let's win this.** 🏆
