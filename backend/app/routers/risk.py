"""
Risk & Hotspot endpoints — served from the in-memory DataStore (real H3 zones).

`risk_score` carries the Congestion Impact Score; the frontend adapter maps it
to `congestion_impact`. No database.
"""

from fastapi import APIRouter, Query
from backend.app.data_loader import store

router = APIRouter()


@router.get("/hotspots")
def get_hotspots(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
    min_members: int = Query(default=0, description="Minimum violation count"),
    limit: int = Query(default=15, ge=1, le=100),
):
    """Top hotspot zones ranked by congestion impact."""
    zones = [z for z in store.top_zones(100) if z["violation_count"] >= min_members]
    return zones[:limit]


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
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
):
    """Full detail for a single zone.

    For a REAL CIS zone (one of the 2,527 H3 zones in the canonical artifact) this
    returns the per-zone Congestion Impact breakdown — the ``CongestionBreakdown``
    contract — including ``calibrated_impact`` (a number for the ~10 agent-
    calibrated zones, ``null`` otherwise). Falls back to the legacy in-memory zone
    shape (game-theory fields, real Mappls) for the mock hotspot zones the
    frontend already consumes, so existing behaviour is preserved.
    """
    breakdown = store.congestion_breakdown(zone_id, time_bucket or "all_day")
    if breakdown is not None:
        return breakdown

    # Legacy mock-hotspot zones (not in the CIS artifact): keep the prior shape.
    z = store.zone(zone_id)
    if z:
        return z
    return {"error": f"No data for zone {zone_id}"}
