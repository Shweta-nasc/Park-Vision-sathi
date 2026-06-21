# ParkVision-Saathi — Project Audit Report

> Full audit of the **backend + data + ML pipeline** against `PARKVISION_SAATHI_MASTER_PLAN.md`
> and `EXECUTION_PLANNER.md`. Frontend tasks are intentionally **out of scope** (per request),
> but frontend↔backend data wiring is covered where it affects whether the backend's real work
> actually reaches the demo.
>
> Date: June 21, 2026 · Method: read every backend/ML source file, ran the full test suite
> (126 passed), booted the app in-process, and exercised every endpoint with real artifacts.

---

## 1. Verdict (read this first)

**The backend runs, all endpoints return 200, and 126 tests pass.** The hard ML work
(Congestion Impact Score over 2,527 real Bengaluru H3 zones, an honest held-out forecast,
a self-validating agent) genuinely exists and is correct.

**BUT there is one structural defect that undermines the demo's credibility:** the project
ships **two disconnected "zone universes,"** and the three pillars are split across them:

| Pillar | Data source actually served | Real or mock? |
|---|---|---|
| **QUANTIFY** (heatmap `risk`/`raw`, `/hotspots`, `/risk/{id}` CIS, `/forecast`, `/agent`) | `data/processed/zone_congestion_impact.json` (2,527 H3 zones) | ✅ **REAL** Bengaluru data |
| **OPTIMIZE** (`/game/*`, `/simulate`, `/stations/*`, `/risk` list, `/heatmap?type=spillover`, `/traffic/{id}`) | `data/mock/hotspots.json` (15 zones) + `data/enriched/traffic_context.json` | ❌ **MOCK / placeholder** |

The 15 "hotspot" zones carry **placeholder H3 IDs from the wrong region** — e.g.
`8928308280fffff`, which is the H3 documentation's San Francisco example cell, paired with
Bengaluru lat/lon. They do **not** intersect the real 2,527-zone universe at all (0/15 overlap).
The real MapMyIndia enrichment that *does* match the real zones lives in a **second file**
(`traffic_context_h3.json`, 10/10 overlap) that **the backend never loads.**

Net effect: the game-theory patrol optimization, the what-if simulation, the station priority
views, and the "validated by MapMyIndia travel times" silver bullet are all running on mock
data, while the real analysis sits unused by those endpoints. A technical judge who clicks a
real hotspot and asks "show me the traffic validation for *this* zone" will get nulls.

**Effort to fix the core issue: roughly half a day.** Everything else is cleanup.

---

## 2. What is working (verified)

