"""
ParkVision-Saathi — MapMyIndia / Mappls API Smoke Tests
========================================================

Tests three Mappls APIs that Stage 2 (enrichment) depends on:
  1. reverse_geocode  — get road name for a lat/lon
  2. nearby           — get POIs (bus stops, etc.) around a point
  3. distance_matrix  — baseline travel time (no traffic)
  4. distance_matrix_eta — live-traffic travel time → travel_time_ratio

Sample points:
  Point A: Upparpet / Gandhi Nagar (top hotspot from dataset)  → 12.9773, 77.5757
  Point B: Majestic / KBS (city transport hub control point)   → 12.9767, 77.5713

Run:
  source venv/bin/activate
  python ml/enrichment/test_mapmyindia.py
"""

import os
import sys
import json
import httpx
from dotenv import load_dotenv

# ─── Auth ────────────────────────────────────────────────────────────────────

load_dotenv()
STATIC_KEY = os.getenv("MAPPLS_STATIC_KEY")
if not STATIC_KEY:
    raise ValueError("MAPPLS_STATIC_KEY missing in .env")

TIMEOUT = 20

# Sample coordinates — using real top-1 hotspot from the dataset
# Point A: Upparpet / Elite Junction (rank-1 hotspot, 5,838 violation records)
POINT_A = {"name": "Upparpet / Elite Junction", "lat": 12.977343, "lon": 77.575702}
# Point B: Majestic KBS — used as fixed control point for travel-time comparison
POINT_B = {"name": "Majestic (KBS)", "lat": 12.9767, "lon": 77.5713}


# ─── 1. Reverse Geocode ───────────────────────────────────────────────────────

def reverse_geocode():
    """Get road name/address for Point A's lat/lon."""
    url = "https://search.mappls.com/search/address/rev-geocode"
    params = {"lat": POINT_A["lat"], "lng": POINT_A["lon"], "access_token": STATIC_KEY}

    print(f"\n{'─' * 60}")
    print("📡 Test 1: Reverse Geocode")
    print(f"   Coords: {POINT_A['lat']}, {POINT_A['lon']}  ({POINT_A['name']})")

    r = httpx.get(url, params=params, timeout=TIMEOUT)
    print(f"   HTTP Status: {r.status_code}")
    print(f"   Response: {r.text[:500]}")
    return r


# ─── 2. Nearby POIs ──────────────────────────────────────────────────────────

def nearby():
    """Get bus stops within 1 km of Point A — used for access_blockage_component."""
    url = "https://search.mappls.com/search/places/nearby/json"
    params = {
        "keywords": "bus stop",
        "refLocation": f"{POINT_A['lat']},{POINT_A['lon']}",
        "radius": 1000,
        "region": "IND",
        "sortBy": "dist:asc",
        "page": 1,
        "access_token": STATIC_KEY,
    }

    print(f"\n{'─' * 60}")
    print("📡 Test 2: Nearby POIs (bus stops within 1 km)")
    print(f"   Center: {POINT_A['lat']}, {POINT_A['lon']}  ({POINT_A['name']})")

    r = httpx.get(url, params=params, timeout=TIMEOUT)
    print(f"   HTTP Status: {r.status_code}")
    print(f"   Response: {r.text[:500]}")
    return r


# ─── 3 & 4. Distance Matrix ──────────────────────────────────────────────────

BASE_DM_URL = "https://route.mappls.com/route/dm"

def _build_dm_url(resource: str) -> str:
    """Build Distance Matrix URL. API expects lon,lat (longitude FIRST)."""
    coords = f"{POINT_A['lon']},{POINT_A['lat']};{POINT_B['lon']},{POINT_B['lat']}"
    return f"{BASE_DM_URL}/{resource}/driving/{coords}"

def _call_dm(resource: str) -> dict | None:
    """Call one Distance Matrix resource and return parsed result dict."""
    url = _build_dm_url(resource)
    params = {"access_token": STATIC_KEY, "rtype": 0, "region": "ind"}

    print(f"\n{'─' * 60}")
    print(f"📡 Test {'3' if resource == 'distance_matrix' else '4'}: {resource}")
    print(f"   From: {POINT_A['name']} ({POINT_A['lat']}, {POINT_A['lon']})")
    print(f"   To:   {POINT_B['name']} ({POINT_B['lat']}, {POINT_B['lon']})")

    try:
        resp = httpx.get(url, params=params, timeout=TIMEOUT)
        print(f"   HTTP Status: {resp.status_code}")

        if resp.status_code != 200:
            print(f"   ❌ Non-200: {resp.text[:300]}")
            return None

        data = resp.json()
        results = data.get("results", {})
        if results.get("code") != "Ok":
            print(f"   ❌ code != Ok: {results}")
            return None

        dist_m  = results["distances"][0][1]
        dur_s   = results["durations"][0][1]
        print(f"   ✅ Distance: {dist_m:.1f} m ({dist_m/1000:.2f} km)")
        print(f"   ✅ Duration: {dur_s:.1f} s ({dur_s/60:.1f} min)")
        return {"resource": resource, "distance_m": dist_m, "duration_s": dur_s}

    except (httpx.TimeoutException, httpx.RequestError, json.JSONDecodeError) as e:
        print(f"   ❌ Error: {e}")
        return None

def distance_matrix():
    """Test distance_matrix (baseline, no traffic)."""
    return _call_dm("distance_matrix")

def distance_matrix_eta():
    """Test distance_matrix_eta (live traffic delays, India only)."""
    return _call_dm("distance_matrix_eta")


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🧪 MapMyIndia / Mappls API Smoke Tests")
    print("=" * 60)
    print(f"   Key: {STATIC_KEY[:8]}...{STATIC_KEY[-4:]}")

    # Run all tests
    reverse_geocode()
    nearby()
    baseline = distance_matrix()
    eta      = distance_matrix_eta()

    # Summary
    print(f"\n{'=' * 60}")
    print("📊 DISTANCE MATRIX SUMMARY")
    print(f"{'=' * 60}")

    if baseline:
        print(f"   Baseline (no traffic): {baseline['duration_s']/60:.1f} min")
    else:
        print("   ❌ Baseline FAILED")

    if eta:
        print(f"   ETA (live traffic):    {eta['duration_s']/60:.1f} min")
    else:
        print("   ⚠️  ETA unavailable (may require higher tier)")

    if baseline and eta:
        ratio = eta["duration_s"] / baseline["duration_s"]
        print(f"   Travel Time Ratio:     {ratio:.2f}x")
        if ratio > 1.3:
            print(f"   → SIGNIFICANT congestion detected ({(ratio-1)*100:.0f}% slower than free flow)")
        elif ratio > 1.1:
            print(f"   → Moderate congestion ({(ratio-1)*100:.0f}% slower)")
        else:
            print("   → Low/no congestion currently")
    elif baseline:
        print("   ℹ️  travel_time_ratio = 1.0 (ETA unavailable — fallback default)")

    print(f"\n{'=' * 60}")
    if baseline:
        print("✅ DISTANCE MATRIX API CONFIRMED WORKING — Ready for Stage 2 enrichment")
    else:
        print("❌ DISTANCE MATRIX FAILED — Activate manual fallback")
    print(f"{'=' * 60}")