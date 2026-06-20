"""
ParkVision-Saathi — Pre-generate Explanations for Top-20 Zones
===============================================================

Sprint 9 task: Pre-generate Gemini explanations for all top-20 hotspot zones
so the /api/explain endpoint never makes a live API call during the demo.

Priority chain used per zone:
  1. Already in cache → skip (no API call)
  2. Not in cache → call Gemini → save to cache
  3. Gemini fails   → save fallback text to cache

Output:
  data/processed/explanations_cache.json  (updated in-place)

Run ONCE before the demo (ideally morning of Day 3 when Gemini quota resets):
  source venv/bin/activate
  python ml/llm/generate_explanations.py

Flags:
  --limit N          Only generate for top-N zones (default: 20)
  --hour H           Peak hour to use in prompts (default: 9 = morning_peak)
  --force            Regenerate even if already cached (use for quality upgrade)
  --dry-run          Show what would be generated without calling API

Gemini free tier: 15 RPM, 1500 RPD — this script uses 4.5s delay = ~13 RPM.
Run at 09:00 IST for fresh daily quota.
"""

from __future__ import annotations

import sys
import json
import time
import argparse
from pathlib import Path

# Ensure project root is on path so ml.llm imports work
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ml.llm.gemini_client import GeminiClient

# ─── Paths ───────────────────────────────────────────────────────────────────

HOTSPOTS_PATH    = PROJECT_ROOT / "data" / "mock"      / "hotspots.json"
TRAFFIC_PATH     = PROJECT_ROOT / "data" / "enriched"  / "traffic_context.json"
CACHE_PATH       = PROJECT_ROOT / "data" / "processed" / "explanations_cache.json"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict | list:
    with open(path) as f:
        return json.load(f)


def zones_already_cached(cache: dict, hotspots: list, force: bool) -> tuple[list, list]:
    """Split hotspot list into (to_generate, already_done)."""
    to_gen, done = [], []
    for h in hotspots:
        zid = h.get("zone_id", h.get("h3_id", "unknown"))
        if zid in cache and not force:
            done.append(zid)
        else:
            to_gen.append(h)
    return to_gen, done


# ─── Main ────────────────────────────────────────────────────────────────────

def generate_all(
    limit: int = 20,
    hour: int = 9,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Pre-generate explanations for top-`limit` hotspot zones.

    Returns final cache dict.
    """
    print(f"\n{'='*60}")
    print("🤖 ParkVision-Saathi — Explanation Pre-generation")
    print(f"{'='*60}")
    print(f"   Input hotspots:    {HOTSPOTS_PATH}")
    print(f"   Traffic context:   {TRAFFIC_PATH}")
    print(f"   Cache output:      {CACHE_PATH}")
    print(f"   Limit:             {limit} zones")
    print(f"   Hour:              {hour}:00 IST")
    print(f"   Force regenerate:  {force}")
    print(f"   Dry run:           {dry_run}")

    # Load data
    if not HOTSPOTS_PATH.exists():
        print(f"\n❌ Hotspots file not found: {HOTSPOTS_PATH}")
        sys.exit(1)

    hotspots = load_json(HOTSPOTS_PATH)
    if isinstance(hotspots, dict):
        hotspots = list(hotspots.values())
    hotspots = hotspots[:limit]

    traffic_ctx: dict = {}
    if TRAFFIC_PATH.exists():
        traffic_ctx = load_json(TRAFFIC_PATH)
        print(f"   Traffic zones:     {len(traffic_ctx)} loaded")
    else:
        print(f"   ⚠️  Traffic context not found — travel_time_ratio will default to 1.0")

    # Load existing cache
    cache: dict = {}
    if CACHE_PATH.exists():
        cache = load_json(CACHE_PATH)
        print(f"   Existing cache:    {len(cache)} entries")

    # Split into to-do and done
    to_generate, already_done = zones_already_cached(cache, hotspots, force)

    print(f"\n   Already cached:    {len(already_done)} zones → SKIP")
    print(f"   To generate:       {len(to_generate)} zones")

    if not to_generate:
        print("\n✅ All zones already cached — nothing to do. Run with --force to regenerate.")
        return cache

    if dry_run:
        print("\n🔍 DRY RUN — zones that would be generated:")
        for i, h in enumerate(to_generate, 1):
            zid = h.get("zone_id", h.get("h3_id"))
            print(f"   [{i:2d}] {zid} ({h.get('station', '?')}) — impact {h.get('congestion_impact', '?')}")
        print("\nRun without --dry-run to actually generate.")
        return cache

    # Initialise client
    client = GeminiClient()
    print(f"\n{'─'*60}")
    print("Starting generation...")
    print(f"{'─'*60}")

    results = {}
    gemini_count  = 0
    cache_count   = 0
    fallback_count = 0

    for i, spot in enumerate(to_generate, 1):
        zid = spot.get("zone_id", spot.get("h3_id", f"zone_{i}"))
        tc  = traffic_ctx.get(zid, {})

        station = spot.get("station", "?")
        impact  = spot.get("congestion_impact", 50.0)

        print(f"\n  [{i:2d}/{len(to_generate)}] {zid}")
        print(f"   Station: {station} | Impact: {impact}/100 | Ratio: {tc.get('travel_time_ratio', 'N/A')}")
        print(f"   ", end="", flush=True)

        t0 = time.monotonic()
        result = client.explain_zone(spot, tc, hour=hour)
        elapsed = time.monotonic() - t0

        src = result["source"]
        print(f"→ {src} ({elapsed:.1f}s)")

        if src == "gemini":
            gemini_count += 1
        elif src == "cache":
            cache_count += 1
        else:
            fallback_count += 1

        results[zid] = result

        # Rate limiting: Gemini free tier = 15 RPM
        # We sleep 4.5s after each Gemini call → ~13 RPM (safe margin)
        if src == "gemini" and i < len(to_generate):
            time.sleep(4.5)

    # Final summary
    total_cache = len(already_done) + cache_count
    print(f"\n{'='*60}")
    print("📊 GENERATION COMPLETE")
    print(f"{'='*60}")
    print(f"   Total zones processed:  {len(to_generate)}")
    print(f"   Via Gemini API:         {gemini_count}")
    print(f"   From cache (skipped):   {cache_count}")
    print(f"   Via fallback:           {fallback_count}")
    print(f"   Total in cache now:     {total_cache + gemini_count + fallback_count}")
    print(f"   Cache file:             {CACHE_PATH}")

    if fallback_count > 0:
        print(f"\n   ⚠️  {fallback_count} zones used fallback — Gemini quota may be exhausted.")
        print(f"   → Run this script again when quota resets (midnight PST)")
        print(f"   → Or the 5 seed entries cover the top-5 zones for demo")
    else:
        print(f"\n   ✅ All zones have Gemini-quality explanations in cache")
        print(f"   ✅ /api/explain endpoint is fully pre-warmed — no live API calls during demo")

    return results


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pre-generate Gemini explanations for top-20 hotspot zones"
    )
    parser.add_argument("--limit",   default=20,  type=int,  help="Max zones to generate (default: 20)")
    parser.add_argument("--hour",    default=9,   type=int,  help="Peak hour for prompts (default: 9)")
    parser.add_argument("--force",   action="store_true",    help="Regenerate even if already cached")
    parser.add_argument("--dry-run", action="store_true",    help="Show plan without calling API")
    args = parser.parse_args()

    generate_all(
        limit   = args.limit,
        hour    = args.hour,
        force   = args.force,
        dry_run = args.dry_run,
    )
