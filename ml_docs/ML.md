

---

# ParkVision-Saathi — Complete ML System Audit & Technical Documentation

*Generated from live source code and real model artifacts. Every claim is traced to a specific file.*

---

## Section 1: Problem Understanding

### Plain English

Bengaluru Traffic Police record roughly 2,000 illegal parking violations per day. The problem they cannot currently answer is: **of all those violations, which ones are actually choking traffic, and where should the limited patrol teams go tomorrow?**

Without this, patrol deployment is intuition-based. Teams go where they've always gone, or where complaints pile up — not where they would do the most good. Violations that look small in volume might be blocking a junction approach, and violations that look large might be on a side street that barely matters to traffic flow.

The ML system answers three questions in sequence:
1. **QUANTIFY** — which violations cause how much congestion damage? (Congestion Impact Score)
2. **PREDICT** — which zones will be the top hotspots tomorrow? (LightGBM + CatBoost ensemble)
3. **OPTIMIZE** — given a fixed number of patrol teams, where should they go, and where will violations migrate if they do? (Stackelberg game theory + waterbed simulation)

### Technically

The dataset is a 298,450-row event log of police-recorded violations, Nov 2023–Apr 2024, with no traffic speed/flow columns. The system constructs a proxy for traffic impact by combining violation-type severity weights, spatial context (junction proximity, road class), vehicle obstruction sizes, and one externally measured signal — MapMyIndia travel-time ratios — into a deterministic 0-100 Congestion Impact Score (CIS). The CIS is then compared against that real Mappls ratio by a self-validating agent that calibrates its own outputs and logs plain-English reasoning.

Forecasting is a supervised regression task: predict the hourly violation count per ~550m grid cell using a dense autoregressive time series with spatial-neighbor features. Game theory produces optimal patrol probabilities per zone under the Stackelberg security game (police as leader, violators as followers), with a waterbed simulation showing where violations displace when an area is enforced.

**The decision ultimately made** is: which zones to assign patrol teams to on the next shift. The value is converting 2,000 raw events/day into a prioritized, explainable deployment order that a control room officer can act on.

---

## Section 2: Prediction Analysis

The system makes five distinct prediction/scoring outputs. None are classification of a single binary label — they span regression, scoring, ranking, and economic modeling.

### 2.1 Congestion Impact Score (CIS)

| Property | Value |
|---|---|
| **Type** | Deterministic scoring (not learned) |
| **Target variable** | None trained — rule-based weighted sum |
| **Output range** | 0–100 continuous |
| **Output label** | `congestion_impact` per (h3_id, time_bucket) |
| **Granularity** | H3 res-9 zone (~0.1 km²) × 5 time buckets |
| **How used** | Primary heatmap layer, zone ranking, agent calibration input |

This is the core "QUANTIFY" answer to the theme. It is not a model prediction in the ML sense — it is a deterministic formula with auditable, explainable weights. It is scored offline and served from a JSON artifact (2,527 zones, 8,632 entries).

**Formula:**
```
CIS = 100 × (0.30 × lane_blockage
           + 0.25 × intersection_impact
           + 0.25 × traffic_degradation
           + 0.10 × access_blockage
           + 0.10 × vehicle_size)
```

Each component is normalized to [0,1] against the corpus maximum. The result is bounded [0,100].

### 2.2 Enforcement Risk Score

| Property | Value |
|---|---|
| **Type** | Deterministic weighted scoring |
| **Output** | 0–100 per (grid_cell_id, hour) |
| **Output label** | `risk_score`, tier label LOW/MEDIUM/HIGH/CRITICAL |
| **Granularity** | ~500m grid cell × hour-of-day |
| **How used** | Stackelberg patrol allocation, what-if simulation |

Distinct from CIS. This captures enforcement-priority signals (density, repeat offenders, validation trust, vehicle weight) rather than traffic-flow impact. Weights: density 30%, repeat 20%, road importance 15%, peak hour 15%, validation trust 10%, heavy vehicle 10%.

### 2.3 Hourly Violation Count Forecast

| Property | Value |
|---|---|
| **Type** | Supervised regression |
| **Target variable** | `violation_count` (integer, zero-inflated) |
| **Models** | LightGBM (Poisson) + CatBoost (RMSE), rank-blended |
| **Blend weights** | 0.85 LightGBM + 0.15 CatBoost |
| **Output** | Predicted hourly violation count per grid cell |
| **Stored in** | SQLite `forecast_predictions` (115,392 rows, April test set) |
| **Headline metric** | Precision@10 daily 67.5–70.0% (up from 28.7% baseline) |

