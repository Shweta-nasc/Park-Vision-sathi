"""
In-process API smoke test (no network server, no database).

Runs the FastAPI app in-process via Starlette's ``TestClient`` and exercises the
main endpoints over the real request layer. This deliberately goes through HTTP
routing rather than calling the route functions directly: the handlers declare
``Query(...)`` defaults that only resolve through the request layer, and several
endpoints now return typed Pydantic models (``CongestionHeatmapResponse``,
``CongestionBreakdown``, ``HotspotItem``, ``SimulationResponse``) — so calling
them as plain functions would pass unresolved ``Query`` objects and break on the
typed responses. ``TestClient`` gives us resolved params and JSON dicts.

Run as a script for a human-readable smoke, or via pytest (``test_api``).
"""

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_api():
    # ── Stations ────────────────────────────────────────────────────────
    print("=== /stations ===")
    r = client.get("/stations")
    assert r.status_code == 200, r.text
    stations = r.json()
    print(f"stations: {len(stations)}")

    station_name = stations[0]["name"] if stations else "Upparpet"
    print(f"=== /stations/{station_name}/priority_areas ===")
    r = client.get(f"/stations/{station_name}/priority_areas", params={"hour": 9, "limit": 3})
    assert r.status_code == 200, r.text
    print(f"priority areas: {len(r.json())}")

    # ── Heatmap (two-layer toggle): risk = CIS, raw = violation count ─────
    print("=== /heatmap?type=risk / type=raw ===")
    risk_hm = client.get("/heatmap", params={"type": "risk"})
    raw_hm = client.get("/heatmap", params={"type": "raw"})
    assert risk_hm.status_code == 200 and raw_hm.status_code == 200
    risk_body, raw_body = risk_hm.json(), raw_hm.json()
    assert risk_body["layer"] == "risk" and raw_body["layer"] == "raw"
    for body in (risk_body, raw_body):
        assert "points" in body and "max_intensity" in body
    print(f"risk points={len(risk_body['points'])} max={risk_body['max_intensity']} | "
          f"raw points={len(raw_body['points'])} max={raw_body['max_intensity']}")

    # ── Hotspots ranked by descending CIS (typed HotspotItem) ─────────────
    print("=== /hotspots ===")
    r = client.get("/hotspots", params={"limit": 5})
    assert r.status_code == 200, r.text
    hotspots = r.json()
    print(f"hotspots: {len(hotspots)}")
    cis_zone = hotspots[0]["zone_id"] if hotspots else None

    # ── Legacy enforcement-risk list ─────────────────────────────────────
    print("=== /risk/top_zones ===")
    r = client.get("/risk/top_zones", params={"hour": 9, "n": 3})
    assert r.status_code == 200, r.text
    top = r.json()
    legacy_zone = top[0]["grid_cell_id"] if top else None
    print(f"top zones: {len(top)}")

    # ── Per-zone CIS breakdown (real CIS zone -> validated CongestionBreakdown)
    if cis_zone:
        print(f"=== /risk/{cis_zone} (real CIS zone) ===")
        r = client.get(f"/risk/{cis_zone}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert 0.0 <= body["congestion_impact"] <= 100.0
        print(f"CIS={body['congestion_impact']} band={body['impact_band']} "
              f"calibrated={body.get('calibrated_impact')}")

    # Unknown zone -> structured 404
    r = client.get("/risk/__definitely_not_a_zone__")
    assert r.status_code == 404
    print("unknown zone -> 404 OK")

    # ── Simulation (typed SimulationResponse) ─────────────────────────────
    print("=== POST /simulate ===")
    r = client.post("/simulate", json={"num_teams": 6, "hour": 9, "strategy": "stackelberg"})
    assert r.status_code == 200, r.text
    sim = r.json()
    assert "assignments" in sim and "coverage_pct" in sim
    print(f"teams={len(sim['assignments'])} coverage={sim['coverage_pct']}% "
          f"spillover={len(sim.get('spillover_zones', []))}")

    # ── Game theory ───────────────────────────────────────────────────────
    print("=== /game/spillover_arrows + /game/whatif_coverage ===")
    arrows = client.get("/game/spillover_arrows")
    whatif = client.get("/game/whatif_coverage")
    assert arrows.status_code == 200 and whatif.status_code == 200
    print(f"arrows={len(arrows.json().get('arrows', []))} "
          f"whatif_keys={len(whatif.json())}")

    # ── Explain + Traffic (use a legacy hotspot zone that the caches key on) ─
    explain_zone = legacy_zone or cis_zone
    if explain_zone:
        print("=== POST /explain ===")
        r = client.post("/explain", json={"zone_id": explain_zone, "hour": 9})
        assert r.status_code == 200, r.text
        assert "explanation" in r.json()
        print("explain OK")

        print(f"=== /traffic/{explain_zone} ===")
        r = client.get(f"/traffic/{explain_zone}")
        assert r.status_code == 200, r.text
        print("traffic OK")

    # ── Self-validating agent report ──────────────────────────────────────
    print("=== /agent/validation-report ===")
    r = client.get("/agent/validation-report")
    assert r.status_code == 200, r.text
    print("agent report OK")


if __name__ == "__main__":
    test_api()
    print("\nAll in-process smoke checks passed.")
