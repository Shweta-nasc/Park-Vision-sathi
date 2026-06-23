"""
ParkVision-Saathi — road geometry provider seam (Task 8)
=========================================================

Gives the forecast model a road-size signal, with a single, clearly-bounded seam
for a future non-MapMyIndia gap-filler.

Architecture rule (non-negotiable)
----------------------------------
MapMyIndia is the fixed backbone. :class:`MapMyIndiaRoadGeometry` derives a
road-size *proxy* from the free-flow speed the Task 1 collector measures (faster
free-flow ⇒ more arterial). :class:`OSMRoadGeometry` is the **only** place a
non-MapMyIndia source may ever plug in, and **only** for the genuine gap
MapMyIndia cannot fill — real lane count / road width. It is a documented stub
(``raise NotImplementedError``) and must only be enabled if the coordinator
permits OSM; it supplements, never replaces, a MapMyIndia call.

Road-class proxy from free-flow speed
-------------------------------------
    free_flow_speed_kmph > 40  -> "arterial"
    20 <= free_flow_speed_kmph <= 40 -> "collector"
    free_flow_speed_kmph < 20  -> "local"
    missing / non-finite       -> "unknown"
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

# ─── Road-class thresholds (km/h) ────────────────────────────────────────────

ARTERIAL_MIN_KMPH = 40.0   # strictly above -> arterial
COLLECTOR_MIN_KMPH = 20.0  # [20, 40] -> collector; below 20 -> local

ROAD_CLASSES = ("local", "collector", "arterial", "unknown")
# Ordinal rank used as the numeric forecast feature (unknown -> 0).
ROAD_CLASS_RANK: dict[str, int] = {"unknown": 0, "local": 1, "collector": 2, "arterial": 3}


def classify_road(free_flow_speed_kmph: Optional[float]) -> str:
    """Map a free-flow speed (km/h) to a road-size class (proxy)."""
    if free_flow_speed_kmph is None:
        return "unknown"
    try:
        ffs = float(free_flow_speed_kmph)
    except (TypeError, ValueError):
        return "unknown"
    if not math.isfinite(ffs) or ffs <= 0:
        return "unknown"
    if ffs > ARTERIAL_MIN_KMPH:
        return "arterial"
    if ffs >= COLLECTOR_MIN_KMPH:
        return "collector"
    return "local"


def road_size_proxy(free_flow_speed_kmph: Optional[float]) -> int:
    """Numeric road-size proxy (the forecast feature): 0=unknown..3=arterial."""
    return ROAD_CLASS_RANK[classify_road(free_flow_speed_kmph)]


# ─── Provider contract ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoadGeometry:
    """Road geometry for one location. ``lane_count``/``road_width_m`` are the gap
    only a real lane/width source (OSM) can fill; the MapMyIndia provider leaves
    them ``None`` and supplies only the speed-derived class proxy."""

    road_class: str                       # local | collector | arterial | unknown
    free_flow_speed_kmph: Optional[float]
    road_size_proxy: int                  # 0..3 (ROAD_CLASS_RANK)
    lane_count: Optional[int] = None      # OSM-only gap (None from MapMyIndia)
    road_width_m: Optional[float] = None  # OSM-only gap (None from MapMyIndia)
    source: str = ""


class RoadGeometryProvider(ABC):
    """Abstract road-geometry provider."""

    @abstractmethod
    def geometry_for(
        self,
        *,
        lat: float,
        lon: float,
        free_flow_speed_kmph: Optional[float] = None,
    ) -> RoadGeometry:
        """Return :class:`RoadGeometry` for the given location."""
        raise NotImplementedError


class MapMyIndiaRoadGeometry(RoadGeometryProvider):
    """Default provider: road-size proxy from the MapMyIndia free-flow speed.

    This is the backbone implementation. It derives ``road_class`` /
    ``road_size_proxy`` from the collector's measured free-flow speed and leaves
    ``lane_count`` / ``road_width_m`` as ``None`` (the genuine gap).
    """

    def geometry_for(
        self,
        *,
        lat: float,
        lon: float,
        free_flow_speed_kmph: Optional[float] = None,
    ) -> RoadGeometry:
        road_class = classify_road(free_flow_speed_kmph)
        return RoadGeometry(
            road_class=road_class,
            free_flow_speed_kmph=(float(free_flow_speed_kmph)
                                  if isinstance(free_flow_speed_kmph, (int, float))
                                  and not isinstance(free_flow_speed_kmph, bool) else None),
            road_size_proxy=ROAD_CLASS_RANK[road_class],
            source="mapmyindia_free_flow_speed",
        )


class OSMRoadGeometry(RoadGeometryProvider):
    """STUB — the ONLY non-MapMyIndia seam, and ONLY for real lane count / width.

    This is a documented future gap-filler. It must remain unimplemented unless the
    coordinator explicitly permits OSM, and even then it may supply ONLY lane
    count / road width (the genuine gap MapMyIndia cannot fill) — it supplements,
    never replaces, the MapMyIndia free-flow-speed class proxy. The exact
    signature matches :class:`RoadGeometryProvider` so it can be dropped in later.
    """

    def geometry_for(
        self,
        *,
        lat: float,
        lon: float,
        free_flow_speed_kmph: Optional[float] = None,
    ) -> RoadGeometry:
        raise NotImplementedError(
            "OSMRoadGeometry is a documented future seam for real lane count / road "
            "width only, and is not enabled. Use MapMyIndiaRoadGeometry. Enabling OSM "
            "requires coordinator approval and must supplement (not replace) MapMyIndia."
        )
