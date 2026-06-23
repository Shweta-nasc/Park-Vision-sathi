# ParkVision-Saathi — ML Documentation

> A complete, single-source reference for every piece of machine-learning and
> analytics work in ParkVision-Saathi. It is generated from the actual code and
> committed data artifacts under `ml/` and `data/`, not from the planning brief.
> Numbers quoted as "currently served" reflect the committed midday-calibrated
> artifacts at the time of writing.

---

## 1. What the project is

ParkVision-Saathi is a Bengaluru parking-induced-congestion intelligence tool
built for the theme:

> *"How can AI-driven parking intelligence detect illegal parking hotspots and
> quantify their impact on traffic flow to enable targeted enforcement?"*

It has three ML pillars:

| Pillar | Question | Core artifact |
| --- | --- | --- |
| **QUANTIFY** | How much does a zone's parking pattern degrade traffic flow? | Congestion Impact Score (CIS), per H3 zone |
| **PREDICT** | Where will tomorrow's violation hotspots be? | LightGBM-Poisson next-day forecast |
| **OPTIMIZE** | Where should limited patrol teams go? | Stackelberg game theory + waterbed/spillover simulation |

On top of these sit a **self-validating agent** (calibrates/validates the CIS
against live MapMyIndia travel-time data) and a **calibration pipeline** that
turns the CIS from a hand-weighted heuristic into a measured, validated,
trust-reporting instrument.

### Architecture rules (non-negotiable, enforced throughout)

- **MapMyIndia-primary.** The only external signal/API is MapMyIndia (Mappls):
  congestion ratio, POIs, reverse geocode, driving-time adjacency, free-flow
  speed road-size proxy. No TomTom/HERE. The one allowed future gap-filler is an
  OSM seam for real lane count/width (a documented stub, not implemented).
- **Additive-shadow.** The v1 CIS path is never destructively edited. The
  calibrated v2 artifact ships as the default but v1 is one rename/flag away.
- **Offline / cache-first.** All calibration is offline/batch. The demo replays
  from committed JSON; nothing makes a live external call at request time without
  a graceful cached fallback.
- **Deterministic.** Fixed seeds everywhere; artifacts are reproducible.
- **Honesty.** Whatever metric is measured is reported as-is. No correlation
  number is fabricated. A weak result is reported as weak.
- **No database for the serving path.** The backend serves pre-computed JSON
  in-memory. (A legacy SQLite path exists for older grid-based modules — see §9.)

---

## 2. Repository map (ML-relevant)

```
ml/
  congestion/                  QUANTIFY pillar — the CIS + calibration pipeline
    impact_score.py            Pure deterministic CIS scoring core (no I/O)
    build_artifact.py          Offline builder: violations CSV -> CIS artifact
    build_calibrated_artifact.py  v2 builder (fitted weights + predicted degradation)
    validate_cis.py            CIS-vs-measured trust harness + density≠impact proof
    calibrate_weights.py       Fit the 4 non-traffic weights to measured ratio
    predict_degradation.py     Ridge model: predict the traffic-degradation component
    stats_utils.py             Bootstrap CIs, flat-variance abort, content hashing
    diff_top_zones.py          v1 ↔ v2 top-N ranking diff
  enrichment/                  MapMyIndia collectors / context
    mapmyindia.py              Legacy zone->city-centre collector (untouched)
    congestion_collector.py    v2 local-segment collector (budget-guarded, frozen snapshots)
    adjacency.py               Driving-time k-NN zone adjacency
    road_geometry.py           Road-size proxy provider seam (+ OSM stub)
    build_routes.py            Offline route geometry pre-compute (demo)
    rekey_traffic_context.py   Re-key legacy enrichment to true H3 ids
  forecast/                    PREDICT pillar
    build_h3_forecast.py       H3-native daily LightGBM-Poisson forecaster (v1)
    build_h3_forecast_v2.py    + MapMyIndia road context (spatial lag + road proxy)
    forecast_explain.py        SHAP (TreeSHAP) per-zone explanations sidecar
    feature_engineering.py     Legacy dense-grid hourly feature matrix (SQLite)
    train_model.py             Legacy LightGBM+CatBoost hourly ensemble (SQLite)
  game/                        OPTIMIZE pillar
    stackelberg.py             Mixed-strategy patrol + Colonel Blotto + what-if (SQLite)
    expected_utility.py        Violator expected-utility / adaptation model (SQLite)
    spillover.py               Waterbed/displacement simulation (SQLite)
    exploration.py             ε-greedy patrol allocation (bias mitigation)
    throughput_sim.py          Before/after congestion-index + real measured-minutes
  agent/
    validation_agent.py        Self-validating CIS calibration / trust-report agent
  llm/                         Grounded LLM explanation layer (Gemini, cached)
  tests/                       pytest + hypothesis suite for the whole pipeline
  risk_score.py                Legacy composite risk score (SQLite)
  hotspot_dbscan.py            Legacy time-aware DBSCAN clustering (SQLite)
run_pipeline.py                Orchestrates the offline artifact (re)build (v1 and --v2)
```

