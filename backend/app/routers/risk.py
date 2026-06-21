"""
Risk & Hotspot endpoints — served from the in-memory DataStore (real H3 zones).

The two canonical Congestion Impact Score (CIS) endpoints are served straight
from the CIS artifact via the DataStore accessors (NOT the legacy enforcement
`risk_score`), returning the typed contract from `backend.app.models`:

  GET /hotspots        -> list[HotspotItem]    (zones ranked by descending CIS)
  GET /risk/{zone_id}  -> CongestionBreakdown  (full per-zone, per-bucket breakdown)

Both accept a `time_bucket` query param (default `all_day`); an unknown bucket
falls back to the zone's `all_day` rollup (handled in the DataStore), and an
unknown `zone_id` yields a structured HTTP 404. Because the canonical CIS
artifact is materialized offline, `/risk/{zone_id}` returns 404 and `/hotspots`
returns `[]` until that artifact exists — the designed graceful, offline-safe
behavior (no fabricated data). No database.

The remaining legacy list/summary/overview endpoints below still serve the
enforcement-priority `risk_score` from the hotspot-derived zone universe and are
unchanged — a separate concern from CIS (Decision 2).
"""

from fastapi import APIRouter, HTTPException, Query
from backend.app.data_loader import store
from backend.app.models import CongestionBreakdown, HotspotItem

router = APIRouter()


@router.get("/hotspots", response_model=list[HotspotItem])
def get_hotspots(
    time_bucket: str = Query(
        default="all_day",
        description="all_day | night | morning_peak | midday | afternoon",
    ),
    limit: int = Query(default=15, ge=1, le=100),
    hour: int = Query(default=None, ge=0, le=23, description="Hour of day (informational)"),
):
    """Top congestion hotspots ranked by descending CIS, from the CIS artifact.

    Served via `store.congestion_hotspots` (the canonical CIS artifact), NOT the
    legacy enforcement `risk_score`. An unknown `time_bucket` falls back to each
    zone's `all_day` rollup; `limit` truncates the ranked list. With no
    materialized artifact this returns `[]` (designed graceful behavior).
    """
    items = store.congestion_hotspots(time_bucket, limit)
    return [HotspotItem.model_validate(item) for item in items]


@router.get("/risk")
def get_risk_scores(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    zone_id: str = Query(default=None),
    risk_label: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Congestion-impact scores per zone, optionally filtered."""
    zones = store.top_zones(1000)
    if zone_id:
        zones = [z for z in zones if z["grid_cell_id"] == zone_id]
    if risk_label:
        zones = [z for z in zones if z["risk_label"] == risk_label.upper()]
    return zones[:limit]


@router.get("/risk/summary")
def get_risk_summary(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    type: str = Query(default="risk"),
):
    """Distribution of zones by impact label."""
    buckets: dict[str, dict] = {}
    for z in store.top_zones(1000):
        b = buckets.setdefault(z["risk_label"], {"risk_label": z["risk_label"], "zone_count": 0,
                                                 "scores": [], "total_violations": 0})
        b["zone_count"] += 1
        b["scores"].append(z["risk_score"])
        b["total_violations"] += z["violation_count"]
    out = []
    for b in buckets.values():
        s = b.pop("scores")
        b["avg_score"] = round(sum(s) / len(s), 2) if s else 0
        b["min_score"] = round(min(s), 2) if s else 0
        b["max_score"] = round(max(s), 2) if s else 0
        out.append(b)
    out.sort(key=lambda x: x["avg_score"], reverse=True)
    return out


@router.get("/risk/top_zones")
def get_top_risk_zones(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    n: int = Query(default=10, ge=1, le=50),
):
    """Top N highest congestion-impact zones."""
    return store.top_zones(n)


@router.get("/risk/overview")
def get_overview(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
):
    """Dashboard overview stats."""
    zones = store.top_zones(1000)
    dist: dict[str, dict] = {}
    for z in zones:
        d = dist.setdefault(z["risk_label"], {"risk_label": z["risk_label"], "count": 0,
                                              "scores": [], "total_violations": 0})
        d["count"] += 1
        d["scores"].append(z["risk_score"])
        d["total_violations"] += z["violation_count"]
    for d in dist.values():
        s = d.pop("scores")
        d["avg_score"] = round(sum(s) / len(s), 1) if s else 0
    return {
        "hour": hour,
        "time_bucket": time_bucket,
        "risk_distribution": list(dist.values()),
        "top_zone": zones[0] if zones else None,
        "total_zones": len(zones),
    }


@router.get("/risk/{zone_id}")
def get_zone_risk_detail(
    zone_id: str,
    time_bucket: str = Query(
        default="all_day",
        description="all_day | night | morning_peak | midday | afternoon",
    ),
    hour: int = Query(default=None, ge=0, le=23, description="Hour of day (informational)"),
):
    """Full detail for a single zone.

    For a REAL CIS zone (one of the 2,527 H3 zones in the canonical artifact) this
    returns the per-zone Congestion Impact breakdown — the ``CongestionBreakdown``
    contract — including ``calibrated_impact`` (a number for the ~10 agent-
    calibrated zones, ``null`` otherwise). Falls back to the legacy in-memory zone
    shape (game-theory fields, real Mappls) for the mock hotspot zones the
    frontend already consumes, so existing behaviour is preserved.

    Note: no strict ``response_model`` is declared on purpose — the legacy fallback
    returns the in-memory zone shape (and a structured error dict for unknown
    zones), which would not validate against ``CongestionBreakdown``.
    """
    breakdown = store.congestion_breakdown(zone_id, time_bucket or "all_day")
    if breakdown is not None:
        return breakdown

    # Legacy mock-hotspot zones (not in the CIS artifact): keep the prior shape.
    z = store.zone(zone_id)
    if z:
        return z
    return {"error": f"No data for zone {zone_id}"}