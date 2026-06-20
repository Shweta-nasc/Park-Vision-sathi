"""
ParkVision-Saathi — MapMyIndia Enrichment Script
=================================================

Queries Mappls APIs for top-20 hotspot zones and saves enriched
traffic context to data/enriched/traffic_context.json.

APIs used per zone:
  1. distance_matrix     — baseline travel time to city centre (no traffic)
  2. distance_matrix_eta — live-traffic travel time → travel_time_ratio
  3. Nearby API          — POIs within 800m (bus stops, hospitals, schools)
  4. Reverse Geocode     — road name and pincode

Output format (contract with Person 1 / backend DataStore):
{
  "8928308280fffff": {
    "zone_id": "8928308280fffff",
    "lat": 12.977343,
    "lon": 77.575702,
    "station": "Upparpet",
    "travel_time_to_center_sec": 141.0,
    "travel_time_eta_sec": 424.5,
    "travel_time_ratio": 3.01,
    "travel_time_baseline_min": 2.4,
    "travel_time_eta_min": 7.1,
    "road_name": "Subedar Chatram Road",
    "pincode": "560009",
    "nearby_pois": ["Bus Stop (112m)", "Flix Bus Bengaluru (197m)"],
    "api_enriched": true
  },
  ...
}

Run:
  source venv/bin/activate
  python ml/enrichment/mapmyindia.py

Flags:
  --dry-run    Print plan without making API calls (for testing)
  --limit N    Process only first N zones (default: 20)
"""

from __future__ import annotations

import os
import sys
import json
import time
import argparse
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ─── Config ──────────────────────────────────────────────────────────────────

load_dotenv()
ACCESS_TOKEN = os.getenv("MAPPLS_STATIC_KEY")
if not ACCESS_TOKEN:
    print("❌ MAPPLS_STATIC_KEY not found in .env — cannot run enrichment")
    sys.exit(1)

# Fixed control point: Bengaluru city centre (Vidhana Soudha area)
# All travel times are measured FROM hotspot TO this point (consistent baseline)
CONTROL_LAT = 12.9716
CONTROL_LON = 77.5946

# Rate limiting — Mappls free tier is lenient but stay safe
SLEEP_BETWEEN_ZONES = 0.6   # seconds between zones
SLEEP_BETWEEN_APIS  = 0.3   # seconds between API calls within one zone
API_TIMEOUT         = 20    # seconds per request

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_PATH   = PROJECT_ROOT / "data" / "mock" / "hotspots.json"
OUTPUT_DIR   = PROJECT_ROOT / "data" / "enriched"
OUTPUT_PATH  = OUTPUT_DIR / "traffic_context.json"

# Mappls API base URLs
DM_BASE  = "https://route.mappls.com/route/dm"
RG_BASE  = "https://search.mappls.com/search/address/rev-geocode"
POI_BASE = "https://search.mappls.com/search/places/nearby/json"


# ─── API Helpers ─────────────────────────────────────────────────────────────