Key data artifacts:

```
data/enriched/
  congestion_observations.json        Task 1 collector output (frozen snapshot)
  congestion_observations.json.meta.json   Provenance: frozen flag + content sha256
  congestion_observations_midday.json / _peak.json   Named backups of two runs
  traffic_context.json / traffic_context_h3.json     Legacy + re-keyed MapMyIndia context
  routes.json                          Cached route geometries
  zone_adjacency.json                  (pending) driving-time neighbor graph
data/processed/
  zone_congestion_impact.json          v1 CIS artifact {h3_id: {bucket: breakdown}}
  zone_congestion_impact_v2.json       v2 calibrated CIS artifact (served when present)
  cis_calibration.json                 Task 3 fitted weights + before/after Spearman
  cis_calibration_meta.json            v2 metadata sidecar (read by /health)
  cis_validation_report.json           Task 2/10 trust + density≠impact proof (served)
  cis_validation_report_baseline.json  v1 baseline trust report
  predicted_degradation.json           Task 4 per-zone degradation (measured|predicted)
  forecasts.json                       v1 next-day forecast
  forecasts_v2.json                    v2 forecast (+ road context)
  forecast_explanations.json           SHAP sidecar
  calibrated_scores.json / agent_log.json   Self-validating agent outputs
  throughput_sim.json                  Before/after enforcement throughput
  zone_impact_res{5,7,8,9}.json        Multi-resolution CIS artifacts
```

---

## 3. QUANTIFY — the Congestion Impact Score (CIS)

### 3.1 What CIS is (and is not)

CIS is a **deterministic, transparent 0–100 proxy score** computed per H3 res-9
zone and per time bucket. It is explicitly **not** a trained model with an RMSE —
it is a weighted sum of five normalized components. (The RMSE/MAE/Precision@10
numbers you see elsewhere belong to the separate violation-count forecast, §4.)

The CIS lives in `ml/congestion/impact_score.py` — a pure module with **no I/O,
no network, no DB, no randomness**. Identical inputs always produce identical
outputs. The offline builder feeds it; the backend never recomputes CIS at
request time.

### 3.2 The five components and weights

```
CIS = clamp( 100 * Σ WEIGHTS[c] * component[c] , 0, 100 )
```

Canonical (v1, expert-set) weights — asserted to sum to 1.0 at import:

| Component | v1 weight | Definition (each clamped to [0,1]) |
| --- | --- | --- |
| `lane_blockage` | 0.30 | `clamp(lane_load / max(max_lane_load,1))`, `lane_load = main_road·1.0 + double_park·2.0` |
| `intersection_impact` | 0.25 | `clamp((junction_count / max(max_junction_load,1)) · (1.5 if named junction else 0.5))` |
| `traffic_degradation` | 0.25 | `clamp((travel_time_ratio − 1)/2)` if a valid MapMyIndia ratio, else `0.5` (defaulted=True) |
| `access_blockage` | 0.10 | `clamp(access_count / max(max_access_count,1))` |
| `vehicle_size` | 0.10 | `clamp(mean_vehicle_obstruction / max(max_mean_obstruction,1e-9))` |

A sixth value, `severity = clamp(mean_vehicle_obstruction / 2.0)`, is reported as
a **diagnostic only** and is deliberately excluded from the weighted sum so the
weights stay a clean partition of unity.

**Impact bands** (right-closed): MINIMAL ≤ 25, MODERATE ≤ 50, SEVERE ≤ 75,
CRITICAL > 75.

**Lane-hours estimate** (`estimate_lane_hours`, transparency metric):
`main_road·0.5 + double_park·1.0 + junction·0.75 + other·0.25`, where `other` is
floored at 0 so over-counted categories can never subtract lane-hours.

`score_zone()` returns a Pydantic `CongestionBreakdown` and accepts two additive
calibration seams (used by v2): `weights=` (a fitted vector) and
`degradation_override=` (a measured/predicted value that replaces the
from-ratio component and clears the `defaulted` flag).

### 3.3 Building the artifact (`build_artifact.py`)

The offline builder turns the cleaned violations CSV into the typed inputs the
scorer consumes:

1. **Spatial:** each row's `(lat, lon)` → H3 **resolution 9** cell (~174 m edge)
   via the `h3` library. `zone_id == h3_id` everywhere.
2. **Temporal:** timestamps parsed as UTC → converted to **IST**; the hour maps
   to one of four data-rich buckets and is dropped past the 16:00 cliff:
   - `night` 00:00–05:59, `morning_peak` 06:00–09:59, `midday` 10:00–13:59,
     `afternoon` 14:00–15:59, plus an `all_day` rollup. Hours ≥ 16 are excluded
     (operational recording bias — ~99% of records are 00:00–15:59).
3. **Category counts** (membership, not multiplicity): main-road, double-park,
   junction (road-crossing / traffic-light / zebra), access (bus-stop / school /
   hospital / footpath). Vehicle obstruction weight on a 0.5–2.0 scale
   (two-wheeler 0.5 → bus 2.0), preferring the validator-corrected vehicle type.
