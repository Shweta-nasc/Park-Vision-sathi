"""
ParkVision-Saathi — Offline Route Pre-compute
==============================================

Fills ``data/enriched/routes.json`` with road-following driving geometries for
the demo's station → top-hotspot pairs, so the "Route now" feature draws real
road paths even with the network OFF.

It reuses the SAME cache-key + fetch logic the backend ``/route`` endpoint uses
(``backend.app.routers.route``), so a key written here is a guaranteed cache HIT
at request time. The script:

  * is BUDGET-GUARDED   — ``--max-calls`` caps live Mappls calls (default 60);
  * is NON-DESTRUCTIVE  — it MERGES into any existing routes.json, never wipes it;
  * is OFFLINE-SAFE     — skips pairs already cached; a failed call is logged and
    skipped (the pair simply falls back to a straight line at demo time);
  * NEVER leaks the key  — the key stays server-side (read from .env here).

Run:
    source venv/bin/activate
    python ml/enrichment/build_routes.py                # all stations, top 8 hotspots each
    python ml/enrichment/build_routes.py --dry-run      # plan only, no API calls
    python ml/enrichment/build_routes.py --per-station 5 --max-calls 40
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Ensure the repo root is importable when run as a script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.data_loader import store  # noqa: E402
from backend.app.routers.route import (  # noqa: E402
    fetch_route_geometry,
    route_cache_key,
    routing_enabled,
    _mappls_token,
)

OUTPUT_PATH = PROJECT_ROOT / "data" / "enriched" / "routes.json"
SLEEP_BETWEEN_CALLS = 0.3  # polite pacing


def _load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def build_routes(per_station: int = 8, max_calls: int = 60,
                 dry_run: bool = False, output_path: Path = OUTPUT_PATH) -> dict:
    """Pre-compute station→hotspot route geometries into routes.json."""
    store.load()
    stations = store.stations()
    existing = _load_existing(output_path)

    # Build the (origin, destination) pair list: each station → its own top
    # hotspot zones (by enforcement priority), the exact pairs "Route now" hits.
    pairs: list[tuple[dict, dict]] = []
    for s in stations:
        zones = store.station_zones(s["name"])[:per_station]
        for z in zones:
            if z.get("grid_lat") is None or z.get("grid_lon") is None:
                continue
            pairs.append((s, z))

    print(f"\n{'='*60}")
    print("🛣️  ParkVision-Saathi — Route Pre-compute")
    print(f"{'='*60}")
    print(f"   Output:        {output_path}")
    print(f"   Stations:      {len(stations)}")
    print(f"   Pairs to fill: {len(pairs)} (≤{per_station}/station)")
    print(f"   Already cached:{len(existing)}")
    print(f"   Budget:        {max_calls} live calls")
    print(f"   Dry run:       {dry_run}")

    token = _mappls_token()
    if not dry_run and not routing_enabled():
        print("\n⚠️  Live routing disabled (no MAPPLS_STATIC_KEY or "
              "MAPPLS_ROUTING_DISABLED set) — nothing to fetch. "
              "Existing cache left untouched.")
        return existing

    merged = dict(existing)
    calls = 0
    added = 0
    skipped_cached = 0

    for s, z in pairs:
        key = route_cache_key(s["lat"], s["lon"], z["grid_lat"], z["grid_lon"])
        if key in merged and isinstance(merged[key], list) and len(merged[key]) >= 2:
            skipped_cached += 1
            continue
        if dry_run:
            print(f"   [plan] {s['name']} → {z['grid_cell_id']}  ({key})")
            continue
        if calls >= max_calls:
            print(f"\n   ⏹  Budget of {max_calls} calls reached — stopping early.")
            break

        geom = fetch_route_geometry(s["lat"], s["lon"], z["grid_lat"], z["grid_lon"], token)
        calls += 1
        if geom:
            merged[key] = geom
            added += 1
            print(f"   ✅ {s['name']} → {z['grid_cell_id']}  ({len(geom)} pts)")
        else:
            print(f"   ⚠️  {s['name']} → {z['grid_cell_id']}  (no geometry — will fall back)")
        time.sleep(SLEEP_BETWEEN_CALLS)

    if not dry_run and added:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False)

    print(f"\n{'─'*60}")
    print(f"   Live calls used:   {calls}")
    print(f"   Routes added:      {added}")
    print(f"   Already cached:    {skipped_cached}")
    print(f"   Total in cache:    {len(merged)}")
    if not dry_run and added:
        print(f"   ✅ Wrote {output_path}")
    elif dry_run:
        print("   (dry-run — nothing written)")
    else:
        print("   (no new routes added — cache unchanged)")
    return merged


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline route pre-compute for Route now")
    parser.add_argument("--per-station", type=int, default=8,
                        help="Max hotspot destinations per station (default: 8)")
    parser.add_argument("--max-calls", type=int, default=60,
                        help="Budget guard: max live Mappls calls (default: 60)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan without making API calls")
    parser.add_argument("--output", default=str(OUTPUT_PATH),
                        help="Path to write routes.json")
    args = parser.parse_args()

    build_routes(
        per_station=args.per_station,
        max_calls=args.max_calls,
        dry_run=args.dry_run,
        output_path=Path(args.output),
    )
