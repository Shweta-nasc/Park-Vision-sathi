"""
ParkVision-Saathi — Pre-generate Explanations for the Top-N REAL Zones
=======================================================================

Pre-warms ``data/processed/explanations_cache.json`` so the ``/explain`` endpoint
serves instantly (``source="cache"``) for the hotspot zones the demo clicks.

The cache is keyed by the SAME real H3 ids the backend serves (the top-N CIS
hotspot universe built by ``data_loader._build_zone_universe``) — NOT the old
mock hotspot ids. This fixes the id mismatch flagged in AUDIT_REPORT.md (P2-1).

Two modes:
  * default (offline, deterministic): build a GROUNDED explanation from each
    zone's real fields — identical in spirit to the endpoint's offline fallback,
    no network, no quota, fully reproducible. This is what we commit.
  * ``--use-gemini``: upgrade to Gemini-quality text where a ``GEMINI_API_KEY`` is
    available (falls back to grounded per-zone on any failure). Use before a demo
    when quota is fresh; the richer text is then cached for offline serving.

Usage:
  PYTHONPATH=. python ml/llm/generate_explanations.py            # offline, top 60
  PYTHONPATH=. python ml/llm/generate_explanations.py --limit 30
  PYTHONPATH=. python ml/llm/generate_explanations.py --use-gemini
  PYTHONPATH=. python ml/llm/generate_explanations.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.data_loader import store
from backend.app.routers.explain import _grounded_fallback, _resolve_zone

CACHE_PATH = PROJECT_ROOT / "data" / "processed" / "explanations_cache.json"


def generate_all(limit: int = 60, hour: int = 9, use_gemini: bool = False,
                 dry_run: bool = False) -> dict:
    store.load()
    zones = store.top_zones(limit)
    print(f"{'='*60}")
    print("ParkVision-Saathi — Explanation pre-generation (real zones)")
    print(f"{'='*60}")
    print(f"  Cache:   {CACHE_PATH}")
    print(f"  Zones:   top {len(zones)} of {len(store.zones)} hotspot universe")
    print(f"  Mode:    {'gemini (upgrade)' if use_gemini else 'grounded (offline, deterministic)'}")
    print(f"  Hour:    {hour:02d}:00 IST")

    if dry_run:
        for i, z in enumerate(zones, 1):
            print(f"  [{i:2d}] {z['grid_cell_id']}  {z.get('station','?')}  "
                  f"CIS={z.get('congestion_impact')}")
        print("\nDry run — nothing written.")
        return {}

    # Optional Gemini client (lazy; only when explicitly requested).
    client = None
    if use_gemini:
        try:
            from ml.llm.gemini_client import GeminiClient
            client = GeminiClient()
        except Exception as e:  # pragma: no cover - optional path
            print(f"  ! Gemini unavailable ({e}); falling back to grounded for all zones.")
            client = None

    cache: dict = {}
    gemini_n = grounded_n = 0
    for i, z in enumerate(zones, 1):
        zid = z["grid_cell_id"]
        resolved = _resolve_zone(zid) or {}
        text = None
        built_by = "grounded"

        if client is not None:
            tc = {
                "travel_time_ratio": z.get("travel_time_ratio") or 1.0,
                "road_name": z.get("road_name"),
                "nearby_pois": z.get("nearby_pois", []),
            }
            try:
                result = client.explain_zone(z, tc, hour=hour)
                if result and result.get("source") == "gemini" and result.get("explanation"):
                    text, built_by = result["explanation"], "gemini"
                    gemini_n += 1
            except Exception:
                text = None

        if text is None:
            text = _grounded_fallback(resolved, hour) if resolved else (
                f"Zone {zid} is a monitored parking-enforcement hotspot.")
            grounded_n += 1

        cache[zid] = {
            "zone_id": zid,
            "explanation": text,
            "source": "cache",       # how the endpoint reports a cache hit
            "generated_by": built_by,  # how this entry was actually built
        }
        if i <= 3 or i == len(zones):
            print(f"  [{i:2d}/{len(zones)}] {zid} -> {text[:70]}...")
        # polite delay only between successful Gemini calls
        if client is not None and built_by == "gemini" and i < len(zones):
            time.sleep(4.5)

    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)
    print(f"\n{'='*60}")
    print(f"Wrote {len(cache)} explanations  (gemini={gemini_n}, grounded={grounded_n})")
    print(f"  -> {CACHE_PATH}")
    print(f"{'='*60}")
    return cache


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pre-generate /explain cache for the real top-N zones")
    parser.add_argument("--limit", default=60, type=int, help="Top-N zones (default: 60 = full hotspot universe)")
    parser.add_argument("--hour", default=9, type=int, help="Peak hour used in the text (default: 9)")
    parser.add_argument("--use-gemini", action="store_true", help="Upgrade to Gemini text where available")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without writing")
    args = parser.parse_args()
    generate_all(limit=args.limit, hour=args.hour, use_gemini=args.use_gemini, dry_run=args.dry_run)
