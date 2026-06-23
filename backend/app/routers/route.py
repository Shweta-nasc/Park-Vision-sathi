"""
Route (Directions) endpoint — road-following patrol routes for "Route now".
============================================================================

The frontend's "Route now" button needs a DRIVABLE path (station → hotspot),
not the crow-flies straight line it drew before. This router serves a drawable
polyline geometry with a strict CACHE-FIRST, OFFLINE-SAFE contract:

  1. Look the route up in the in-memory cache (loaded once from
     ``data/enriched/routes.json`` by the DataStore), keyed by ROUNDED
     from→to coordinates so nearby clicks reuse the same cached path.
  2. On a cache MISS, AND only when a Mappls key is present AND live routing is
     not disabled, call the Mappls **Directions / Route Advanced** API
     SERVER-SIDE (the key never reaches the browser), cache the geometry both
     in memory and on disk, and return it.
  3. On offline / no key / disabled / any failure, return
     ``{"geometry": null, "source": "none"}`` — this endpoint NEVER 500s, so the
     frontend silently falls back to its straight dashed line.

Return shape (stable contract):
    {"geometry": [{"lat": .., "lon": ..}, ...] | null,
     "source": "cache" | "mappls" | "none"}

This is the Directions API (returns a drawable ``geometry``), NOT the Distance
Matrix endpoint used by ml/enrichment/mapmyindia.py (durations only). Verified
endpoint shape:
    GET https://apis.mappls.com/advancedmaps/v1/{KEY}/route_adv/driving/
        {from_lon},{from_lat};{to_lon},{to_lat}?geometries=geojson&overview=full
    -> {"routes": [{"geometry": {"coordinates": [[lng, lat], ...]}}]}
"""

from __future__ import annotations

import json
import logging
import os

import httpx
from fastapi import APIRouter, Query

from backend.app.data_loader import store

logger = logging.getLogger(__name__)

router = APIRouter()

# Mappls Directions / Route Advanced base (key goes in the URL path, server-side).
MAPPLS_ROUTE_BASE = "https://apis.mappls.com/advancedmaps/v1"
# Coordinate rounding for the cache key: 4 dp ≈ 11 m, enough to dedupe repeated
# clicks on the same marker while never confusing distinct hotspots.
CACHE_PRECISION = 4
# Keep the request-time live call short so a slow/blocked network degrades fast
# to the cached/null path instead of hanging the UI.
ROUTE_TIMEOUT_SEC = 8.0


def route_cache_key(from_lat: float, from_lon: float,
                    to_lat: float, to_lon: float,
                    precision: int = CACHE_PRECISION) -> str:
    """Stable cache key from rounded from→to coordinates."""
    return (f"{round(from_lat, precision)},{round(from_lon, precision)}"
            f"->{round(to_lat, precision)},{round(to_lon, precision)}")


def _mappls_token() -> str | None:
    """The server-side Mappls REST key (never exposed to the browser)."""
    return os.getenv("MAPPLS_STATIC_KEY") or None


def routing_enabled() -> bool:
    """Live routing is on only when a key exists AND it is not force-disabled.

    Set ``MAPPLS_ROUTING_DISABLED=1`` to force the offline/cache-only path (e.g.
    for an air-gapped demo) so cache misses return null geometry without ever
    touching the network.
    """
    disabled = (os.getenv("MAPPLS_ROUTING_DISABLED") or "").strip().lower() in (
        "1", "true", "yes", "on")
    return bool(_mappls_token()) and not disabled


def fetch_route_geometry(from_lat: float, from_lon: float,
                         to_lat: float, to_lon: float,
                         token: str,
                         timeout: float = ROUTE_TIMEOUT_SEC) -> list[dict] | None:
    """Call the Mappls Directions API and return ``[{lat,lon}, ...]`` or ``None``.

    Returns ``None`` (never raises) on any HTTP error, timeout, malformed
    response, or empty geometry, so every caller can degrade gracefully.
    Mappls expects ``lng,lat`` order in the path; the returned GeoJSON
    coordinates are ``[lng, lat]`` and are converted back to ``{lat, lon}``.
    """
    coords = f"{from_lon},{from_lat};{to_lon},{to_lat}"
    url = f"{MAPPLS_ROUTE_BASE}/{token}/route_adv/driving/{coords}"
    params = {"geometries": "geojson", "overview": "full"}
    try:
        resp = httpx.get(url, params=params, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("route: Mappls HTTP %s", resp.status_code)
            return None
        data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as e:
        logger.warning("route: Mappls request failed — %s", e)
        return None

    routes = data.get("routes") if isinstance(data, dict) else None
    if not routes:
        return None
    geometry = (routes[0] or {}).get("geometry") or {}
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None

    path: list[dict] = []
    for pt in coordinates:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            lng, lat = pt[0], pt[1]
            try:
                path.append({"lat": float(lat), "lon": float(lng)})
            except (TypeError, ValueError):
                continue
    return path if len(path) >= 2 else None


def _persist_routes() -> None:
    """Best-effort write of the in-memory route cache to disk (never raises)."""
    try:
        path = store.data_dir / "enriched" / "routes.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(store.routes, f, ensure_ascii=False)
    except OSError as e:
        logger.warning("route: could not persist routes cache — %s", e)


@router.get("/route", tags=["Route"])
def get_route(
    from_lat: float = Query(..., ge=-90, le=90),
    from_lon: float = Query(..., ge=-180, le=180),
    to_lat: float = Query(..., ge=-90, le=90),
    to_lon: float = Query(..., ge=-180, le=180),
):
    """Drivable route geometry from origin → destination (cache-first, offline-safe).

    Returns ``{"geometry": [{lat,lon}...] | null, "source": "cache"|"mappls"|"none"}``.
    Never raises a 5xx — a cache miss while offline/keyless returns null geometry
    so the map silently falls back to a straight line.
    """
    store.ensure()
    key = route_cache_key(from_lat, from_lon, to_lat, to_lon)

    cached = store.routes.get(key)
    if isinstance(cached, list) and len(cached) >= 2:
        return {"geometry": cached, "source": "cache"}

    if not routing_enabled():
        return {"geometry": None, "source": "none"}

    token = _mappls_token()
    geometry = fetch_route_geometry(from_lat, from_lon, to_lat, to_lon, token)  # type: ignore[arg-type]
    if not geometry:
        return {"geometry": None, "source": "none"}

    # Cache the freshly fetched geometry (in memory + on disk) so the demo is
    # offline from here on.
    store.routes[key] = geometry
    _persist_routes()
    return {"geometry": geometry, "source": "mappls"}