This is the only trained ML model in the pipeline. It predicts which grid cells will have the most violations in the next hour, which translates to the "PREDICT" pillar of the demo.

### 2.4 Patrol Probability (Stackelberg)

| Property | Value |
|---|---|
| **Type** | Algorithmic optimization (game-theoretic) |
| **Output** | Normalized patrol probability per (grid_cell_id, hour), sum = 1.0 per hour |
| **Formula** | `p_i = (risk_i^1.5 / (1 + 0.3 × patrol_count_i)) / Σ_j(...)` |
| **How used** | Team allocation (Blotto), violator utility, spillover simulation |

### 2.5 Calibrated Congestion Impact (Agent)

| Property | Value |
|---|---|
| **Type** | Rule-based calibration |
| **Output** | `calibrated_score` per zone (optional field in `CongestionBreakdown`) |
| **Coverage** | 10 of 2,527 zones (those with real Mappls travel-time data) |
| **Formula** | `calibrated = clamp(CIS × (1 + 0.3 × (actual_ratio - expected_ratio) / max(expected_ratio, 1.0)), 0, 100)` |

---

## Section 3: Dataset Analysis

### Dataset Purpose

A single operational dataset: anonymized parking/traffic violation records from Bengaluru Traffic Police, captured via enforcement devices, Nov 2023–Apr 2024.

**Critical caveat:** the dataset contains zero traffic flow data (no speed, queue length, road capacity, or travel time). All congestion signals are proxies constructed from violation characteristics. The one externally-measured traffic signal is the MapMyIndia travel-time ratio, obtained via API and applied to the top ~15 hotspot zones.

### Column Dictionary

| Column | Meaning | Data Type | Used by ML? | Notes |
|---|---|---|---|---|
| `id` | Unique violation id | string | No | Dropped after dedup check |
| `latitude` | Event latitude | numeric string | Yes — CIS, DBSCAN, grid | 100% complete |
| `longitude` | Event longitude | numeric string | Yes — CIS, DBSCAN, grid | 100% complete |
| `location` | Reverse-geocoded address | string | Partially — pincode extraction | 1.02% missing |
| `vehicle_number` | Anonymized vehicle id | string | Yes — repeat-offender feature | 100% complete |
| `vehicle_type` | Original vehicle class | string | Yes — severity/obstruction weight | 100% complete |
| `description` | Free text | string | No | 100% empty, dropped |
| `violation_type` | JSON-like list of violation labels | string | Yes — CIS components, severity | 100% complete, multi-label |
| `offence_code` | Numeric codes matching violation_type | string | No (in current pipeline) | Dropped |
| `created_datetime` | UTC creation timestamp | timestamp string | Yes — all temporal features | 100% complete |
| `closed_datetime` | Close timestamp | string | No | 100% empty, dropped |
| `modified_datetime` | Last modified UTC | timestamp string | No (used for QA only) | 100% complete |
| `device_id` | Capture device id | string | No | Dropped in ETL |
| `created_by_id` | Officer/user id | string | No | Dropped |
| `center_code` | Traffic center code | numeric string | No | 3.77% missing (Kodigehalli) |
| `police_station` | Station name | string | Yes — station label in CIS, DBSCAN | 0.002% missing |
| `data_sent_to_scita` | SCITA integration flag | boolean string | No | Dropped |
| `junction_name` | Named junction or "No Junction" | string | Yes — intersection_impact, junction_flag | 0.002% missing |
| `action_taken_timestamp` | Enforcement action time | timestamp | No | 100% empty, dropped |
| `data_sent_to_scita_timestamp` | SCITA send timestamp | timestamp | No | 85.9% missing |
| `updated_vehicle_number` | Corrected vehicle id after validation | string | No | 42.0% missing |
| `updated_vehicle_type` | Corrected vehicle type after validation | string | Yes — preferred over vehicle_type when present | 42.0% missing |
| `validation_status` | Workflow outcome (approved/rejected/…) | string | Yes — validation_trust feature | 42.0% missing (not random — recent months unvalidated) |
| `validation_timestamp` | Validation time UTC | timestamp | No | 42.0% missing |

