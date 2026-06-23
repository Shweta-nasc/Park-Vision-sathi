# ParkVision-Saathi — Frontend Audit

Read-only audit. No application source was modified. Verified by curling the live
backend (port 8000), statically tracing frontend wiring, `tsc --noEmit`, and
`npm run build`. Captured on the current build; values are live ground-truth.

Baseline confirmed: **335 pytest passed**, `tsc --noEmit` clean, `npm run build` clean.
`/health` → `cis_version=v2`, `calibrated=true`.

---

## 1. Endpoint inventory

All routes are mounted twice (bare + `/api`). Status = live HTTP result.
"Used by panel" = the frontend consumer (via `endpoints.ts`).

| Endpoint | Status | Accepts params | Output varies by param? | Used by panel/component |
|---|---|---|---|---|
| `GET /health` | 200 | — | — | TopHeader (status pill) |
| `GET /` | 200 | — | — | (none) |
| `GET /hotspots` | 200 | `time_bucket`, `limit`, `hour` | ✅ bucket; ❌ hour | (none — frontend uses `/risk/top_zones`) |
| `GET /risk/top_zones` | 200 | `n`, `time_bucket`, `hour` | ✅ **bucket re-ranks**; ❌ hour(raw) | MapView markers (`useTopZones`) |
| `GET /risk/{zone_id}` | 200 | `time_bucket`, `hour` | ✅ bucket (CIS+components) | ZoneDetail (`api.zoneDetail`) |
| `GET /risk` | 200 | `limit`, `zone_id`, `risk_label` | filter only | ZoneDetail/Game `zoneIndex` names (`api.zoneIndex`) |
| `GET /risk/summary` | 200 | — | — | (none) |
| `GET /risk/overview` | 200 | — | — | (none) |
| `GET /risk/calibration` | 200 | — | — | ZoneDetail (`useCalibration` → headline bucket) |
| `GET /heatmap` | 200 | `type`, `time_bucket`, `hour` | ✅ type & bucket; ❌ **`resolution` ignored** | MapView heatmap (`useHeatmap`) |
| `GET /heatmap/patrol_overlay` | 200 | `hour`,`time_bucket` | ❌ (time-stable) | (none) |
| `GET /forecast/top_risk_zones` | 200 | `n`, `hour` | list | ForecastPanel (`useForecastTopZones`) |
| `GET /forecast/zones` | 200 | — | — | (none) |
| `GET /forecast/accuracy` | 200 | — | — | ForecastPanel (`useForecastAccuracy`) |
| `GET /forecast/explanations` | 200 | — | available=true, 50 zones SHAP | ForecastPanel (`useForecastExplanations`) |
| `GET /game/stackelberg_strategy` | 200 | `hour`, `limit` | ❌ (all_day-derived) | GameTheoryPanel (`api.stackelberg`) |
| `GET /game/violator_adaptation` | 200 | `hour`, `limit` | ❌ (all_day-derived) | GameTheoryPanel (`api.violators`) |
| `GET /game/spillover_arrows` | 200 | — | `{arrows:[]}` | MapView spillover arrows (`useSpilloverArrows`) |
| `GET /game/summary`, `/spillover_forecast`, `/whatif_coverage`, `/patrol_allocation` | 200 | — | — | (none) |
| `POST /simulate` | 200 | body `{num_teams,hour,strategy}` | ✅ num_teams | SimulationPanel (`useSimulation`) |
| `GET /simulate/throughput` | 200 | — | — | (none) |
| `GET /stations` | 200 | — | **21 stations** | StationSelect, TopHeader |
| `GET /stations/{s}/priority_areas` | 200 | `hour`, `time_bucket`, `limit` | ✅ **bucket re-ranks** | PriorityStrip (`usePriorityAreas`) |
| `GET /stations/{s}/summary` | 200 | `hour` | counts | TopHeader (`useStationSummary`) |
| `GET /traffic/{zone_id}` | 200 | — | per-zone | ZoneDetail (`api.traffic`) |
| `POST /explain` | 200 | body `{zone_id,hour}` | `is_cached=true, source=cache` | ChatPanel (`useExplain`) |
| `GET /agent/validation-report` | 200 | — | summary+10 zones+calibration_run | AgentPanel (`useAgentReport`) |
| `GET /route` | 200 | `from_lat/lon,to_lat/lon` | ✅ geometry (81 pts, source=cache) | MapView route overlay (`api.route`) |
| `GET /validation/proof` | 200 | — | available=true, 48 proof pts | ProofScatter (`useValidationProof`) |