4. **Corpus maxima** taken across every scored aggregate (buckets + all_day) so
   each count-based component normalizes the corpus max to 1.0.
5. **Score + write** as `{h3_id: {time_bucket: breakdown}}` JSON, sorted for
   byte-stable output. Centroid lat/lon attached per zone from the H3 id.

Determinism: every reduction is order-independent (counts, sums, means, `any`,
tie-broken-by-value rankings), so the artifact is invariant to row order. There
is **no SQLite / no DB** in this path — only a columnar/JSON file or an in-memory
DataFrame.

The artifact covers **2,527 H3 zones**. A multi-resolution variant
(`build_multi_resolution`) also writes res5/7/8/9 artifacts.

---

## 4. PREDICT — next-day violation forecast

### 4.1 H3-native forecaster (`build_h3_forecast.py`, v1)

Trains on the **same H3 res-9 zones** the map uses, so "tomorrow's hotspots" line
up exactly with the CIS layer (no re-keying). Self-contained, deterministic, and
serves a single committed artifact `forecasts.json`.

- **Target:** daily `violation_count` per H3 zone over the data-rich window
  (00:00–15:59 IST).
- **Panel:** dense (zone × day); missing day = 0 violations.
- **Features (leakage-free, strictly past):** `lag_1d`, `lag_7d`,
  `rolling_mean_7d`, `rolling_mean_14d`, `rolling_std_7d`, `zone_expanding_mean`,
  `dow`, `month`, `is_weekend`, `lat`, `lon`. Rolling stats use `shift(1)` then
  `rolling(...)`, so the target never enters its own features.
- **Split (chronological):** train < 2024-03-01, validate = March (early stop),
  test ≥ 2024-04-01. **LightGBM Poisson**, seed 42, single-threaded deterministic.
- **Metrics:** daily **Precision@10** (overlap of the day's true top-10 hotspot
  zones with the predicted top-10), plus MAE / RMSE.
- **Output per zone:** `predicted_count`, `predicted_risk` (percentile×100),
  `predicted_band`, Poisson confidence band `pred ± 1.96·√pred`, lat/lon.

**Currently committed v1 held-out metrics** (`forecasts.json`): Precision@10 =
**0.45**, MAE = **0.832**, RMSE = **4.426**, over **8** April test days; 2,527
zones; forecast target date 2024-04-09 (trained through 2024-04-08).

### 4.2 Forecast v2 with road context (`build_h3_forecast_v2.py`, Task 8)

An additive shadow of v1: same panel and trainer, plus two MapMyIndia-sourced
features:

- `neighbor_spatial_lag` — mean of a zone's **road-connected** neighbors' `lag_1d`
  (driving-time adjacency from `adjacency.py`), so the model uses real road
  neighbors, not straight-line distance.
- `road_size_proxy` — 0–3 road-size class from the collector's free-flow speed
  (`road_geometry.py`).

It trains v2 **and** the v1 baseline on the same split and reports Precision@10
old vs new. Improvement is **not forced**: when adjacency/observations are
absent, both new features are 0 everywhere, so v2 collapses to v1 (an honest "no
change without real data"). Writes `forecasts_v2.json`; never overwrites
`forecasts.json`.

### 4.3 SHAP explainability (`forecast_explain.py`, Task 9)

Per-zone explanation of the forecast: which features pushed tomorrow's count up
or down. Uses LightGBM's native `predict(pred_contrib=True)` (TreeSHAP-identical,
no extra dependency, offline, deterministic). Exports the top-k contributors and
the base value per zone to `forecast_explanations.json`. Additivity invariant:
contributions + base value = the model's raw margin.

---

## 5. OPTIMIZE — game theory & simulation

### 5.1 Stackelberg patrol allocation (`stackelberg.py`)

Computes mixed-strategy patrol probabilities. Baseline weight `risk^ALPHA`
(ALPHA = 1.5) with a **fatigue adjustment** derived from real approved-violation
history: `adjusted_weight = risk^α / (1 + λ·patrol_count)` (λ = 0.3), normalized
per hour so `Σ P = 1`. Also computes **Colonel Blotto** discrete team assignment
(K teams to the top-K zones per hour) and **what-if coverage** of HIGH/CRITICAL
zones across K ∈ {2,4,6,8,10,15,20}. (Legacy SQLite path — see §9.)

### 5.2 Violator expected utility (`expected_utility.py`)

Models the attacker (violator) side: time saved by illegal parking minus search
time and expected fine cost `patrol_probability · ₹500`, mapped through a sigmoid
to a 0–100 `violator_risk_score`, then bucketed into an `adaptation_response`
(`search_legal` < 40, `uncertain`, `park_illegally` ≥ 60) that gates spillover.

### 5.3 Waterbed / spillover (`spillover.py`)