**Derived columns produced by ETL** (`data/load_and_clean.py`):

| Column | Source | How Computed |
|---|---|---|
| `hour` | `created_datetime` → IST | `.dt.hour` after UTC→IST conversion |
| `day_of_week` | `created_datetime` | Mon=0 |
| `month` | `created_datetime` | 1–12 |
| `date` | `created_datetime` | IST date |
| `is_weekend` | `day_of_week` | 1 if day ∈ {5,6} |
| `is_peak` | `hour` | 1 if hour ∈ {8,9,10,17,18,19} |
| `time_bucket` | `hour` | night/morning_peak/midday/afternoon |
| `pincode` | `location` | regex `Pin-(\d{6})` |
| `grid_cell_id` | `latitude`, `longitude` | floor(lat/0.005) × floor(lon/0.005) → "latcell_loncell" |
| `grid_lat` / `grid_lon` | `grid_cell_id` | cell centroid |
| `vehicle_severity` | `updated_vehicle_type` or `vehicle_type` | lookup table, range 0.1–1.0 |
| `validation_trust` | `validation_status` | approved=1.0, pending=0.5, rejected=0.1, NaN=0.3 |
| `primary_violation` | `violation_type` | first item from parsed list |
| `vehicle_type_final` | prefers `updated_vehicle_type` | fill → 0.4 default if unknown |

**ETL-level columns added by CIS build** (`ml/congestion/build_artifact.py`):

| Column | Source | How Computed |
|---|---|---|
| `h3_id` | `latitude`, `longitude` | `h3.latlng_to_cell(lat, lon, 9)` — H3 res-9 |
| `time_bucket` | `hour` → IST | 5 buckets after temporal-cliff guard (≥16:00 dropped) |
| `violation_tuple` | `violation_type` | parsed list of uppercase strings |
| `is_main_road` / `is_double_park` | `violation_tuple` | membership test |
| `is_junction` | `violation_tuple` | in JUNCTION_VIOLATIONS set |
| `is_access` | `violation_tuple` | in ACCESS_VIOLATIONS set |
| `obstruction_weight` | `updated_vehicle_type` or `vehicle_type` | VEHICLE_OBSTRUCTION dict, range 0.5–2.0 |
| `is_named_junction` | `junction_name` | not in {"NO JUNCTION", "NULL", ""} |

### Missing Values

| Column | Missing % | Handling | Reason |
|---|---|---|---|
| `validation_status` | 41.97% | → `validation_trust` = 0.3 (DEFAULT_TRUST) | Missingness is time-dependent (Feb–Apr unvalidated); default 0.3 treats unknown as "below average confidence" rather than dropping them, preserving full spatial coverage |
| `updated_vehicle_type` | 41.97% | falls back to `vehicle_type` | Validation-corrected type is more accurate but not always present |
| `location` | 1.02% | `pincode` = None | Pincode used only for display/labeling |
| `junction_name` | 0.002% | treated as "No Junction" | Negligible; correct default behavior |
| lag features (forecast) | first 168h per cell | rows dropped from training | True lags require 168 prior observations; unavoidable for any window-based model |

### Data Quality Issues

**Temporal recording bias (critical, acknowledged in all code):** 85% of records are created between 00:00–15:00 IST. This likely reflects enforcement shift patterns (officers log violations during their shift), not actual violation timing. The CIS pipeline excludes hours ≥16:00 IST via the `TEMPORAL_CLIFF_HOUR_IST = 16` guard. All forecasting documentation explicitly calls this "predicted detection hotspots" not "actual violation timing."

**Validation censoring:** recent months (Feb–Apr) are almost entirely unvalidated. The pipeline assigns `validation_trust = 0.3` to these rows — not 0 (which would exclude them) and not 1.0 (which would falsely treat them as high-quality). Validation trust is used as a feature, not as a filter.

**Zero-inflation in the dense forecast grid:** the dense 2.18M-row training matrix is 96.83% zeros (most (cell, hour) slots have no violations). Poisson LightGBM handles this natively; CatBoost required RMSE objective instead to avoid negative-R² blow-ups from the exp-link.

**Multi-label violations:** one row can carry 2–12 violation labels. The CIS pipeline counts membership (one row contributes at most 1 to each category bucket) to avoid inflating counts for rows with many labels.