Unused-by-frontend but live: `/`, `/hotspots`, `/risk`(list)/`summary`/`overview`,
`/heatmap/patrol_overlay`, `/forecast/zones`, `/game/{summary,spillover_forecast,whatif_coverage,patrol_allocation}`, `/simulate/throughput`.

---

## 2. Panel-by-panel wiring + verdict

| Panel / component | Hook → endpoint | Reacts to | Verdict |
|---|---|---|---|
| **MapView** (heatmap) | `useHeatmap` → `/heatmap` (`type`+`time_bucket=hourToBucket(hour)`) | station, hour, layer | **WORKS** |
| **MapView** (markers) | `useTopZones` → `/risk/top_zones` (`time_bucket`) | station, hour | **WORKS** (re-ranks by bucket) |
| **MapView** (spillover arrows) | `useSpilloverArrows` → `/game/spillover_arrows` | layer=spillover | **WORKS** |
| **MapView** (sim overlay) | from `MapOverlay.simResult` | sim run | **WORKS** |
| **MapView** (route overlay) | `api.route` → `/route` | `routeTarget` | **WORKS** (F1; straight-line fallback) |
| **MapView** (resolution badge) | local zoom state only | zoom | **COSMETIC** (S1 — never sent) |
| **LayerToggle** | sets `AppState.layer` | — | **WORKS** / **PARTIAL** (no Violator option, S3) |
| **TopHeader** | `useHealth`, `useStationSummary` | station, hour | **WORKS** |
| **TimeControls** | sets `AppState.hour` (debounced) | — | **WORKS** (evening cliff note ≥16) |
| **StationSelect** | `useStations` → `/stations` | — | **WORKS** (footer shows real 21) |
| **PriorityStrip / Dock** | `usePriorityAreas` → `/stations/{s}/priority_areas` (`time_bucket`) | station, hour | **WORKS** (F3; window label) |
| **RiskGauge** | presentational | — | **WORKS** |
| **ZoneDetail** | `api.zoneDetail` `/risk/{id}`, `api.traffic`, `useCalibration` | selectedZone, hour | **PARTIAL** (hardcoded stale weight labels — I1) |
| **SimulationPanel** | `useSimulation` → POST `/simulate` | hour, station, teams | **WORKS** |
| **ForecastPanel** | `useForecastTopZones/Accuracy/Explanations` | station | **WORKS** |
| **GameTheoryPanel** | `api.stackelberg`, `api.violators` | station (hour=no-op) | **PARTIAL** (hour in key but output time-stable — C2) |
| **AgentPanel** | `useAgentReport` → `/agent/validation-report` | station | **WORKS** (report-only renders gracefully, S4) |
| **ChatPanel** | `useExplain` → POST `/explain` (+ rule-based) | selectedZone, hour | **WORKS** (cached/offline-safe) |
| **ProofScatter** | `useValidationProof` → `/validation/proof` | — (mounted in AgentPanel) | **WORKS** (honest WEAK/NOT-YET state) |

No imports from `data/mock` and no hardcoded mock datasets found in `frontend/src`.
All panel data is backend-driven. Adapters (`adapters.ts`) coerce via a NaN-guarded
`num()` and default missing fields, so no obvious unguarded null-throw was spotted.

---

## 3. Findings by severity

### CRITICAL (breaks demo)
None. Every panel renders with real data; build + typecheck are clean; the only
request-time network calls (`/route`, `/explain`) degrade to cache/fallback, so the
demo is offline-safe.

### IMPORTANT (weakens demo)
- **I1 — ZoneDetail shows stale CIS component weights.** `COMP_META` hardcodes the
  old v1 weights `0.3 / 0.25 / 0.25 / 0.1 / 0.1` (`frontend/src/components/panels/ZoneDetail.tsx:34-40`),
  but the live calibrated v2 weights are `lane 0.015 / intersection 0.604 / degradation 0.25 / access 0.131 / vehicle 0.0002`. The "·30%", "·25%" labels next to each bar are wrong and undersell the calibration story.
  *Fix:* derive the weight labels from `useCalibration().weights` (already fetched) or the `weights` field returned by `/risk/{id}`.
