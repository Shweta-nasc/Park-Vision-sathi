"""
In-process end-to-end smoke test for the JSON + in-memory backend (no DB).

Run:  venv/bin/python scripts/verify_backend.py
Exits non-zero if any check fails.
"""

import sys
from fastapi.testclient import TestClient
from backend.app.main import app

CITY_MARKET = "892830828ffffff"   # BGS Flyover, City Market — the demo hero zone
TOP_ZONE = "8928308280fffff"      # Subedar Chatram Road, Upparpet — rank #1

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
check("/health loaded 15 zones", h.get("zones_loaded") == 15)
check("/health data_layer is json-in-memory", h.get("data_layer") == "json-in-memory")

# ── stations ──────────────────────────────────────────────────────────────────
st = client.get("/stations").json()
check("/stations non-empty", isinstance(st, list) and len(st) > 0, f"{len(st)} stations")

# ── heatmap layers ────────────────────────────────────────────────────────────
hm_risk = client.get("/heatmap", params={"type": "risk", "hour": 9}).json()
check("/heatmap?type=risk has 15 points", len(hm_risk["points"]) == 15)
check("/heatmap risk top intensity ~88.7",
      abs(hm_risk["max_intensity"] - 88.7) < 0.5, f"max={hm_risk['max_intensity']}")
hm_raw = client.get("/heatmap", params={"type": "raw"}).json()
check("/heatmap?type=raw uses violation counts (max ~5838)",
      hm_raw["max_intensity"] >= 5000, f"max={hm_raw['max_intensity']}")
hm_sp = client.get("/heatmap", params={"type": "spillover"}).json()
check("/heatmap?type=spillover uses calibrated (max < raw 88.7)",
      hm_sp["max_intensity"] < 88.7, f"max={hm_sp['max_intensity']}")

# ── hotspots / risk ───────────────────────────────────────────────────────────
top = client.get("/risk/top_zones", params={"n": 15}).json()
check("/risk/top_zones returns 15", len(top) == 15)
check("/risk/top_zones sorted desc", top[0]["risk_score"] >= top[-1]["risk_score"])
check("top zone is H3 id (not CELL_)", not top[0]["grid_cell_id"].startswith("CELL_"),
      top[0]["grid_cell_id"])

detail = client.get(f"/risk/{CITY_MARKET}", params={"hour": 9}).json()
check("/risk/{id} City Market raw 85.3", detail["risk_score"] == 85.3)
check("/risk/{id} City Market calibrated 72.1", detail["calibrated_score"] == 72.1)
check("/risk/{id} carries real ratio 1.307", detail["travel_time_ratio"] == 1.307)
check("/risk/{id} has patrol_probability", detail["patrol_probability"] > 0)

# ── traffic (real Mappls) ─────────────────────────────────────────────────────
tr = client.get(f"/traffic/{CITY_MARKET}").json()
check("/traffic City Market ratio 1.307", tr["travel_time_ratio"] == 1.307)
check("/traffic City Market has nearby POIs", len(tr["nearby_pois"]) > 0)

# ── explain: the demo hero number must be reconciled ──────────────────────────
ex = client.post("/explain", json={"zone_id": CITY_MARKET, "hour": 9}).json()
check("/explain City Market is cached", ex["is_cached"] is True)
check("/explain City Market says 1.31x", "1.31x" in ex["explanation"])
check("/explain City Market NO fake 2.40x", "2.40x" not in ex["explanation"])
check("/explain City Market NO '2.4x' claim", "2.4x" not in ex["explanation"])
ex_fallback = client.post("/explain", json={"zone_id": "deadbeef", "hour": 9}).json()
check("/explain unknown zone → graceful fallback", ex_fallback["source"] == "fallback")

# ── game theory ───────────────────────────────────────────────────────────────
sk = client.get("/game/stackelberg_strategy", params={"limit": 100}).json()
check("/game/stackelberg sorted by patrol prob",
      sk[0]["patrol_probability"] >= sk[-1]["patrol_probability"])
check("/game/stackelberg probs ~sum to 1",
      abs(sum(z["patrol_probability"] for z in sk) - 1.0) < 0.01,
      f"sum={sum(z['patrol_probability'] for z in sk):.4f}")
vi = client.get("/game/violator_adaptation").json()
check("/game/violator_adaptation non-empty", len(vi) == 15)
arrows = client.get("/game/spillover_arrows").json()
check("/game/spillover_arrows has arrows", len(arrows["arrows"]) > 0)
check("spillover arrows are H3 (not CELL_)",
      all(not a["from_zone"].startswith("CELL_") for a in arrows["arrows"]))
whatif = client.get("/game/whatif_coverage").json()
check("/game/whatif_coverage monotonic in teams",
      whatif["1"]["coverage_pct"] <= whatif["5"]["coverage_pct"])

# ── simulate ──────────────────────────────────────────────────────────────────
sim = client.post("/simulate", json={"num_teams": 5, "hour": 9}).json()
check("/simulate 5 teams → 5 assignments", len(sim["assignments"]) == 5)
check("/simulate coverage 0-100", 0 <= sim["coverage_pct"] <= 100, f"{sim['coverage_pct']}%")
check("/simulate produces spillover zones", len(sim["spillover_zones"]) > 0)
sim3 = client.post("/simulate", json={"num_teams": 3, "hour": 9}).json()
check("/simulate fewer teams → less coverage",
      sim3["coverage_pct"] <= sim["coverage_pct"],
      f"3 teams={sim3['coverage_pct']}% vs 5 teams={sim['coverage_pct']}%")

# ── forecast ──────────────────────────────────────────────────────────────────
fc = client.get("/forecast/top_risk_zones", params={"n": 10}).json()
check("/forecast/top_risk_zones returns 10", len(fc) == 10)
check("/forecast flagged as proxy", fc[0].get("is_proxy") is True)

# ── agent ─────────────────────────────────────────────────────────────────────
ar = client.get("/agent/validation-report").json()
check("/agent summary 15 validated", ar["summary"]["validated"] == 15)
check("/agent has per-zone log", len(ar["zones"]) == 15)

# ── /api alias works too ──────────────────────────────────────────────────────
api_alias = client.get("/api/risk/top_zones", params={"n": 3}).json()
check("/api/* alias works", len(api_alias) == 3)

print("=" * 72)
if failures:
    print(f"  RESULT: {len(failures)} FAILED → {failures}")
    sys.exit(1)
print("  RESULT: ALL CHECKS PASSED ✅")
print("=" * 72)