- **App boots** via `uvicorn backend.app.main:app` with no DB — pure JSON-in-memory (matches the planner's "no PostgreSQL/Redis/Docker" rule). `render.yaml` + `Procfile` are present and sensible (lean `requirements-backend.txt`, `$PORT` binding, `/health` check).
- **All endpoints return HTTP 200** and are mounted twice (bare path + `/api` prefix).
- **Congestion Impact Score** (`ml/congestion/impact_score.py` + `build_artifact.py`) — real, deterministic, 2,527 zones, weights form a clean partition of unity, validated by Pydantic on serve.
- **Two-layer heatmap is genuinely different** at the data level: `?type=risk` (CIS) and `?type=raw` (violation count) return different orderings — verified (`risk` top zone ≠ `raw` top zone). The "density ≠ impact" thesis holds in the data.
- **Forecast is honest** (`ml/forecast/build_h3_forecast.py` → `forecasts.json`): LightGBM-Poisson, leakage-free chronological split, real held-out metrics (Precision@10 = 0.45, MAE 0.83, RMSE 4.43) on the **same H3 zones as the map**. `is_proxy:false`. This is the kind of honesty judges reward.
- **Self-validating agent** (`ml/agent/validation_agent.py`) — calibrates CIS against the real travel-time ratio, deterministic/offline, exposed at `/agent/validation-report`.
- **`/explain` is offline-safe and grounded** — cache → optional Gemini (only if `GEMINI_API_KEY`) → grounded template built only from real fields. No hallucination path. Resolves both zone universes.
- **Edge cases handled** — invalid `hour`/`num_teams` → 422; unknown zone → structured 404; missing artifact → empty list, no crash.
- **Test suite: 126 passed** (`pytest -q`), covering CIS properties, breakdown round-trips, layer distinctness, patrol probability, agent integration.

---

## 3. Critical issues (P0 — fix before the demo)

### P0-1 — Two disconnected zone universes; OPTIMIZE pillar runs on mock data
**Where:** `backend/app/data_loader.py` `load()` builds the served zone list from
`data/mock/hotspots.json` (15 zones, fake SF-region H3 IDs). Those zones feed `/risk` (list),
`/risk/summary`, `/risk/top_zones`, `/risk/overview`, `/game/*`, `/simulate`, `/stations/*`,
`/heatmap?type=spillover`, `/heatmap/patrol_overlay`, and the `/traffic/{id}` lookups.

**Evidence:** mock hotspot IDs (`89283082bffffff` …) have **0/15** overlap with the real CIS
universe (`8960…`/`8961…` Bengaluru cells). The vanilla frontend (`frontend/app.js`) draws its
map markers from `/risk/top_zones` (mock) and runs `/simulate`, `/stations/*` (mock) — so the
**live demo's markers, simulation, and station views are 100% mock**, while the real 2,527-zone
analysis is only reachable through the heatmap layer and the unused `/hotspots` endpoint.

**Fix (pick one):**
- **Preferred:** Rebuild the served zone universe from the **real CIS artifact**. In
  `data_loader.load()`, derive the "hotspots"/zone list from `self.congestion` (top-N by CIS,
  with real H3 IDs, centroids, station, top violation, lane-hours) instead of `mock/hotspots.json`.
  Then game theory, simulation, stations, and risk-detail all operate on real zones with IDs that
  match the map and the forecast. This is the highest-leverage change in the project.
- **Faster stopgap:** Regenerate `data/mock/hotspots.json` from the real CIS top-N (correct H3 IDs
  + matching `traffic_context_h3.json` keys) so the existing code path consumes real data.

### P0-2 — Backend loads the wrong traffic-context file (real MapMyIndia data is ignored)
**Where:** `backend/app/data_loader.py` loads `data/enriched/traffic_context.json` (15 entries,
keyed to the mock SF IDs). The **real, H3-aligned** enrichment is `data/enriched/traffic_context_h3.json`
(10 entries, 10/10 match to the CIS universe), produced by `run_pipeline.py` step 1.

**Evidence:** `GET /traffic/<real-hotspot-id>` returns all `null`s (road_name, ratio, POIs) because
the loaded file isn't keyed to real zones. `run_pipeline.py` and `render.yaml` also disagree on which
file is canonical (`run_pipeline` writes `_h3`; `render.yaml`'s comment lists the old one).

**Fix:** Point the loader at `traffic_context_h3.json` (and update `render.yaml`'s artifact list +
the `build_artifact.py` `DEFAULT_TRAFFIC_CONTEXT_PATH`). Combined with P0-1, `/traffic/{id}` and the
"validated by MapMyIndia" claim start working on the zones judges actually click.

### P0-3 — Status docs describe an architecture that no longer exists
**Where:** `PERSON1_STATUS_REPORT.md` and `BACKEND_CHECKLIST.md` describe a **SQLite** backend
(`data/parkvision.db`, `grid_cell_id`, DBSCAN-from-DB) and claim endpoints are "connected to the
SQLite database." The shipped backend is JSON-in-memory and **there is no `.db` file** in the repo.

**Why it matters:** If a judge reads these, the project looks inconsistent/untruthful. `API_DOCS.md`
(correct, JSON-in-memory) directly contradicts them.

**Fix:** Update or delete both stale reports so the written record matches `API_DOCS.md` and the code.

---

## 4. High-priority issues (P1)

### P1-1 — Dead SQLite code path still in the tree
`backend/app/db.py`, `scripts/seed_db.py`, `scripts/verify_backend.py`, plus the DB-driven ML
scripts (`ml/hotspot_dbscan.py`, `ml/risk_score.py`, `ml/forecast/feature_engineering.py`,
`ml/forecast/train_model.py`, `ml/game/expected_utility.py`, `ml/game/spillover.py`,
`data/load_and_clean.py`) all target `data/parkvision.db`, which doesn't exist and which nothing in
the live request path uses. This is the remnant of "Pipeline A." It confuses readers and any judge
who opens the repo, and it makes `seed_db` look like a required step.

**Fix:** Either delete the SQLite path entirely, or quarantine it under a clearly-labeled
`legacy/` folder with a README note. Make sure `run_pipeline.py` (the real pipeline) is the only
documented way to regenerate artifacts.

### P1-2 — Game-theory / simulation values are fabricated proxies, not data-derived
In `data_loader.load()`, fields like `validation_trust = 0.70` (constant), `repeat_offender`,
`heavy_vehicle_ratio`, and the violator-utility constants (`VIOLATOR_TIME_SAVED=100`,
`VIOLATOR_FINE=500`) are hardcoded proxies. That's defensible *if disclosed*, but right now the
zone-detail "risk breakdown bars" present invented numbers as if measured. Once P0-1 routes real
CIS zones through here, re-derive these from the CIS components (`lane_blockage`,
`vehicle_size`, `access_blockage`, etc.) which are real, and label any remaining illustrative
constants as such in the response/docs.

### P1-3 — `mock/hotspots.json` CIS values disagree with the real artifact
The mock file claims a `CRITICAL 88.7` top zone (Upparpet); the real CIS top is `~MODERATE 49.5`.
If both surface anywhere (markers vs heatmap), the inconsistency is visible. Resolved automatically
by P0-1.

### P1-4 — Heatmap `type=violator` silently aliases to `risk`
The frontend requests `type=violator`, but the backend only recognizes `risk|raw|spillover` and
falls back to `risk`. So the "Violator" layer renders identical to the "Risk" layer. Either add a
real `violator` layer (intensity = `violator_risk_score`) or align the frontend to `raw` so the
two-layer theme toggle (CIS vs violation density) is actually demonstrated. (Frontend label fix is
tracked in `PERSON3_STATUS_REPORT.md`; the backend should expose whatever layer name the toggle uses.)

---

## 5. Medium / low priority (P2)

- **P2-1 — `explanations_cache.json` is keyed mostly to mock zones** (1/16 in the real universe).
  After P0-1, regenerate the cache for the real top-N zones (`ml/llm/generate_explanations.py`),
  or rely on the grounded fallback (works fine, just not pre-warmed).
- **P2-2 — FastAPI `@app.on_event("startup")` is deprecated.** Move to a `lifespan` handler to
  silence the warning and future-proof.
- **P2-3 — `db.py`'s deprecation aside:** `requirements.txt` pulls heavy ML libs; confirm the deploy
  uses `requirements-backend.txt` (it does in `render.yaml`) so cloud builds stay fast.
- **P2-4 — Two frontends coexist** (`frontend/app.js` vanilla + `frontend/src` React/TS + `_legacy`).
  Out of scope here, but decide which one is "the" demo build so the backend's CORS/static mount and
  the deploy target are unambiguous.
- **P2-5 — `region: singapore` on Render free tier** spins down when idle; do a warm-up request
  before judging, or bump to `starter`.

---

## 6. Coverage vs the planner's MUST-DO backend scope

| Planner MUST-DO (Person 1 / ML) | Status |
|---|---|
| FastAPI skeleton + CORS, routers, requirements | ✅ Done |
| JSON + in-memory data layer (no DB) | ✅ Done (DB path is dead code — see P1-1) |
| CIS computation + artifact (QUANTIFY) | ✅ Done, real |
| Two-layer heatmap (CIS vs raw) | ✅ Backend supports it; ⚠️ frontend wiring uses `violator` (P1-4) |
| `/hotspots`, `/risk/{id}` breakdown | ✅ Done (but `/hotspots` unused by live frontend) |
| Forecast (PREDICT) with real metrics | ✅ Done, honest |
| Game theory + `/simulate` (OPTIMIZE) | ⚠️ Implemented but on **mock** zones (P0-1) |
| Stations / priority areas | ⚠️ Implemented but on **mock** zones (P0-1) |
| MapMyIndia traffic validation `/traffic/{id}` | ❌ Broken for real zones — wrong file loaded (P0-2) |
| Self-validating agent endpoint | ✅ Done |
| `/explain` (LLM, offline-safe) | ✅ Done |
| `API_DOCS.md` | ✅ Present and accurate |
| Deploy config (Render/Procfile) | ✅ Present |

---

## 7. Recommended fix order (fastest path to "as intended")

1. **P0-1 + P0-2 together** — make `data_loader` build its zone universe from the real CIS artifact
   and load `traffic_context_h3.json`. This single change makes game theory, simulation, stations,
   risk-detail, and traffic-validation all run on real Bengaluru zones whose IDs match the map and
   forecast. (~3–4 h, plus re-running `pytest`.)
2. **P1-2** — re-derive the zone-detail component bars from the real CIS components; label any
   illustrative constants. (~1 h)
3. **P0-3 + P1-1** — fix/delete the stale SQLite status docs and quarantine the dead SQLite code.
   (~30 min)
4. **P1-4** — align the heatmap layer names between frontend and backend so the two-layer theme
   toggle truly shows CIS vs violation density. (~20 min backend side)
5. **P2-1** — regenerate `explanations_cache.json` for the real top zones (optional; fallback works).
6. Re-run `pytest` and the in-process probe; warm up the Render instance before judging.

---

## 8. How this was verified

- Read every file in `backend/app/`, `ml/`, `data/processed/`, `data/enriched/`, `data/mock/`,
  plus `run_pipeline.py`, `render.yaml`, `Procfile`, `requirements*.txt`, the planner, and the docs.
- Booted the app in-process (FastAPI `TestClient`) and called all 20+ endpoints — every one returned
  200.
- Cross-checked zone-ID overlap across `hotspots.json`, `traffic_context.json`,
  `traffic_context_h3.json`, `zone_congestion_impact.json`, `calibrated_scores.json`,
  `explanations_cache.json` (this is how the disjoint-universe defect surfaced).
- Ran `pytest -q` → **126 passed**.

> Note: the numbers and overlaps above were measured against the artifacts committed as of this
> audit. Re-running `run_pipeline.py` will refresh the real artifacts but will **not** by itself fix
> P0-1/P0-2 — those require the loader changes described above.


---

## 9. Resolution log (all items fixed)

Every issue above has been implemented and verified (126 pytest pass + a 23-check
in-process smoke test + a live `uvicorn` HTTP run).

| Issue | Status | What changed |
|---|---|---|
| **P0-1** disjoint zone universes | ✅ Fixed | `data_loader._build_zone_universe()` now builds the served hotspot/OPTIMIZE universe from the **real CIS artifact** (top-60 by volume). Real H3 IDs flow through game theory, simulation, stations, `/risk`, and `/traffic`. |
| **P0-2** wrong traffic file | ✅ Fixed | Loader now reads `traffic_context_h3.json` (H3-keyed). `/traffic/{hotspot}` returns real road names, travel-time ratios, and POIs. |
| **P0-3** stale SQLite docs | ✅ Fixed | `PERSON1_STATUS_REPORT.md` + `BACKEND_CHECKLIST.md` rewritten to the real JSON-in-memory architecture. |
| **P1-1** dead SQLite code | ✅ Fixed (revised) | The SQLite-based **modelling scripts were KEPT in place** — they are the project's real ML work (DBSCAN, the LightGBM+CatBoost ensemble behind `models/`, the Stackelberg/waterbed game theory, ETL). The audit's real concern (reader confusion about which pipeline is canonical) is addressed by **`docs/ML_PIPELINE.md`**, which documents both the offline modelling pipeline and the in-memory serving layer and how to run each. `scripts/verify_backend.py` was rewritten to the real universe (23/23 pass). |
| **P1-2** fabricated component bars | ✅ Fixed | `heavy_vehicle_ratio` = real CIS `vehicle_size`; `density`/`road_importance` real; `peak_weight`/`repeat_offender`/`validation_trust` documented as illustrative. |
| **P1-3** mock CIS values | ✅ Fixed | Resolved automatically by P0-1 (single real universe). |
| **P1-4** heatmap `violator` aliased to `risk` | ✅ Fixed | `/heatmap` now serves 4 distinct layers: `risk` (CIS), `raw` (density), `violator` (game-theory net benefit), `spillover`. |
| **P2-1** explanations cache keyed to mock zones | ✅ Fixed | `ml/llm/generate_explanations.py` regenerates from the real zones; cache now 60/60 real, served as `source="cache"`. |
| **P2-2** deprecated `on_event` startup | ✅ Fixed | `main.py` uses an `asynccontextmanager` `lifespan` handler. |
| **P2-5** Render idle spin-down | ⚠️ Operational | Documented in `render.yaml` (bump to `starter` or warm up before judging) — no code change. |

**Verification snapshot:** `zones_loaded=60`, `congestion_artifact_zones=2527`,
heatmap `risk` top ≠ `raw` top (HAL Old Airport vs Upparpet — density ≠ impact),
`/simulate` coverage scales ~10→43% with 17→5 uncovered high-risk zones,
`/traffic` real for hotspots, `/forecast/accuracy` `is_proxy=false`, 21 real stations.