- **I2 — Demo-script station count mismatch.** Scripts say "55 stations" (`docs/DEMO_VIDEO_SCRIPT.md:51,234`) and "54 stations" (`docs/demo_video_script_next.md:31,33`); live `/stations` = **21**. The UI is honest (StationSelect footer shows 21); the scripts are stale. *Fix:* update both scripts to 21.
- **I3 — Demo-script agent narrative is stale.** Scripts narrate the agent *adjusting* scores ("HAL Old Airport calibrated down from 50 to 44", `DEMO_VIDEO_SCRIPT.md:101,238`; `demo_video_script_next.md:256-260`). The agent is now **report-only** (`mean_abs_adjustment_pct=0.0`, reasoning reads "Reported (no nudge)… score left unchanged"). *Fix:* reword to "confirms/validates the model (report-only)".
- **I4 — Demo-script test count.** Script says "126 tests" (`DEMO_VIDEO_SCRIPT.md:246`); actual **335**. *Fix:* update.
- **I5 — Violator map layer not exposed (S3).** Backend `/heatmap?type=violator` returns real data (60 pts, max 75.51), but `LayerToggle` only offers Density/Risk/Spillover (`frontend/src/components/LayerToggle.tsx:11`) and `LAYER_TO_BACKEND` has no `violator` entry (`endpoints.ts`). *Fix:* add a 4th toggle option mapping `violator→violator` (+ gradient/meta). (Low urgency — violator data is already shown in the Game panel list.)
- **I6 — `demo_video_script_next.md` top-zone numbers are stale.** It claims "Top zone: 5,838 violations at Elite Junction" and "City Market 31.2 lane-hours" (`:33,159`). Live top by violations = **12,109 at Upparpet/Gandhi Nagar (NO PARKING)**; top by CIS = **Jayanagara, CIS 49.98**. `DEMO_VIDEO_SCRIPT.md` (3,072 lane-hours for the enforcement-top zone) matches live; the two scripts disagree with each other. *Fix:* reconcile `_next` to live numbers.
- **I7 — Unverifiable forecast claim.** `demo_video_script_next.md:222,224` cites "Precision@10 = 0.68 on a coarser grid"; `/forecast/accuracy` only reports **0.45** (H3 res-9). The 0.68 figure is NOT FOUND in any live endpoint. *Fix:* drop it or cite a source artifact.

### COSMETIC
- **C1 — Multi-resolution heatmap badge (S1).** MapView computes `resolution` from zoom and shows "City view ~1km / District ~100m / Street full detail", but `/heatmap` has no `resolution` param and `api.heatmap` never sends it (verified: `resolution=2` and `resolution=3` return byte-identical output). The badge is purely a zoom label. *Fix:* relabel honestly (e.g. "Zoom: street/district/city") or implement backend re-aggregation (larger change).
- **C2 — Game panel hour control is inert.** `GameTheoryPanel` query keys include `hour` but `/game/stackelberg_strategy` & `/game/violator_adaptation` are derived from the time-stable all_day `risk_score`, so dragging the hour does not change the Game tab. *Fix:* note it, or remove `hour` from the keys.
- **C3 — Spillover heatmap layer is all_day-only.** `heatmap_points("spillover")` ignores `time_bucket`, so the Spillover layer (unlike Density/Risk) does not change across hours.
- **C4 — ZoneDetail "agent calibrated X→Y" note never fires.** `showCalib` needs `|calibrated−CIS| ≥ 0.5`; under report-only they're equal, so the note is silently hidden (expected, not a bug).

### Security / key hygiene
- Gemini key: **0 occurrences** in `frontend/dist` (server-side only — correct).
- Mappls key: 2 occurrences in `dist`, but `MAPPLS_STATIC_KEY` and `VITE_MAPPLS_KEY`
  are the **same value** in `.env`, so the bundle exposure is the intended public SDK
  tile key — *not* a new leak (the `/route` directions call is server-side). **Recommend** using a separate, domain-restricted key for the public SDK vs the server-side REST/directions key. (`.env` is open in the editor — do not commit it.)

---

## 4. Recent-fix verification

