# Person 1 (Backend) — Completion Report

> Verified against `EXECUTION_PLANNER.md`. Person 1 owns the **FastAPI backend**:
> API skeleton, data loading, and every `/api` endpoint feeding the frontend.
>
> **Verification method:** all routes exercised in-process via
> `scripts/test_in_process.py` and FastAPI `TestClient`. Every endpoint returned
> HTTP 200 with real data from `data/parkvision.db`.

---

## Headline

**Backend is functionally complete and working.** All planned endpoints are
implemented, return real data, and handle bad input gracefully. One missing
MUST-DO deliverable (`API_DOCS.md`) was created during this review, and the
declared-but-uninstalled `httpx` dependency was installed.

> **Architecture note:** The shipped backend uses a **grid-cell + SQLite**
> design (`data/parkvision.db`, `grid_cell_id`, `risk_score`) instead of the
> H3 + parquet + in-memory-pandas contract sketched in the planner. This is a
> valid, working substitution — it honours the "no PostgreSQL/Redis/Docker"
> rule and every planned endpoint exists. Field names differ from the planner's
> Pydantic contract (`grid_cell_id` vs `h3_id`, `risk_score` vs
> `congestion_impact`).

---

## What was DONE during this review

| Action | File |
| :-- | :-- |
| Created the missing API documentation (Sprint 7 MUST-DO) with curl examples for every endpoint | `API_DOCS.md` |
| Installed `httpx` (declared in `requirements.txt` but absent from the venv) | environment |
| Verified all endpoints, edge cases, and the in-process test suite pass | — |

---

## Endpoint-by-endpoint status

| Endpoint | Planner ref | Status | Verified result |
| :-- | :-- | :--: | :-- |
| `GET /health` | infra | ✅ | All 5 tables present |
| `GET /` | infra | ✅ | Service index |
| `GET /hotspots` | Sprint 2/3 | ✅ | DBSCAN clusters (468 rows) |
| `GET /risk` | Sprint 4 | ✅ | Risk-scored cells (10,313 rows) |
| `GET /risk/summary` | Sprint 4 | ✅ | Distribution by label |
| `GET /risk/top_zones` | Sprint 4 | ✅ | Top-N zones |
| `GET /risk/overview` | Sprint 4 | ✅ | Dashboard stats |
| `GET /risk/{zone_id}` | Sprint 4/5 | ✅ | Full component breakdown + game-theory join |
| `GET /forecast/zones` | Sprint 5/8 | ✅ | LightGBM predictions (2,033 rows) |
| `GET /forecast/top_risk_zones` | Sprint 8 | ✅ | Top predicted zones |
| `GET /forecast/accuracy` | Sprint 8 | ✅ | **MAE 0.17, RMSE 0.67** |
| `GET /forecast/stations` | Sprint 8 | ✅ | Per-station forecasts |
| `GET /game/stackelberg_strategy` | Sprint 6/8 | ✅ | Patrol probabilities |
| `GET /game/violator_adaptation` | Sprint 9 | ✅ | Violator utility scores |
| `GET /game/spillover_forecast` | Sprint 9 | ✅ | Waterbed effect data |
| `GET /game/summary` | Sprint 7 | ✅ | Combined game summary |
| `GET /game/spillover_arrows` | bonus | ✅ | 767 displacement arrows |
| `GET /game/whatif_coverage` | bonus | ✅ | Coverage for 2–20 teams |
| `POST /simulate` | Sprint 9/10 | ✅ | Allocations + coverage % + spillover |
| `GET /heatmap` | Sprint 2/3 | ✅ | risk / violator / spillover / raw layers |
| `GET /heatmap/patrol_overlay` | bonus | ✅ | Patrol marker overlay |
| `GET /stations` | bonus | ✅ | 54 stations |
| `GET /stations/{station}/priority_areas` | bonus | ✅ | Force + ETA per zone |
| `GET /stations/{station}/summary` | bonus | ✅ | Station breakdown |
| `POST /explain` | Sprint 7+ | ✅ | Data-driven explanation text |
| `GET /traffic/{zone_id}` | Sprint 5/10 | ✅ | Travel-time ratio + POIs |