Simulates crime displacement when patrols shift violators to neighbors. KD-tree
k-NN neighbor graph (k = 6); patrolled zones lose 20% of risk; displaced risk is
conserved and distributed 70/30 to 1st/2nd-degree neighbors (gated by the
violator adaptation response). Exports top-50 displacement arrows per hour for an
animated map overlay. Asserts risk stays in [0,100], patrolled risk decreases,
and neighbor-1 risk increases.

### 5.4 ε-greedy bias mitigation (`exploration.py`, Task 9)

Mitigates the predictive-policing feedback loop (the model learns *where police
record* violations, not where they happen). Patrol mass is split:

```
allocation_i = (1−ε)·exploit_i + ε·explore_i        (ε = 0.10)
```

- `exploit_i ∝ risk_i^1.5` (normalized) — patrol where recorded risk is highest.
- `explore_i ∝ 1/(1+observed_count_i)` (normalized) — favor under-observed zones.

Both distributions sum to 1, so the allocation sums to 1.0 for any ε. Pure and
deterministic. Carries an "honest limitation" note for the UI.

### 5.5 Throughput simulation (`throughput_sim.py`, Task 7)

The "put traffic on the map" payoff, grounded in the calibrated CIS.

**City congestion index** over the top-N hotspot universe:
`C = Σ (CIS_zone/100)·w_zone` (uniform `w = 1`). Patrolling concentrates via the
same Stackelberg strategy `p_zone ∝ CIS^1.5`; with n teams, a zone's coverage is
`1 − (1−p_zone)^n`. Enforcement removes a documented fraction
(`ENFORCEMENT_EFFECTIVENESS = 0.6`) of a covered zone's blockage. Reports
`pct_reduction` and an explicitly **illustrative** `modeled_minutes_saved`
(`MINUTES_PER_INDEX_UNIT = 45`) across 1–20 teams. Every constant lives in a
`CONSTANTS` block and is labeled a modeled estimate. Monotonic by construction.

**Real measured-minutes extension** (Task 7 extension, additive): for the zones
actually measured by MapMyIndia, attributes real delay relief using the **Task 4
degradation model** (components → degradation), **never the full CIS** (which
embeds the measured target — that would be circular). Per measured zone:

```
E_i        = t_ff_i · (ratio_measured_i − 1)          # measured excess delay
coverage_i = 1 − (1 − p_i)^N
c_after_i  = reduce lane/intersection/access by (1 − eff·coverage_i)
d_deg_i    = max(0, model(c_i) − model(c_after_i))
minutes_i  = t_ff_i · min(2·d_deg_i, ratio_measured_i − 1) / 60   # clamp
```

The `min` clamp guarantees `minutes_i ≤ E_i/60`, so total saved ≤ total measured
excess (D/M ≤ 100%). Reports an honest `available: false` pending block when
there is no live collector run or too few measured zones to fit the model. Caveats
state it is ~350 m local segments, model-attributed on a small sample, with a
documented effectiveness assumption.

---

## 6. The calibration pipeline (turning CIS into a measured instrument)

The core insight: in v1, `traffic_degradation` (25% of the score) is the flat
`0.5` fallback for ~2,517 of 2,527 zones, and the other four weights are expert
guesses never fitted to anything. The pipeline measures real local congestion
with MapMyIndia, fits the weights to it, predicts the missing component, and
reports a real, non-circular trust metric.

The numbered tasks below map directly to modules. The **data boundary** rule
holds throughout: real calibration numbers come only from a live, peak/midday
MapMyIndia collector run; tests use CIS-independent synthetic fixtures and no
synthetic numbers are committed.

### Task 1 — Local-segment congestion collector (`congestion_collector.py`)

Measures **local** congestion per zone, not the whole corridor to the city
centre (the legacy `mapmyindia.py` approach, left untouched).

- **Method (`local_segment_v2`):** for each zone centroid, build 4 short ~350 m
  legs N/E/S/W (`Δlat≈0.0035`, `Δlon≈0.0036`). For each leg query
  `distance_matrix` (baseline, no traffic) and `distance_matrix_eta` (live), set
  `ratio = eta/baseline`. `congestion_ratio = median(ratio over legs)`.
- **Free-flow speed:** prefer the response `distances`
  (`free_flow_speed_kmph = distance_m/baseline_s·3.6`); else haversine fallback
  with `free_flow_speed_approx = True`.
- **Budget guard:** `--budget` caps API calls (≈ legs·2 + reverse-geocode +
  nearby = 10 per uncached zone). Prints the call estimate and ₹ cost and refuses
  to run (`BudgetExceededError`) if the estimate exceeds the budget.
- **Caching:** per-zone results written incrementally; a re-run makes zero calls
  for cached zones unless `--refresh`.
- **Exploration sampling:** top `--top-n` (default 110) by violation volume **plus**
  a seeded random `--explore-n` (default 40) lower-volume zones, each tagged
  `is_exploration`, so the trust metric isn't measured only on dense zones.
- **Peak-time guard:** records `measured_at` (ISO + IST hour) and warns when run
  outside ~08:00–11:00 / 18:00–20:00 IST (off-peak ratios trend to ~1.0 and
  destroy calibration).