**Vehicle type corrections:** 6,169 rows (3.56% of validated rows) had vehicle type changed during validation. The pipeline always prefers `updated_vehicle_type`.

---

## Section 4: Feature Engineering

The features are documented for the forecast model (the one trained ML model). The CIS scoring uses its own directly-computed values described under Section 3 derived columns.

### Raw Features (passed through from ETL)

| Feature | What it is | Why it helps |
|---|---|---|
| `grid_lat` | Centroid latitude of the ~550m grid cell | Encodes geographic location; the model learns that certain latitudes (central Bengaluru) have persistently higher violation rates |
| `grid_lon` | Centroid longitude | Same — captures east-west commercial district patterns |
| `hour` | IST hour of day (0–23) | Strong predictor; violations concentrate in enforcement hours. Treated as categorical by CatBoost |
| `day_of_week` | Mon=0…Sun=6 | Sunday has ~17% more records than Monday; weekday vs weekend enforcement patterns differ |
| `month` | 1–12 | Seasonal trend; Dec–Jan is the highest-volume period |
| `is_weekend` | Binary (0/1) | Categorical summary of day_of_week |
| `is_peak` | 1 if hour ∈ {8–10, 17–19}, else 0 | Captures the known morning peak enforcement window |
| `is_data_rich_hour` | 1 if hour ∈ {0–15}, else 0 | Guards the temporal cliff; separates the 99% of data from the 1% |
| `junction_flag` | Per-cell constant: 1 if majority of records at this cell had a named junction | Static zone characteristic; junction cells tend to have persistent enforcement activity |
| `mean_vehicle_severity` | Per-cell mean of the ETL's 0.1–1.0 severity weight | Static zone characteristic; areas with heavier vehicles have higher obstruction baselines |
| `mean_validation_trust` | Per-cell mean validation trust (0.1–1.0) | Feature importance rank #3 — cells with higher approval rates likely have more reliable, consistent enforcement patterns |
| `heavy_vehicle_ratio` | Fraction of each cell's records where `vehicle_severity ≥ 0.6` | Proxy for commercial zone character |

### Cyclical Temporal Encodings (engineered)

These solve the "midnight boundary" problem: `hour=23` and `hour=0` are adjacent in time but distant in raw integer encoding.

| Feature | Formula | Why |
|---|---|---|
| `sin_hour` | sin(2π × hour / 24) | Continuous encoding; hour 23 and hour 0 are properly adjacent |
| `cos_hour` | cos(2π × hour / 24) | Pair with sin_hour; together uniquely identify any hour |
| `sin_dow` | sin(2π × day_of_week / 7) | Day boundary (Sun→Mon) is smooth |
| `cos_dow` | cos(2π × day_of_week / 7) | Pair with sin_dow |
| `sin_month` | sin(2π × month / 12) | Dec→Jan boundary is smooth |
| `cos_month` | cos(2π × month / 12) | Pair with sin_month |

### Autoregressive Lag Features (engineered, on dense grid)

These are the core temporal memory of the model. They are only valid and physically meaningful on the **dense** grid (where every hourly slot exists). On the old sparse grid, "lag_1" meant "previous recorded observation," which could be days earlier.

| Feature | Formula | Why | Lag semantics |
|---|---|---|---|
| `lag_1` | `groupby(cell).shift(1)` on dense grid | The most recent hourly count — if violations just happened, they're likely to continue | Exactly 1 clock hour ago |
| `lag_24` | `groupby(cell).shift(24)` | Same day-of-week/hour last day — strong daily seasonality | Exactly 24 hours ago |
| `lag_168` | `groupby(cell).shift(168)` | Same hour exactly one week ago | Exactly 168 hours (7 days) ago |

All lags are **strictly past** (shift(k ≥ 1)) — the dense grid guarantees k=1 is exactly 1 clock hour, not just 1 recorded event.

### Rolling Window Features (engineered, strictly past)

Each rolling stat is computed on a **pre-shifted** series (`shift(1)` before `.rolling()`), so the window for target hour t covers only t-1 down to t-window.

| Feature | Formula | Window | Why |
|---|---|---|---|
| `rolling_mean_24h` | mean(count[t-24 : t-1]) | 24h trailing | Short-term trend; is today tracking above or below recent hours? |
| `rolling_std_24h` | std(count[t-24 : t-1]) | 24h trailing | Volatility over the last day; high-std cells are less predictable |
| `rolling_mean_168h` | mean(count[t-168 : t-1]) | 7-day trailing | Weekly baseline for this cell; normalizes the violation_rate spike detector |
| `rolling_std_168h` | std(count[t-168 : t-1]) | 7-day trailing | Weekly volatility; important for separating noisy one-off spikes from patterns |

