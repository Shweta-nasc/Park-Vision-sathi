"""
In-process end-to-end smoke test for the JSON + in-memory backend (no DB).

Run:  PYTHONPATH=. venv/bin/python scripts/verify_backend.py
Exits non-zero if any check fails.

This exercises the REAL zone universe (the top-N CIS hotspots built by
``data_loader._build_zone_universe``), so it uses ids discovered at runtime rather
than hardcoded ones — it stays correct as the artifacts are regenerated.
"""

import sys

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)
failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  — {detail}" if detail else ""))
    if not cond:
        failures.append(name)


print("=" * 72)
print("  BACKEND VERIFICATION — JSON + in-memory (no database)")
print("=" * 72)

# ── health / root ────────────────────────────────────────────────────────────
h = client.get("/health").json()
check("/health ok", h.get("status") == "ok", f"zones_loaded={h.get('zones_loaded')}")
check("/health data_layer is json-in-memory", h.get("data_layer") == "json-in-memory")
check("/health loaded the hotspot universe", (h.get("zones_loaded") or 0) > 0)
check("/health sees the full CIS artifact",
      (h.get("sources", {}).get("congestion_artifact_zones") or 0) > 1000,
      f"{h.get('sources', {}).get('congestion_artifact_zones')} CIS zones")

# ── stations ───────────────────────────────────────────────────────────────────
st = client.get("/stations").json()
check("/stations non-empty", isinstance(st, list) and len(st) > 0, f"{len(st)} stations")

# ── heatmap layers: risk (CIS) and raw (density) must differ ───────────────────
hm_risk = client.get("/heatmap", params={"type": "risk"}).json()
hm_raw = client.get("/heatmap", params={"type": "raw"}).json()
hm_viol = client.get("/heatmap", params={"type": "violator"}).json()
check("/heatmap?type=risk non-empty", len(hm_risk["points"]) > 0)
check("/heatmap?type=raw non-empty", len(hm_raw["points"]) > 0)
check("risk and raw layers are NOT identical (density != impact)",
      hm_risk["points"] and hm_raw["points"]
      and hm_risk["points"][0]["h3_id"] != hm_raw["points"][0]["h3_id"],
      f"risk_top={hm_risk['points'][0]['h3_id']} raw_top={hm_raw['points'][0]['h3_id']}")
check("/heatmap?type=violator distinct layer", hm_viol.get("layer") == "violator")

# ── top zones: real H3 ids, sorted desc ────────────────────────────────────────
top = client.get("/risk/top_zones", params={"n": 15}).json()
check("/risk/top_zones non-empty", len(top) > 0, f"{len(top)} zones")
check("/risk/top_zones sorted desc", top[0]["risk_score"] >= top[-1]["risk_score"])
check("top zone is an H3 id (not a CELL_/mock id)",
      not top[0]["grid_cell_id"].startswith("CELL_")
      and not top[0]["grid_cell_id"].startswith("8928308"),
      top[0]["grid_cell_id"])

TOP_ID = top[0]["grid_cell_id"]

# ── /risk/{id}: real CIS breakdown ─────────────────────────────────────────────
detail = client.get(f"/risk/{TOP_ID}", params={"hour": 9}).json()
check("/risk/{id} returns a CIS breakdown",
      "congestion_impact" in detail and "components" in detail,
      f"CIS={detail.get('congestion_impact')}")
check("/risk/{id} unknown zone -> 404",
      client.get("/risk/deadbeefdeadbeef0000").status_code == 404)

# ── /traffic: at least one hotspot carries REAL MapMyIndia enrichment ──────────
enriched_hit = None
for z in top:
    tr = client.get(f"/traffic/{z['grid_cell_id']}").json()
    if tr.get("travel_time_ratio") and tr.get("road_name"):
        enriched_hit = (z["grid_cell_id"], tr)
        break
check("/traffic carries real MapMyIndia data for a hotspot",
      enriched_hit is not None,
      f"{enriched_hit[0]} ratio={enriched_hit[1]['travel_time_ratio']}" if enriched_hit else "none")

# ── game theory + simulation ───────────────────────────────────────────────────
sk = client.get("/game/stackelberg_strategy", params={"limit": 10}).json()
check("/game/stackelberg_strategy non-empty", len(sk) > 0)
vi = client.get("/game/violator_adaptation", params={"limit": 10}).json()
check("/game/violator_adaptation non-empty", len(vi) > 0)

sim5 = client.post("/simulate", json={"num_teams": 5, "hour": 9, "strategy": "stackelberg"}).json()
sim15 = client.post("/simulate", json={"num_teams": 15, "hour": 9, "strategy": "stackelberg"}).json()
check("/simulate coverage grows with more teams",
      sim15["coverage_pct"] > sim5["coverage_pct"],
      f"5 teams={sim5['coverage_pct']}% < 15 teams={sim15['coverage_pct']}%")
check("/simulate surfaces uncovered high-risk zones",
      len(sim5["uncovered_high_risk"]) > 0,
      f"{len(sim5['uncovered_high_risk'])} uncovered with 5 teams")

# ── forecast (PREDICT pillar) ──────────────────────────────────────────────────
acc = client.get("/forecast/accuracy").json()
check("/forecast/accuracy from a real (non-proxy) model", acc.get("is_proxy") is False,
      acc.get("model"))

# ── agent + explain ────────────────────────────────────────────────────────────
ar = client.get("/agent/validation-report").json()
check("/agent has summary + per-zone log", "summary" in ar and len(ar.get("zones", [])) > 0)
ex = client.post("/explain", json={"zone_id": TOP_ID, "hour": 9}).json()
check("/explain returns text", bool(ex.get("explanation")), f"source={ex.get('source')}")

# ── /api alias ─────────────────────────────────────────────────────────────────
check("/api/* alias works",
      client.get("/api/risk/top_zones", params={"n": 3}).status_code == 200)

print("=" * 72)
if failures:
    print(f"  {len(failures)} CHECK(S) FAILED: {failures}")
    sys.exit(1)
print("  ALL CHECKS PASSED")
print("=" * 72)