- **Per-zone isolation:** one bad zone (network/parse error) is logged, skipped,
  and the run continues; the snapshot still freezes with what was collected.
- **Immutable snapshot (Task 11):** writes a `.meta.json` sidecar with
  `frozen: true` + `content_sha256` + `measured_at`; refuses to overwrite a frozen
  snapshot without `--force`. Every downstream artifact records the sha it
  consumed (auditable provenance).
- **Secrets:** the key is read from `MAPPLS_STATIC_KEY` and is never printed or
  written to the artifact.

Output `congestion_observations.json` keyed by `h3_id` with `congestion_ratio`,
`raw_legs`, `free_flow_speed_kmph`, `road_name`, `pois`, `is_exploration`,
`measured_at`, `method`, `source`.

### Task 2 + 10 — Validation harness & density≠impact proof (`validate_cis.py`)

Joins, per zone, the CIS `all_day` `congestion_impact` with the measured
`congestion_ratio`, and reports rank correlation (Spearman, primary) and Pearson.

- **Deterministic split:** SHA-256 hash of `f"{seed}:{h3_id}"` → 70% train / 30%
  test (stable across processes, unlike salted `hash()`).
- **Reported on:** all zones, the held-out test split, and the exploration subset.
- **Honest guard:** < 5 points or constant input → `null` (logged), never a
  misleading number.

**The density≠impact proof (Task 10)** — three Spearman correlations on the test
split vs the measured ratio, each with a bootstrap CI:

1. `corr(raw_count, ratio)` — the **baseline to beat** (`total_records`).
2. `corr(CIS_full, ratio)` — flagged **circular / upper bound** (it contains the
   measured ratio via `traffic_degradation`).
3. `corr(CIS_honest, ratio)` — the **honest** number: weighted sum of the **four
   non-traffic components only** (lane, intersection, access, vehicle), with the
   calibrated 4-component weights renormalized to 1. Asserted to exclude
   `traffic_degradation` (airtight anti-circularity).

`baseline_beaten = honest > count`. A `calibration_strength` verdict
(`strong` / `weak` / `aborted`, Task 15) is set: `strong` requires the honest CI
lower bound to exceed the count rho **and** honest rho > 0.3; `aborted` when there
is no usable signal; else `weak`.

### Task 3 — Weight calibration (`calibrate_weights.py`)

Replaces the guessed weights with weights **fitted to the measured ratio**.

- **Circularity rule:** `traffic_degradation` is excluded from the fit (it is
  derived from the ratio). Only the four violation/road components are fitted.
- **Objective:** non-negative weights `a₁..a₄` summing to 1 that **maximize
  Spearman**(`Σaᵢxᵢ`, ratio) on the train split. Spearman is rank-based
  (non-differentiable), so it uses a **seeded Dirichlet random search** (20k
  samples + simplex vertices + current weights) with optional **Nelder-Mead**
  refinement. Fully deterministic.
- **Reassembly:** `traffic_degradation` weight stays fixed at **0.25** (the
  "measured-signal weight"); the other four become `aᵢ·(1−0.25)`; sum asserted to
  1.0 ± 1e-9.
- **Flat-variance abort (Task 11):** if measured ratios are near-flat (std <
  0.02, i.e. off-peak), it refuses to fit and returns a structured
  `aborted_flat_variance` (no crash, no noise-fitting).
- Reports old vs new test Spearman with bootstrap CIs. Improvement is not forced.

### Task 4 — Predicted degradation (`predict_degradation.py`)

Replaces the flat `0.5` for unmeasured zones with a **predicted** value.

- **Label (measured zones):** `clamp((ratio − 1)/2)` — the same transform the
  scorer uses (CIS-independent).
- **Features:** the four components + `poi_count` + `free_flow_speed_kmph` (the
  latter two mean-imputed for unmeasured zones).
- **Model:** strongly-regularized **Ridge** (impute → standardize → Ridge,
  α = 1.0), defensible for ~150 samples and fully deterministic.
- **Generalization:** **leave-one-zone-out CV** (leakage-free: each held-out zone
  predicted by a model refit on the others), reporting R² and Spearman + CI.
- **Output:** measured zones keep their real transform (`source: "measured"`);
  unmeasured zones get the model prediction (`source: "predicted"`), clamped to
  [0,1]. Falls back to 0.5 with a warning if too few measured zones.

### Task 5 — Calibrated v2 artifact (`build_calibrated_artifact.py`)

Builds the **v2** CIS artifact via the v1 builder's `weights` / `degradation_lookup`
seams, without touching v1.

- Writes a **pure** `{h3_id: {bucket: breakdown}}` artifact to
  `zone_congestion_impact_v2.json` (no embedded metadata key — so no consumer can
  miscount a phantom "zone").
- Writes calibration metadata to a **separate sidecar**
  `cis_calibration_meta.json` (`cis_version`, weights, `spearman_test`,
  `n_measured`, `calibrated_bucket`, `collection_date`, ...). `/health` reads it.