### Spike Detector (derived from strictly-past features)

| Feature | Formula | Why |
|---|---|---|
| `violation_rate` | `lag_1 / rolling_mean_168h` if rolling_mean_168h > 0 else 1.0 | "How much higher than the weekly normal was the last hour?" — a spike detector. Neither numerator nor denominator contains the current target t. Feature importance rank #12. |

### Spatial Feature (engineered, strictly past)

| Feature | Formula | Why |
|---|---|---|
| `spatial_lag_1` | mean over grid-Moore neighbors j of count_{j, t-1} | "What happened in the surrounding cells one hour ago?" — captures spatial contagion (a traffic jam in one cell often spreads to neighboring cells). Uses t-1, never t. |

**Neighbor definition:** The violation data lives on a ~550m lat/lon lattice (GRID_RESOLUTION = 0.005°). The 8-cell Moore neighbourhood (±1 on both axes) gives consistent adjacency for 561/601 cells with mean degree 4.34. H3 res-9 k-ring=1 was measured but found inconsistent (only 275/601 cells matched) because the ~550m grid straddles the H3 res-9 ~330m cell size at k-ring boundary — documented deviation from the blueprint, not a silent assumption.

### Feature Importance (LightGBM v2, from `models/feature_importance.txt`)

| Rank | Feature | Score | Interpretation |
|---|---|---|---|
| 1 | `rolling_mean_168h` | 6339 | Weekly baseline — the most predictive single signal |
| 2 | `rolling_std_168h` | 5355 | Weekly volatility — how noisy is this cell? |
| 3 | `mean_validation_trust` | 5342 | Zone-level data quality — reliable zones are more forecastable |
| 4 | `hour` | 4764 | Time-of-day pattern |
| 5 | `rolling_mean_24h` | 4653 | Recent trend |
| 6 | `mean_vehicle_severity` | 4417 | Zone commercial character |
| 7–8 | `grid_lat` / `grid_lon` | 4358 / 4112 | Geographic location — persistent spatial patterns |
| 9 | `rolling_std_24h` | 4039 | Recent volatility |
| 10 | `spatial_lag_1` | 3971 | Neighbor spillover |
| 11 | `heavy_vehicle_ratio` | 3778 | Commercial zone proxy |
| 12 | `violation_rate` | 3099 | Spike detector |
| 13–25 | Cyclical + lagged features | 282–2570 | Supporting temporal signals |

Notable: `lag_1`, `lag_24`, `lag_168` rank 17, 14, 15 respectively — important but not dominant. The weekly rolling mean and zone-level static features carry the most weight.

---

## Section 5: ML Pipeline