def _get(url: str, params: dict, label: str) -> dict | None:
    """Shared GET wrapper with timeout and error handling."""
    try:
        resp = httpx.get(url, params=params, timeout=API_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        print(f"      ⚠️  {label}: HTTP {resp.status_code}")
        return None
    except httpx.TimeoutException:
        print(f"      ⚠️  {label}: timeout after {API_TIMEOUT}s")
        return None
    except httpx.RequestError as e:
        print(f"      ⚠️  {label}: request error — {e}")
        return None
    except json.JSONDecodeError:
        print(f"      ⚠️  {label}: invalid JSON response")
        return None


def get_distance_matrix(lat: float, lon: float, resource: str) -> float | None:
    """Query Mappls Distance Matrix API. Returns duration in seconds or None.

    resource: "distance_matrix" (no traffic) or "distance_matrix_eta" (live traffic)
    Coordinate format: lon,lat (longitude FIRST per Mappls spec).
    """
    # FROM hotspot → TO city centre
    coords = f"{lon},{lat};{CONTROL_LON},{CONTROL_LAT}"
    url    = f"{DM_BASE}/{resource}/driving/{coords}"
    params = {"access_token": ACCESS_TOKEN, "rtype": 0, "region": "ind"}

    data = _get(url, params, resource)
    if not data:
        return None

    results = data.get("results", {})
    if results.get("code") != "Ok":
        return None

    durations = results.get("durations", [[]])
    if len(durations[0]) < 2:
        return None

    return float(durations[0][1])  # source→dest duration in seconds


def get_reverse_geocode(lat: float, lon: float) -> dict:
    """Query Mappls Reverse Geocode API.

    Extracts all useful fields from the single API call:
      road_name, pincode, formatted_address, street, street_dist_m,
      locality, sub_locality, district, city, state
    """
    params = {"lat": lat, "lng": lon, "access_token": ACCESS_TOKEN}
    data   = _get(RG_BASE, params, "reverse_geocode")

    out = {
        "road_name":         None,
        "pincode":           None,
        "formatted_address": None,
        "street":            None,
        "street_dist_m":     None,
        "locality":          None,
        "sub_locality":      None,
        "district":          None,
        "city":              None,
        "state":             None,
    }
    if not data:
        return out

    results = data.get("results", [])
    if not results:
        return out

    r = results[0]

    street   = r.get("street",      "") or ""
    locality = r.get("locality",    "") or ""
    sub_loc  = r.get("subLocality", "") or ""

    # road_name: street + locality (backward-compatible with existing contract)
    out["road_name"]         = f"{street}, {locality}".strip(", ") or None
    out["pincode"]           = r.get("pincode") or None
    out["formatted_address"] = r.get("formatted_address") or None
    out["street"]            = street or None
    out["street_dist_m"]     = r.get("street_dist") or None  # metres from centroid to road
    out["locality"]          = locality or None
    out["sub_locality"]      = sub_loc or None
    out["district"]          = r.get("district") or None
    out["city"]              = r.get("city") or None
    out["state"]             = r.get("state") or None

    return out


def get_nearby_pois(lat: float, lon: float, keywords: str = "bus stop", radius: int = 800) -> tuple[list[str], list[dict]]:
    """Query Mappls Nearby API. Returns:
      - pois_str: list of "Name (dist m)" strings (backward-compatible)
      - pois_detailed: list of {name, distance_m, eloc, address, category_codes} dicts

    Note: Mappls Nearby API returns eLoc (place code) + address, NOT lat/lon.
    To get coordinates, a secondary Place Details call on eLoc would be needed.
    """
    params = {
        "keywords":    keywords,
        "refLocation": f"{lat},{lon}",
        "radius":      radius,
        "region":      "IND",
        "sortBy":      "dist:asc",
        "page":        1,
        "access_token": ACCESS_TOKEN,
    }
    data = _get(POI_BASE, params, "nearby_poi")
    if not data:
        return [], []

    pois_str      = []
    pois_detailed = []
    for item in data.get("suggestedLocations", [])[:5]:
        name     = item.get("placeName", "POI")
        dist     = item.get("distance", "?")
        eloc     = item.get("eLoc", "")          # Mappls unique place ID
        address  = item.get("placeAddress", "")  # Full address string
        keywords_raw = item.get("keywords", [])  # Category codes e.g. ["TRNBUS"]

        pois_str.append(f"{name} ({dist}m)")
        pois_detailed.append({
            "name":           name,
            "distance_m":     dist,
            "eloc":           eloc,       # Mappls place code (use for further lookups)
            "address":        address,    # Full street address
            "category_codes": keywords_raw,  # e.g. ["TRNBUS"] = bus, ["HOSP"] = hospital
        })
    return pois_str, pois_detailed




# ─── Enrichment Logic ────────────────────────────────────────────────────────

def enrich_zone(spot: dict, dry_run: bool = False) -> dict:
    """Enrich one hotspot zone with all Mappls data. Returns context dict."""
    zone_id = spot["h3_id"] if "h3_id" in spot else spot.get("zone_id", "unknown")
    lat     = float(spot["lat"])
    lon     = float(spot["lon"])
    station = spot.get("station", "")

    base_result = {
        "zone_id":                   zone_id,
        "lat":                       lat,
        "lon":                       lon,
        "station":                   station,
        "travel_time_to_center_sec": None,
        "travel_time_eta_sec":       None,
        "travel_time_ratio":         1.0,
        "travel_time_baseline_min":  None,
        "travel_time_eta_min":       None,
        "road_name":                 None,
        "street":                    None,
        "street_dist_m":             None,
        "locality":                  None,
        "sub_locality":              None,
        "district":                  None,
        "city":                      None,
        "state":                     None,
        "pincode":                   None,
        "formatted_address":         None,
        "nearby_pois":               [],
        "nearby_pois_detailed":       [],
        "api_enriched":              False,
    }

    if dry_run:
        return {**base_result, "api_enriched": False, "_dry_run": True}

    print(f"   → Distance Matrix (baseline)...")
    baseline_s = get_distance_matrix(lat, lon, "distance_matrix")
    time.sleep(SLEEP_BETWEEN_APIS)

    print(f"   → Distance Matrix ETA (live traffic)...")
    eta_s = get_distance_matrix(lat, lon, "distance_matrix_eta")
    time.sleep(SLEEP_BETWEEN_APIS)

    print(f"   → Reverse Geocode...")
    geocode = get_reverse_geocode(lat, lon)
    time.sleep(SLEEP_BETWEEN_APIS)

    print(f"   → Nearby POIs (bus stops)...")
    pois_str, pois_detailed = get_nearby_pois(lat, lon, keywords="bus stop", radius=800)
    time.sleep(SLEEP_BETWEEN_APIS)

    # Compute travel_time_ratio — the key metric for CongestionImpactScore
    if baseline_s and baseline_s > 0:
        ratio = (eta_s / baseline_s) if eta_s else 1.0
    else:
        ratio = 1.0  # unknown: assume free flow

    # Build result
    result = {
        "zone_id":                   zone_id,
        "lat":                       lat,
        "lon":                       lon,
        "station":                   station,
        "travel_time_to_center_sec": baseline_s,
        "travel_time_eta_sec":       eta_s,
        "travel_time_ratio":         round(ratio, 3),
        "travel_time_baseline_min":  round(baseline_s / 60, 1) if baseline_s else None,
        "travel_time_eta_min":       round(eta_s / 60, 1)      if eta_s      else None,
        # Reverse Geocode fields — all from single API call
        "road_name":                 geocode.get("road_name"),
        "street":                    geocode.get("street"),
        "street_dist_m":             geocode.get("street_dist_m"),
        "locality":                  geocode.get("locality"),
        "sub_locality":              geocode.get("sub_locality"),
        "district":                  geocode.get("district"),
        "city":                      geocode.get("city"),
        "state":                     geocode.get("state"),
        "pincode":                   geocode.get("pincode"),
        "formatted_address":         geocode.get("formatted_address"),
        # Nearby API fields
        "nearby_pois":               pois_str,
        "nearby_pois_detailed":       pois_detailed,
        "api_enriched":              baseline_s is not None,
    }

    # Log result inline
    if baseline_s:
        ratio_str = f"{ratio:.2f}x"
        congestion = "🔴 CRITICAL" if ratio > 2.5 else "🟠 HIGH" if ratio > 1.5 else "🟡 MODERATE" if ratio > 1.2 else "🟢 LOW"
        print(f"   ✅ Baseline: {baseline_s/60:.1f}min | ETA: {(eta_s or 0)/60:.1f}min | Ratio: {ratio_str} {congestion}")
    else:
        print(f"   ⚠️  API call failed — using fallback (ratio=1.0)")

    return result


def enrich_hotspots(
    input_path: Path = INPUT_PATH,
    output_path: Path = OUTPUT_PATH,
    limit: int = 20,
    dry_run: bool = False,
) -> dict:
    """
    Main enrichment function. Reads hotspot list, queries Mappls APIs for each
    zone, writes output to traffic_context.json.

    Args:
        input_path:  Path to hotspots JSON (list of HotspotItem dicts)
        output_path: Where to write enriched output
        limit:       Max zones to process (default 20, per planner spec)
        dry_run:     Skip API calls, just validate input/output shapes

    Returns:
        Dict keyed by h3_id/zone_id
    """
    print(f"\n{'='*60}")
    print("🗺️  ParkVision-Saathi — MapMyIndia Enrichment")
    print(f"{'='*60}")
    print(f"   Input:    {input_path}")
    print(f"   Output:   {output_path}")
    print(f"   Key:      {ACCESS_TOKEN[:8]}...{ACCESS_TOKEN[-4:]}")
    print(f"   Control:  ({CONTROL_LAT}, {CONTROL_LON}) — Bengaluru city centre")
    print(f"   Dry run:  {dry_run}")

    # Load hotspots
    if not input_path.exists():
        print(f"\n❌ Input file not found: {input_path}")
        sys.exit(1)

    with open(input_path) as f:
        hotspots = json.load(f)

    # Handle both list (HotspotItem[]) and dict (keyed by h3_id) inputs
    if isinstance(hotspots, dict):
        hotspot_list = list(hotspots.values())
    else:
        hotspot_list = hotspots

    zones = hotspot_list[:limit]
    print(f"\n   Zones to process: {len(zones)} of {len(hotspot_list)} total")
    print(f"{'─'*60}")

    # Create output directory
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Enrich each zone
    results = {}
    failed  = 0

    for i, spot in enumerate(zones, 1):
        zone_id = spot.get("h3_id") or spot.get("zone_id", f"zone_{i}")
        station = spot.get("station", "?")
        rank    = spot.get("rank", i)

        print(f"\n[{i:2d}/{len(zones)}] Zone: {zone_id}")
        print(f"   Station: {station} | Rank #{rank} | ({spot['lat']:.4f}, {spot['lon']:.4f})")

        enriched = enrich_zone(spot, dry_run=dry_run)
        results[zone_id] = enriched

        if not enriched["api_enriched"] and not dry_run:
            failed += 1

        # Save incrementally after each zone so partial results survive a crash
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        # Rate limit between zones
        if i < len(zones) and not dry_run:
            time.sleep(SLEEP_BETWEEN_ZONES)

    # Final summary
    print(f"\n{'='*60}")
    print("📊 ENRICHMENT COMPLETE")
    print(f"{'='*60}")
    print(f"   Zones processed: {len(results)}")
    print(f"   API enriched:    {len(results) - failed}")
    print(f"   Fallback used:   {failed}")
    print(f"   Output saved:    {output_path}")

    # Ratio summary
    ratios = [v["travel_time_ratio"] for v in results.values() if v["travel_time_ratio"] > 1.0]
    if ratios:
        print(f"\n   Travel Time Ratio stats:")
        print(f"   Min:    {min(ratios):.2f}x")
        print(f"   Max:    {max(ratios):.2f}x")
        print(f"   Median: {sorted(ratios)[len(ratios)//2]:.2f}x")

    critical = sum(1 for v in results.values() if v["travel_time_ratio"] > 2.5)
    print(f"\n   🔴 CRITICAL zones (ratio > 2.5x): {critical}")
    print(f"   → These zones get maximum traffic_degradation_component weight")

    print(f"\n✅ traffic_context.json ready — Person 1 can load this into DataStore")
    return results


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MapMyIndia enrichment for top-20 hotspots")
    parser.add_argument("--input",   default=str(INPUT_PATH),  help="Path to hotspots JSON")
    parser.add_argument("--output",  default=str(OUTPUT_PATH), help="Path to write traffic_context.json")
    parser.add_argument("--limit",   default=20, type=int,     help="Max zones to process (default: 20)")
    parser.add_argument("--dry-run", action="store_true",       help="Skip API calls, validate shapes only")
    args = parser.parse_args()

    enrich_hotspots(
        input_path  = Path(args.input),
        output_path = Path(args.output),
        limit       = args.limit,
        dry_run     = args.dry_run,
    )