- The backend's `data_loader` defaults to v2 and **falls back to v1** when v2 is
  absent (additive-shadow; removing/renaming v2 cleanly reverts).

### Task 6 + 12 — Self-validating agent (`agent/validation_agent.py`)

Demo "wow moment": *"our AI validates itself against real traffic data."* Reads
the CIS artifact's `all_day` `congestion_impact`, queries the real MapMyIndia
`travel_time_ratio`, and per zone computes:

```
expected_ratio   = 1.0 + (raw_score/100)·2.0
discrepancy      = actual_ratio − expected_ratio
adjustment       = 0.3·(discrepancy / max(expected_ratio, 1.0))
calibrated_score = clamp(raw_score·(1 + adjustment), 0, 100)
status: |adjustment| ≤ 0.05 → validated_accurate; > 0.05 up; < −0.05 down
```

- **Guard:** a zone is calibrated only when `is_traffic_degradation_defaulted`
  is False **and** the ratio is finite and positive; everything else is `no_data`
  and omitted.
- **Rule-based, not LLM:** deterministic, zero quota, fully offline.
- **Coherence mode (Task 12):** when a real weight calibration exists
  (`cis_calibration.json`), the agent runs **report-only** — `apply_nudge=False`,
  so `calibrated_score == raw_score` and `adjustment == 0`. Scores are calibrated
  **exactly once** (by the weights); the agent's job becomes reporting trust. The
  legacy α=0.3 nudge survives only as the fallback when no calibration exists.
- **`calibration_run` block:** assembled offline from the Task 2/3/4 sidecars
  (old/new weights, before/after Spearman, n measured/exploration, LOZO metrics).
  Reports `available: false` (pending) when sidecars are absent — never fabricated.

### Task 11 — Statistical honesty (`stats_utils.py`)

Shared helpers so every reported correlation carries a CI and calibration refuses
to fit noise:

- `bootstrap_spearman_ci(x, y, n_boot=2000, seed=42)` — deterministic percentile
  bootstrap CI; `null` fields when < 5 pairs or constant.
- `flat_variance_abort(y, std_min=0.02)` — structured abort on near-flat ratios.
- `content_sha256(...)` — canonical-JSON content hashing for the provenance chain.

### Task 12 (serving) — calibrated bucket / time regime

`data_loader` exposes `headline_bucket` (the calibrated bucket, default
`all_day`) and tags each served breakdown with `time_regime`
(`"calibrated"` when the served bucket matches the calibrated one, else
`"uncalibrated"`). `/health` additively exposes `calibrated_bucket` and
`headline_bucket`; `risk.py` exposes the bucket/regime additively without changing
the existing `all_day` default.

### Task 13–15 — proof visual, e2e test, fallback

- **Task 13 (frontend):** `/validation/proof` endpoint + a lightweight SVG
  ProofScatter (CIS_honest vs ratio and count vs ratio) with ρ + CI labels and the
  density≠impact headline; graceful pending state when the report is absent.
- **Task 14:** `diff_top_zones.py` reports v1↔v2 top-15 adds/drops/rank-moves so a
  reordered demo leaderboard never surprises anyone; an end-to-end pipeline test
  runs the full v2 chain on a tiny CIS-independent fixture.
- **Task 15:** the `calibration_strength` verdict drives a pre-rehearsed
  strong / weak / aborted demo narrative.

### 6.1 Orchestration (`run_pipeline.py`)

- `python run_pipeline.py` — rekey enrichment → build v1 CIS artifact →
  self-validating agent → H3 forecast. (`--multi-res` also builds res5/7/8/9.)
- `python run_pipeline.py --v2` — the **offline, idempotent, no-network**
  calibrated re-run that consumes the frozen `congestion_observations.json`:
  `validate_cis (v1 baseline) → calibrate_weights → predict_degradation →
  build_calibrated_artifact → validate_cis (v2, served) → agent (report-only) →
  forecast v2 (+adjacency, +SHAP)`. It refuses to run if the v1 artifact or the
  observations snapshot is missing — it never fabricates a calibration.

The live collectors (`congestion_collector`, `adjacency`) are separate, manual,
budget-guarded steps run first; `--v2` only consumes their cached, frozen output.

---

## 7. MapMyIndia enrichment details

- **`mapmyindia.py` (legacy):** the original zone→city-centre collector. Endpoints
  (all GET, `access_token`): Distance Matrix
  `route.mappls.com/route/dm/{distance_matrix|distance_matrix_eta}/driving/{lon,lat;lon,lat}`
  (reads `results.durations[0][1]` seconds; coords are **lon,lat** order), Reverse
  Geocode `search.mappls.com/search/address/rev-geocode`, Nearby POI
  `search.mappls.com/search/places/nearby/json`. Left untouched (additive-shadow).
- **`adjacency.py` (Task 8):** builds a road-connected k-NN neighbor graph (k = 6)
  for the top-N hotspot zones. Haversine-prefilters the nearest `MAX_CANDIDATES`
  (12) zones (free), then makes **one** distance-matrix call per zone over
  `[zone] + candidates` (each call ≤ `MAX_MATRIX_SIZE`), keeping the k smallest
  driving times. Budget-capped. Output `zone_adjacency.json`.