---

## Planner task checklist (Person 1)

### Setup / Sprint 1 — Skeleton
- [x] GitHub repo + folder structure + `.gitignore` + `README`
- [x] API contract / Pydantic models — `backend/app/models.py`
- [x] FastAPI skeleton with CORS — `backend/app/main.py`
- [x] Router stubs for heatmap, risk, forecast, game, simulate, explain, traffic
- [x] `requirements.txt` (root; declares `fastapi, uvicorn, pandas, numpy, lightgbm, pydantic, httpx`…)

### Sprint 2–4 — Data + real endpoints
- [x] Startup data store available to all routers — `backend/app/db.py` (SQLite helper; replaces planned `data_loader.py`)
- [x] `/heatmap` returns real data per hour/time-bucket
- [x] `/hotspots` returns ranked clusters
- [x] `/risk/{zone_id}` with component breakdown
- [x] Verified responses with test harness

### Sprint 5–7 — Depth + docs
- [x] `/forecast` (real, not mock — exceeds plan)
- [x] `/traffic/{zone_id}` (planned as stretch)
- [x] `/game/strategy` + `/simulate`
- [x] CORS, running instructions (`README.md`)
- [x] All endpoints schema-stable
- [x] **`API_DOCS.md` with curl examples — created in this review**

### Sprint 8–11 — ML + simulation integration
- [x] LightGBM/CatBoost predictions wired to `/forecast`
- [x] Stackelberg wired to `/game/stackelberg_strategy`
- [x] All pre-computed data loaded at startup (SQLite tables + JSON arrows/coverage)
- [x] `/game/violator_adaptation`
- [x] `POST /simulate` with real Stackelberg + spillover

### Sprint 12–14 — Hardening
- [x] Fix bugs / clean API
- [x] Edge cases hardened — invalid `hour`/`num_teams` → `422`; unknown zone → graceful error JSON; unknown heatmap type → graceful error
- [x] Offline-capable — backend serves entirely from local SQLite, no request-time network calls

---

## Remaining items (all STRETCH / optional in the planner)

These are marked 🔶 STRETCH in `EXECUTION_PLANNER.md` and are **not required** for
the demo. None are implemented:

| Item | Planner ref | Priority |
| :-- | :-- | :-- |
| Demo-mode flag (`DEMO_MODE` / `?demo=true` pre-computed responses) | Sprint 7/12/14 | 🔶 Stretch (reliability) |
| In-memory dict caching for expensive endpoints | Sprint 12 | 🔶 Stretch (perf) |
| `GET /api/agent/validation-report` (self-validating agent endpoint) | Sprint 12 | 🔶 Stretch (depends on Person 2 agent data) |
| `GET /heatmap?resolution=` multi-resolution H3 data | Sprint 12 | 🔶 Stretch (depends on Person 2 multi-res aggregation) |

> Note: the two agent/multi-resolution stretches are blocked on Person 2 outputs
> (`calibrated_scores.json`, `zone_impact_res{5,7,8,9}.json`), which are not
> present in `data/processed/`. They cannot be completed by Person 1 alone.

---

## Minor observations (non-blocking)

- `requirements.txt` lists `httpx` but it was not installed in `.venv` — installed during this review. Re-run `pip install -r requirements.txt` on fresh checkouts.
- Several read endpoints return raw `list[dict]`/`dict` rather than declared Pydantic `response_model`s (e.g. `/risk`, `/hotspots`). JSON is valid and stable; adding `response_model` would tighten the OpenAPI schema but is cosmetic.
- `backend/app/db.py` opens a new SQLite connection per query. Fine for demo scale; a cached connection/in-memory load would help under load (overlaps with the stretch caching task).

---

## Verdict

**Person 1 scope: COMPLETE for all MUST-DO (✅) tasks.** Backend runs, every
endpoint serves real data, edge cases are handled, and documentation
(`README.md` + new `API_DOCS.md`) is in place. Only optional 🔶 stretch features
remain, two of which are blocked on Person 2 deliverables.
