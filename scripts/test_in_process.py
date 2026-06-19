import json
from backend.app.routers import stations, heatmap, risk, simulate, game
from backend.app.models import SimulationRequest

def test_api():
    print("=== Testing list_stations ===")
    res_stations = stations.list_stations()
    print(f"Stations count: {len(res_stations)}")
    if res_stations:
        print("First station:", res_stations[0])
        
    station_name = res_stations[0]["name"] if res_stations else "CHICKPET PS"
    print(f"\n=== Testing priority areas for station: {station_name} ===")
    res_priorities = stations.get_station_priority_areas(station_name, hour=9, limit=3)
    print(f"Priority areas count: {len(res_priorities)}")
    if res_priorities:
        print("First priority area:", res_priorities[0])
        
    print("\n=== Testing heatmap for risk ===")
    res_heatmap = heatmap.get_heatmap(hour=9, type="risk")
    print(f"Heatmap points count: {len(res_heatmap['points'])}")
    print(f"Max intensity: {res_heatmap['max_intensity']}")
    
    print("\n=== Testing top_zones ===")
    res_top = risk.get_top_risk_zones(hour=9, n=3)
    print(f"Top zones count: {len(res_top)}")
    if res_top:
        print("Top zone:", res_top[0])
        
    print("\n=== Testing simulation ===")
    req = SimulationRequest(num_teams=6, hour=9, strategy="stackelberg")
    res_sim = simulate.run_simulation(req)
    print(f"Teams assigned: {len(res_sim.assignments)}")
    print(f"Coverage %: {res_sim.coverage_pct}%")
    print(f"Spillover zones from simulation: {len(res_sim.spillover_zones)}")
    if res_sim.spillover_zones:
        print("First spillover zone in simulation:", res_sim.spillover_zones[0].model_dump())

    print("\n=== Testing spillover arrows endpoint ===")
    res_arrows = game.get_spillover_arrows()
    print(f"Spillover arrows count: {len(res_arrows.get('arrows', []))}")
    if res_arrows.get('arrows'):
        print("First arrow:", res_arrows['arrows'][0])

    print("\n=== Testing whatif coverage endpoint ===")
    res_whatif = game.get_whatif_coverage()
    print(f"What-If keys count: {len(res_whatif.keys())}")
    print("What-If keys:", list(res_whatif.keys()))

if __name__ == "__main__":
    test_api()