| Fix | Result | Evidence |
|---|---|---|
| **F1 — `/route` real road geometry + fallback** | ✅ PASS | `/route?from=12.9716,77.5946&to=12.9773,77.5750` → 81-point geometry, `source=cache`. MapView route effect awaits `api.route`, draws the polyline, and falls back to the 2-point dashed line on `geometry:null`. |
| **F2 — heatmap changes by hour (bucket)** | ✅ PASS | `/heatmap?type=risk` max intensity per bucket: morning_peak **29.285**, midday **27.318**, afternoon **34.427**, night **25.037**, all_day **49.981**. `endpoints.ts` sends `time_bucket=hourToBucket(hour)`; `useHeatmap` keyed on the bucket. |
| **F3 — markers + priority strip re-rank by hour** | ✅ PASS | `/risk/top_zones` morning_peak = `[28.4, 25.0, 16.2]` vs default/all_day `[7.83, 17.09, 2.56]` (re-ranked by per-bucket CIS). Default (no `time_bucket`) == all_day. `priority_areas` re-ranks similarly while `risk_score` stays time-stable. |

---

## 5. Ground-truth numbers appendix

Cite-checked against live endpoints + artifacts. "NOT FOUND" = not locatable (never guessed).

**Dataset / scale**
- Dataset records: `Dataset/jan to may police violation_anonymized791b166.csv` = **298,450 lines** (~298,449 records excl. header). Demo scripts say "298,450 records".
- Stations: **21** (`/stations`).
- H3 zones scored (CIS artifact): **2,527** (`/health congestion_artifact_zones`).
- Served hotspot universe: **60** (`/health hotspot_universe`).
- MapMyIndia-enriched zones (real travel ratio): **10** (`/health traffic_context_enriched`; only 10/60 served zones carry a `travel_time_ratio`).
- Routes cached: **59** (`data/enriched/routes.json`).
- Tests: **335 passed** (`pytest -q`).

**Calibration / CIS**
- `cis_version` **v2**, `calibrated` **true** (`/health`, `/risk/calibration`).
- Weights: lane_blockage **0.0147**, intersection_impact **0.6041**, traffic_degradation **0.25**, access_blockage **0.1310**, vehicle_size **0.0002** (`dirichlet_random_search+nelder_mead`).
- `calibration_strength` **weak**, `baseline_beaten` **false** (`/validation/proof`).
- Honest CIS ρ (non-circular, held-out test): **0.3802**, CI **[0.131, 0.579]**, p≈0.002, n=**48** proof zones.
- Raw-count ρ (baseline): **0.4119**, CI **[0.103, 0.658]**, p≈0.012 → baseline currently *edges out* the honest CIS (overlapping CIs).
- Full-CIS ρ (circular upper bound, contains the measured ratio): **0.8462**, CI [0.691, 0.944] — *not* the trust metric.
- n_measured (calibration fit): **150**; n_exploration: **40**.

**Self-validating agent** (`/agent/validation-report`, report-only)
- total_zones **2,527**, calibrated **10**, no_data 2,517, validated **10**, accurate **6**, adjusted_up **2**, adjusted_down **2**, mean_abs_adjustment **0.0%**, max_abs_adjustment **0.0%**, `coherence_mode=report_only`.
- Old→new weight agreement: Spearman **0.1097 → 0.3794** on 150 zones. Degradation model: ridge, LOZO R²=**0.2909**, ρ=**0.5978**.

**Forecast** (`/forecast/accuracy`)
- Model: LightGBM Poisson, H3 res-9, daily. `is_proxy=false`.
- Precision@10 **0.45**, MAE **0.8323**, RMSE **4.4257**, test days **8** (held-out April, chronological split). Coarse-grid "0.68": **NOT FOUND** in any endpoint.
- SHAP explanations: available, **50** zones (`/forecast/explanations`).

**Heatmap max intensity by bucket** (`/heatmap?type=risk`)
- morning_peak **29.285** · midday **27.318** · afternoon **34.427** · night **25.037** · all_day **49.981**. Raw (violation count) all_day max **12,109**. Violator layer max **75.51** (60 pts).

**Top zones**
- By enforcement (risk_score): `8960145b553ffff` — **Upparpet** (Subedar Chatram Road, Gandhi Nagar), **12,109 violations**, risk_score **100**, CIS **7.83 / MINIMAL**, **3,072 lane-hours**, travel ratio 1.594. *(The density≠impact headline: busiest zone, minimal congestion impact.)*
- By CIS: `89618925983ffff` — **Jayanagara**, CIS **49.98 / MODERATE**, **164.75 lane-hours**.
- Highest MapMyIndia travel-time ratio: **1.704** (Shivajinagar, `8961892e9b…`).