```
Raw CSV (298,450 rows, 24 cols)
      │
      ▼ data/load_and_clean.py
┌─────────────────────────────────────────────────────────┐
│ PHASE 1 — ETL                                            │
│  • UTC→IST timestamp conversion                          │
│  • violation_type list parsing                           │
│  • vehicle type preference (updated > original)          │
│  • grid_cell_id: floor(lat/0.005)_floor(lon/0.005)       │
│  • vehicle_severity lookup (0.1–1.0 scale)               │
│  • validation_trust lookup (1.0/0.5/0.1/0.3)            │
│  • pincode regex extraction                              │
│  Output → SQLite violations table (298,445 rows)         │
└─────────────────────────────────────────────────────────┘
      │
      ├──────────────────────────┬──────────────────────────┐
      ▼                          ▼                          ▼
┌────────────────┐  ┌─────────────────────────┐  ┌──────────────────┐
│ BRANCH A       │  │ BRANCH B                │  │ BRANCH C         │
│ CIS Pipeline   │  │ Forecast Pipeline       │  │ Enforcement       │
│ (QUANTIFY)     │  │ (PREDICT)               │  │ Pipeline         │
└────────────────┘  └─────────────────────────┘  │ (OPTIMIZE input) │
      │                          │               └──────────────────┘
      ▼                          │                         │
ml/congestion/               data/regularize_grid.py       ▼
build_artifact.py                  │               ml/risk_score.py
      │             ┌──────────────┘               ml/hotspot_dbscan.py
      │             │                                      │
      ▼             ▼                                      ▼
H3 lat/lon    Dense hourly grid               risk_scores table
→ res-9 zone  (601 cells × 3,624h             (grid_cell_id × hour)
  buckets     = 2,178,024 rows, 3.17%
  agg. per    nonzero, zero-filled)
  (zone,              │
  bucket)             ▼
      │      ml/forecast/feature_engineering.py
      │             │
      │      27 features (lags, rolling,
      │      cyclical, spatial, zone meta)
      │             │
      │             ▼
      │      ml/forecast/train_model.py
      │             │
      │      LightGBM (Poisson) early-stop on March
      │      CatBoost (RMSE) early-stop on March
      │      blend weight tuned for P@10 on March val
      │      evaluated once on April test
      │             │
      │      Output → forecast_predictions (115,392)
      │              models/lightgbm_v2.pkl
      │              models/catboost_v1.cbm
      │              models/ensemble_config.json
      │              models/MODEL_CARD.md
      │
      │ (traffic_context_h3.json join for ~10 zones)
      ▼
zone_congestion_impact.json
(2,527 H3 zones, 8,632 entries)
      │
      ▼
ml/agent/validation_agent.py
  GUARD: only zones with is_traffic_degradation_defaulted == False
  Formula: calibrated = clamp(CIS × (1 + adj), 0, 100)
      │
      ▼
calibrated_scores.json (10 zones)
agent_log.json
      │
      └──────────────────────────────────────────────────┐
                                                         ▼
                                               BRANCH C (continues)
                                               ml/game/stackelberg.py
                                                 patrol_prob ∝ risk^1.5
                                                 fatigue decay: /(1+λ×hist)
                                                      │
                                               ml/game/expected_utility.py
                                                 violator net benefit
                                                 sigmoid VRS
                                                      │
                                               ml/game/spillover.py
                                                 KD-tree k=6 neighbors
                                                 waterbed displacement
                                                      │
                                                      ▼
                                                Backend (FastAPI)
                                                In-memory DataStore
                                                REST API → Frontend
```

**Data flow summary:** Raw CSV → cleaned SQL → (a) offline CIS computation, (b) dense grid → feature engineering → ensemble training, (c) risk scoring + game theory. All artifacts are pre-computed JSON or SQLite and served in-memory at API startup. No model inference at request time (except in the forecast proxy endpoint).

---

## Section 6: Model Analysis

### 6.1 Congestion Impact Score — Deterministic Weighted Scoring

Not a trained ML model. A deterministic, auditable formula.

**Why this design was chosen:** The dataset has no traffic ground truth to train on (no speed data, no queue measurements). Any supervised model claiming to predict "congestion" would be learning from proxies, not labels. A transparent formula is honest, defensible to judges, explainable to police officers, and cannot overfit.

**Hyperparameters (weights, from `ml/congestion/impact_score.py`):**

| Component | Weight | Rationale |
|---|---|---|
| Lane blockage | 0.30 | Directly removes lane capacity (main road + double park) |
| Intersection impact | 0.25 | Junction violations reduce green-phase throughput |
| Traffic degradation | 0.25 | MapMyIndia travel-time ratio — the only externally measured signal |
| Access blockage | 0.10 | Bus stop/school/hospital obstruction, more localized impact |
| Vehicle size | 0.10 | Heavier vehicles block more space — amplifier, not primary driver |

Weights must sum to exactly 1.0 (enforced by import-time `assert` and a Pydantic validator on every served response). A sixth `severity` value is reported for transparency but deliberately excluded from the sum.

**Advantages:** fully explainable, no overfitting, deterministic, offline-safe, zero training data needed.
**Disadvantages:** weights are expert-set (no empirical calibration against measured congestion), normalization against corpus maxima means scores are relative within this dataset (not absolute traffic impact), and the traffic_degradation component only resolves to a real measurement for ~10 of 2,527 zones.

### 6.2 LightGBM (Poisson Regressor)

**Why LightGBM:** count data with heavy skew (mostly zeros, occasional spikes up to 15) is the natural target for a Poisson-objective gradient boosting model. LightGBM handles zero-inflation better than naive regression, trains fast enough to iterate in hours, and produces interpretable feature importance.

| Hyperparameter | Value | Rationale |
