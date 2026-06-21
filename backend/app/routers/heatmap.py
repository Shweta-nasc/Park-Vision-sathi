"""
Heatmap endpoint — typed point layers for the two-layer map toggle.

Layers (frontend maps these to the `type` param):
  risk      → congestion impact   (where violations choke traffic) — intensity = CIS
  raw       → violation density   (where violations happen)        — intensity = count
  spillover → agent-calibrated impact

The `risk` and `raw` layers are served straight from the canonical CIS artifact
via the DataStore accessors (`congestion_points` / `violation_density_points`),
so the toggle is backed by genuinely different values — CIS vs raw count — the
"density != impact" thesis (Req 8.3, 8.4, 10.2). Because that artifact is
materialized offline, both layers return empty points (min/max 0.0) until it
exists — designed graceful, offline-safe behavior (no fabricated data).

The `spillover` layer is preserved as-is: it is the agent-calibrated layer drawn
from the legacy hotspot-derived zone universe (`heatmap_points("spillover")`,
intensity = `calibrated_score`), which is NOT keyed to the CIS artifact — so it
keeps its current source and is merely adapted into the response shape.

All layers return a typed `CongestionHeatmapResponse`. Served from the in-memory
DataStore (real H3 zones). No database.
"""

from fastapi import APIRouter, Query
from backend.app.data_loader import store
from backend.app.models import CongestionHeatmapPoint, CongestionHeatmapResponse

router = APIRouter()


def _aggregate_resolution(points: list[dict], resolution: int) -> list[dict]:
    """Aggregate fine-grained heatmap points into coarser spatial bins (zoom-adaptive).

    `resolution` is the number of lat/lon decimal places to snap to: higher = finer
    detail (4 ≈ ~11 m, 3 ≈ ~110 m, 2 ≈ ~1.1 km). Member coordinates and intensities
    are averaged; each bin keeps the ``h3_id`` (and ``impact_band``) of its
    highest-intensity member as a representative, so an aggregated point still
    satisfies the typed ``CongestionHeatmapPoint`` contract. Used to serve coarse
    blobs when zoomed out and fine spots when zoomed in.
    """
    bins: dict[tuple, dict] = {}
    for p in points:
        key = (round(p["lat"], resolution), round(p["lon"], resolution))
        b = bins.get(key)
        if b is None:
            b = {
                "lat_sum": 0.0, "lon_sum": 0.0, "int_sum": 0.0, "n": 0,
                "rep_h3": p.get("h3_id"), "rep_band": p.get("impact_band"),
                "rep_int": p["intensity"],
            }
            bins[key] = b
        b["lat_sum"] += p["lat"]
        b["lon_sum"] += p["lon"]
        b["int_sum"] += p["intensity"]
        b["n"] += 1
        # Representative metadata = the bin's highest-intensity member.
        if p["intensity"] >= b["rep_int"]:
            b["rep_int"] = p["intensity"]
            b["rep_h3"] = p.get("h3_id")
            b["rep_band"] = p.get("impact_band")
    out = [
        {
            "lat": b["lat_sum"] / b["n"],
            "lon": b["lon_sum"] / b["n"],
            "intensity": b["int_sum"] / b["n"],
            "h3_id": b["rep_h3"],
            "impact_band": b["rep_band"],
        }
        for b in bins.values()
    ]
    out.sort(key=lambda d: d["intensity"], reverse=True)
    return out


@router.get("/heatmap", response_model=CongestionHeatmapResponse)
def get_heatmap(
    type: str = Query(default="risk", description="risk | raw | spillover"),
    time_bucket: str = Query(
        default="all_day",
        description="all_day | night | morning_peak | midday | afternoon",
    ),
    hour: int = Query(default=None, ge=0, le=23, description="Hour of day (informational)"),
    resolution: int = Query(
        default=None, ge=2, le=5,
        description="Optional spatial aggregation: lat/lon decimal places to snap to "
                    "(2≈~1km blobs, 5≈full detail). Omit for full resolution.",
    ),
):
    """Heatmap layer for the two-layer (Congestion Risk vs Violation Density) toggle.

    `type=risk` serves CIS intensities, `type=raw` serves violation-count
    intensities (both from the CIS artifact, with an `all_day` fallback for an
    unknown `time_bucket`), and `type=spillover` serves the agent-calibrated layer
    from its existing source. An unknown `type` falls back to `risk`. `min_intensity`
    / `max_intensity` are computed from the returned points and are 0.0 when empty.
    """
    layer = type if type in {"risk", "raw", "spillover"} else "risk"
    if layer == "raw":
        raw_points = store.violation_density_points(time_bucket)
    elif layer == "spillover":
        # Preserved legacy source: agent-calibrated layer from the hotspot-derived
        # zone universe (NOT the CIS artifact); adapted into the typed shape.
        raw_points = store.heatmap_points("spillover")
    else:  # risk → Congestion Impact Score
        raw_points = store.congestion_points(time_bucket)

    if isinstance(resolution, int):
        raw_points = _aggregate_resolution(raw_points, resolution)

    points = [CongestionHeatmapPoint.model_validate(p) for p in raw_points]
    intensities = [p.intensity for p in points]
    return CongestionHeatmapResponse(
        layer=layer,
        time_bucket=time_bucket,
        points=points,
        min_intensity=min(intensities) if intensities else 0.0,
        max_intensity=max(intensities) if intensities else 0.0,
    )


@router.get("/heatmap/patrol_overlay")
def get_patrol_overlay(
    hour: int = Query(default=None, ge=0, le=23),
    time_bucket: str = Query(default=None),
):
    """Patrol-probability overlay for map markers (circle sizing)."""
    zones = store.top_zones(50)
    patrols = [
        {"lat": z["grid_lat"], "lon": z["grid_lon"],
         "probability": z["patrol_probability"], "risk_score": z["risk_score"]}
        for z in zones if z["patrol_probability"] > 0.001
    ]
    return {"hour": hour, "time_bucket": time_bucket, "patrols": patrols}