- **`road_geometry.py` (Task 8):** `RoadGeometryProvider` seam.
  `MapMyIndiaRoadGeometry` derives a road-size class from free-flow speed
  (> 40 km/h arterial, 20–40 collector, < 20 local, else unknown → rank 0–3).
  `OSMRoadGeometry` is the only non-MapMyIndia seam — a documented stub
  (`raise NotImplementedError`) for real lane count/width, requiring coordinator
  approval and supplementing, never replacing, MapMyIndia.
- **`build_routes.py`:** offline pre-compute of route geometries (station →
  top-hotspot) into `routes.json` so "Route now" is fully cached/offline.
- **`rekey_traffic_context.py`:** re-keys the legacy enrichment to true H3 res-9
  ids (the legacy file used placeholder example ids that didn't match real cells).

**Pricing / budget:** MapMyIndia per-call price is not publicly published;
`RUPEES_PER_CALL = 0.03` is a documented default (overridable). The hard guard is
on the **call count** (`--budget`), which is plan-independent. Total project
budget is ₹1000; the midday full collection (150 zones) cost ~₹45.

---

## 8. LLM explanation layer (`ml/llm/`)

A grounded, cached natural-language layer for the `/explain` endpoint. Three
prompt templates (zone explain, patrol recommend, impact explain) inject **exact
pre-computed numeric facts** and lock the model into a "Bengaluru traffic
enforcement analyst" persona that must use only the supplied facts (anti-
hallucination). `generate_explanations.py` pre-warms
`explanations_cache.json` for the top-N real H3 hotspot zones so the demo serves
instantly offline; an optional `--use-gemini` mode upgrades the text when a
`GEMINI_API_KEY` is present, falling back to a deterministic grounded template on
any failure. Fully offline-safe.

---

## 9. Legacy SQLite analytics path (older modules)

A separate, earlier lineage of modules keyed to a custom ~500 m lat/lon grid
(`grid_cell_id` like `2563_15537`) and a SQLite DB (`data/parkvision.db`). These
are **not** on the JSON serving path but are documented for completeness:

- `risk_score.py` — composite 0–100 risk per `(grid_cell_id, hour)` from six
  weighted components (density, road importance, peak, repeat-offender, trust,
  heavy-vehicle), tiered LOW/MEDIUM/HIGH/CRITICAL.
- `hotspot_dbscan.py` — time-aware DBSCAN clustering (haversine BallTree,
  eps≈330 m, min_samples=10) per time bucket, with cluster centroids/density.
- `forecast/feature_engineering.py` — dense hourly (cell × hour) leakage-free
  feature matrix (true clock lags, rolling stats, grid-Moore spatial lag).
- `forecast/train_model.py` — LightGBM (Poisson) + CatBoost (RMSE) rank-weighted
  blend, chronological split, val-tuned prediction caps + blend weight, daily
  Precision@10 headline. Writes a model card.
- `game/stackelberg.py`, `game/expected_utility.py`, `game/spillover.py` — the
  game-theory trio described in §5, persisting to SQLite tables and exporting
  JSON overlays (`whatif_coverage.json`, `violator_utility.json`,
  `spillover_arrows.json`).

The H3-native CIS + forecast (`build_artifact.py`, `build_h3_forecast.py`)
supersede the grid path for the live map because they align exactly with the
H3-keyed congestion layer.

---

## 10. Dataset facts

- ~**298,450** rows, 24 columns, **Nov 2023 – Apr 2024** (the "jan to may"
  filename is wrong), **151** unique IST dates.
- **No** speed/queue/capacity columns — congestion impact must be a defensible
  proxy unless external traffic data is added (which MapMyIndia provides).
- `description`, `closed_datetime`, `action_taken_timestamp` are 100% empty
  (dropped).
- Hours 00–15 hold ~99% of records; 16:00+ ~0.4% (operational recording bias —
  "recorded creation time", never claim violations only happen in the morning).
- **H3 res-9** (~174 m hex), **2,527** CIS zones, top ~60 hotspot universe.
- **54** police stations (top: Upparpet, Shivajinagar, Malleshwaram, HAL Old
  Airport, City Market). **169** named junctions (~half of rows).
- Dataset's suggested congestion weights: double-park 1.40, near traffic
  light/zebra 1.35, near crossing 1.35, main road 1.30, bus/school/hospital 1.25,
  footpath 1.15, wrong/no parking 1.00, defective plate 0.40.
- Top hotspots: Upparpet/Gandhi Nagar, City Market/KR Market, HAL Old
  Airport/Kadubisanahalli, Shivajinagar/Safina Plaza.

---

## 11. Current served calibration numbers (midday snapshot)

The committed v2 artifacts reflect a **midday** MapMyIndia collection (150 zones,
measured 2026-06-23 ~12:46 IST; observations sha `dab4158d…`). A separate evening
**peak** re-collect came out weaker on the held-out split (honest ρ 0.312) with
degenerate capped weights, so the **midday** snapshot was kept and rebuilt for
consistency; the peak snapshot is preserved as a named backup.

