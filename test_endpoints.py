"""Quick endpoint integration test."""
import urllib.request
import json

BASE = "http://localhost:8000"
endpoints = [
    "/health",
    "/stations",
    "/heatmap?hour=9&type=risk",
    "/risk/top_zones?hour=9&n=5",
    "/risk/summary?hour=9",
    "/game/stackelberg_strategy?hour=9",
    "/game/violator_adaptation?hour=9",
    "/game/spillover_forecast?hour=9",
    "/game/spillover_arrows",
    "/game/whatif_coverage",
    "/game/summary?hour=9",
    "/forecast/zones?hour=9&n=5",
    "/forecast/accuracy",
    "/stations/Upparpet/priority_areas?hour=9&limit=5",
    "/stations/Upparpet/summary?hour=9",
]

print("=" * 60)
print("ENDPOINT INTEGRATION TEST")
print("=" * 60)
passed = 0
failed = 0
for ep in endpoints:
    try:
        r = urllib.request.urlopen(f"{BASE}{ep}")
        data = json.loads(r.read())
        kind = type(data).__name__
        size = len(data) if isinstance(data, (list, dict)) else "?"
        print(f"  PASS  {ep}  ({kind}, {size} items)")
        passed += 1
    except Exception as e:
        print(f"  FAIL  {ep}  -> {e}")
        failed += 1

print("=" * 60)
print(f"Results: {passed} passed, {failed} failed out of {len(endpoints)}")
print("=" * 60)