**Simulation** (`POST /simulate`, hour 9)
- 6 teams → coverage **18.85%**, 14 uncovered high-risk, 6 spillover zones.
- 8 teams → coverage **24.7%**, 12 uncovered high-risk.
- (Demo script "Spillover Zones 0" at 6 teams is stale — live = 6.)

---

## 6. Manual browser checklist

Run `cd frontend && npm run dev` (backend on :8000). For each panel: click path →
expected → watch-for. Open DevTools **Network** (watch for 404/500) and **Console**.

**0. Boot / map engine**
- Open `localhost:5173`. Expected: full-screen station picker, footer "21 stations available".
- Pick a station → map renders. **Watch:** did the **Mappls SDK** load, or did it fall back to **MapLibre** (Carto positron)? Confirm `frontend/.env` `VITE_MAPPLS_KEY` is authorized for `localhost:5173`. Console should be free of red errors.

**1. Layer toggle (theme moment)**
- Click **Violation Density** → blue heatmap. Click **Congestion Risk** → green→red heatmap. Expected: visibly different maps. **Watch:** Network shows `/heatmap?type=raw…` vs `type=risk…`, both 200. Note: there is **no Violator option** (I5).

**2. Hour reactivity (the key F2/F3 check)**
- Drag the hour slider **9 → 10** (morning_peak → midday) and **13 → 14** (midday → afternoon). Expected: the **heatmap**, the **hotspot markers**, and the **Priority Areas** strip all change/re-order together. **Watch:** Network fires `/heatmap`, `/risk/top_zones`, `/stations/{s}/priority_areas` each with a new `time_bucket`; the Priority dock header shows the window label (e.g. "Midday"). CIS scores will be **lower** in a bucket than all_day — that's correct.
- Drag to **16–23**: expect the "Evening — limited data, showing all-day" note and a populated (not blank) map.

**3. Hotspot popup + ZoneDetail**
- Click the top marker (Upparpet). Expected popup: Enforcement **100** vs Congestion **~8** — the density≠impact contrast. Open the zone → ZoneDetail. **Watch:** the gauge shows CIS; the "● calibrated · measured window" badge appears (only when the served breakdown is the calibrated window); the component bars render. **Known issue (I1):** the "·30% / ·25%" weight labels are stale v1 values — ignore them for the demo.

**4. Route now (F1)**
- In ZoneDetail or a Priority card, click **Route now →**. Expected: a **road-following** line (multi-bend), not a straight diagonal, plus a red destination dot; map fits the route. **Watch:** Network `/route?from…&to…` returns `geometry` with many points. If offline, it should silently fall back to a straight dashed line (no error).

**5. Simulation**
- **Sim** tab → drag teams to **6**. Expected: Coverage **18.85%**, Uncovered High-Risk **14**, Spillover Zones listed; team pins + spillover circles on the map. Drag to **8** → **24.7%**, 12 uncovered. **Watch:** POST `/simulate` per change; map overlay updates live.

**6. Forecast**
- **Forecast** tab. Expected: Precision@10 **45%**, MAE 0.83, RMSE 4.43; predicted top-zone bars; a SHAP "Why #1?" breakdown; the honest-limitations paragraph. **Watch:** `/forecast/top_risk_zones`, `/forecast/accuracy`, `/forecast/explanations` all 200.

**7. Game theory**
- **Game** tab. Expected: patrol-probability bars + violator-utility list with real place names. **Watch (C2):** dragging the hour does NOT change this tab — expected; don't present it as time-aware.

**8. Agent (S4 + S5)**
- **Agent** tab. Expected: the **Density ≠ Impact** proof scatter (two plots, ρ≈0.38 honest vs ρ≈0.41 count, **WEAK** badge, "NOT YET"); the **Calibration Loop** table (old→new weights, ρ 0.11→0.38); a summary row (Validated 10, Accurate 6, Adj↑ 2, Adj↓ 2); "Mean absolute calibration adjustment: **0%**"; the reasoning log ("Reported (no nudge)…"). **Watch:** this is the honest "weak but real" story — the panel must render fully, not empty.

**9. Assistant (offline-safe)**
- **Assist** tab with a zone selected → ask "Why is this area high risk?". Expected: a plain-English brief tagged "(cached)". **Watch:** POST `/explain` returns `source=cache` — works without network.

**10. Header / status**
- Confirm the status pill reads **Live** (green). Counts (zones / high-risk / violations) match the selected station.

---

*End of audit. No application source modified during this audit.*