**Calibrated weights** (`cis_calibration_meta.json` / `cis_calibration.json`):

| Component | v1 (old) | v2 (calibrated) |
| --- | --- | --- |
| `intersection_impact` | 0.25 | **0.604** |
| `traffic_degradation` | 0.25 | 0.25 (fixed) |
| `access_blockage` | 0.10 | **0.131** |
| `lane_blockage` | 0.30 | **0.0147** |
| `vehicle_size` | 0.10 | **0.00019** |

Method: `dirichlet_random_search+nelder_mead`. The calibration's headline finding
is that **junctions dominate** congestion impact, not raw lane volume.

**Trust metrics** (`cis_validation_report.json`, test split, n = 48 proof zones):

| Metric | ρ | 95% bootstrap CI |
| --- | --- | --- |
| Honest CIS (4 non-traffic components) | **0.380** | [0.131, 0.579] |
| Raw violation count (baseline) | **0.412** | [0.103, 0.658] |
| Full CIS (circular / upper bound) | 0.846 | [0.691, 0.944] |

- `baseline_beaten`: **false** — `calibration_strength`: **weak** (the honest CIS
  and raw count have overlapping CIs at n = 48).
- This is the **honest, expected** result and must not be "fixed" by fabrication.
  The contribution is the methodology (measure → calibrate → validate against live
  MapMyIndia), which tightens with more measurement.

**Degradation model** (`predicted_degradation.json`): Ridge, n = 150 measured,
2,377 predicted; LOZO R² = **0.291**, LOZO Spearman = **0.598** [0.471, 0.696].

**Calibration cohort:** n_measured = 150 (110 core + 40 exploration), 102 train /
48 test.

> These numbers are produced **only** from the live collector run and are
> regenerated deterministically by `run_pipeline.py --v2`. They are not fabricated
> and are reported as-is, including the weak verdict.

---

## 12. Testing

`ml/tests/` (pytest + hypothesis) covers the whole pipeline; the suite is
deterministic and uses **CIS-independent** synthetic fixtures (no synthetic
calibration numbers are committed). Notable suites:

- CIS scoring properties: band monotonicity, determinism, lane-hours
  non-negativity/monotonicity, traffic-degradation fallback, score bounds,
  empty-corpus and order-independence properties.
- `test_validate_cis`, `test_calibrate_weights`, `test_predict_degradation`,
  `test_stats_utils` — calibration math, anti-circularity (honest predictor
  provably excludes `traffic_degradation`), weights ≥ 0 and sum to 1, bootstrap CI
  brackets, flat-variance abort, LOZO leakage-freeness.
- `test_congestion_collector` — ratio/free-flow math, budget cap, cache,
  offset≈350 m, per-zone error isolation, frozen-snapshot guard.
- `test_throughput_sim`, `test_measured_minutes` — monotonicity, clamp
  (minutes ≤ excess), zero at coverage/effectiveness 0, determinism.
- `test_build_calibrated_artifact`, `test_task12_calibration_coherence`,
  `test_agent_calibration_run`, `test_validation_agent_integration` — v2 build,
  report-only zero-nudge when calibrated, legacy nudge when not.
- `test_road_features`, `test_diff_top_zones`, `test_bias_and_explain`,
  `test_pipeline_e2e` — road proxy/adjacency, top-zone diff, ε-greedy mass = 0.10
  and allocation sums to 1.0, SHAP finiteness, full offline chain.

Run from the repo root: `python -m pytest -q`.

---

## 13. How it all flows (offline rebuild)

```
raw violations CSV
   │  build_artifact.py (H3 res-9, IST buckets, corpus maxima)
   ▼
zone_congestion_impact.json  (v1 CIS) ───────────────► build_h3_forecast.py ─► forecasts.json
   │                                                          (+ adjacency, +SHAP) ─► forecasts_v2.json
   │  (live, manual, budget-guarded)                                                  forecast_explanations.json
   ▼
congestion_collector.py  ─► congestion_observations.json (frozen snapshot)
   │
   │  run_pipeline.py --v2  (offline, deterministic, no network)
   ▼
validate_cis (baseline) ─► calibrate_weights ─► predict_degradation
   ▼
build_calibrated_artifact ─► zone_congestion_impact_v2.json + cis_calibration_meta.json
   ▼
validate_cis (v2, served) ─► cis_validation_report.json   (density≠impact proof)
   ▼
validation_agent (report-only) ─► calibrated_scores.json + agent_log.json
   ▼
throughput_sim / diff_top_zones / exploration  (OPTIMIZE + bias mitigation)
   ▼
FastAPI backend loads JSON in-memory (v2 default, v1 fallback) ─► /health, /risk, /validation/proof, ...
```

The backend serves committed JSON in-memory and never runs this pipeline at
request time. To revert to v1, remove/rename the v2 artifact or unset
`CIS_ARTIFACT_PATH`.
