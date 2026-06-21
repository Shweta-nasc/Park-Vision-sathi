"""
ParkVision-Saathi — In-Memory DataStore
========================================

Planner-mandated data layer: pre-computed JSON files loaded once into memory.
NO database (EXECUTION_PLANNER L233 "JSON files + in-memory pandas. Period.";
MASTER_PLAN L629 "Skip PostgreSQL entirely. Use pre-computed JSON files +
in-memory Python dicts.").

This module loads the project's REAL artifacts and assembles a single canonical
list of zones keyed by H3 id — the one source of truth shared by the map, the
zone detail panel, the LLM explanations, the game-theory simulation, and the
self-validating agent:

  data/mock/hotspots.json            → ranked zones (legacy score, station, …)
  data/enriched/traffic_context.json → REAL MapMyIndia travel-time + road + POIs
  data/processed/calibrated_scores.json → self-validating agent's calibrated scores
  data/processed/agent_log.json      → agent run summary + reasoning log
  data/processed/explanations_cache.json → cached Gemini zone explanations
  data/processed/zone_congestion_impact.json → canonical Congestion Impact Score
                                       (CIS) artifact, {h3_id: {time_bucket: …}}

The frontend speaks `grid_cell_id` / `risk_score` and adapts those to
`h3_id` / `congestion_impact` client-side (see frontend/src/api/adapters.ts).

`congestion_impact` (the QUANTIFY pillar's CIS) is served from the CIS artifact
and is a value DISTINCT from the legacy enforcement `risk_score` — the two are no
longer aliased (Decision 2; Requirements 10.1, 10.3). When the artifact is absent
the congestion universe loads empty (and a warning is logged) rather than
crashing, so the demo stays offline-safe and database-free (Requirements 11.3,
14.3). Loading reads JSON only; nothing here touches a database or the network.

Risk-component fields (density, road_importance, …) and game-theory fields
(patrol_probability, violator_risk_score, …) are DERIVED here with transparent,
documented formulas — there is no hidden model and nothing random.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA = PROJECT_ROOT / "data"

# Stackelberg emphasis exponent (docs/README: patrol_prob ∝ score^α, α=1.5).
PATROL_ALPHA = 1.5
# Violator expected-utility knobs (illustrative units, documented in MODEL).
VIOLATOR_TIME_SAVED = 100.0   # value of time saved by parking illegally
VIOLATOR_FINE = 500.0         # fine if caught


def _display_path(path: Path) -> Path | str:
    """Best-effort project-relative path for logging; absolute if outside the root.

    ``Path.relative_to`` raises when ``path`` is not under ``PROJECT_ROOT`` (e.g.
    a test fixture in a temp dir), so this guards it: the missing-artifact warning
    must never itself raise (Requirement 14.3).
    """
    try:
        return path.relative_to(PROJECT_ROOT)
    except ValueError:
        return path


def _load(path: Path, default):
    """Load a JSON file, returning `default` if it is missing or invalid."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("DataStore: %s not found — using fallback.", _display_path(path))
        return default
    except (json.JSONDecodeError, OSError) as e:
        logger.error("DataStore: failed to read %s (%s).", path, e)
        return default


def _band(score: float) -> str:
    """Congestion impact band (matches ml/congestion impact_band thresholds)."""
    if score <= 25:
        return "MINIMAL"
    if score <= 50:
        return "MODERATE"
    if score <= 75:
        return "SEVERE"
    return "CRITICAL"


def _risk_label(score: float) -> str:
    """LOW/MEDIUM/HIGH/CRITICAL label (matches frontend normalizeRiskLabel)."""
    if score >= 80:
        return "CRITICAL"
    if score >= 67:
        return "HIGH"
    if score >= 34:
        return "MEDIUM"
    return "LOW"


def _road_importance(road_name: str, ratio: Optional[float]) -> float:
    """Proxy 0-1 for how arterial a road is.

    Signals: a named main road / flyover / arterial is structurally important;
    a higher real travel-time ratio also implies a more load-bearing corridor.
    """
    name = (road_name or "").lower()
    base = 0.5
    for kw, w in (("flyover", 0.95), ("main road", 0.9), ("circle", 0.85),
                  ("road", 0.75), ("cross", 0.6)):
        if kw in name:
            base = max(base, w)
            break
    if ratio:
        base = max(base, min(1.0, 0.5 + (ratio - 1.0)))
    return round(base, 3)


def _heavy_vehicle_ratio(top_violation: str) -> float:
    """Proxy 0-1 for heavy-vehicle obstruction, inferred from the top violation."""
    v = (top_violation or "").upper()
    if "MAIN ROAD" in v or "DOUBLE" in v:
        return 0.22
    if "BUSTOP" in v or "BUS" in v:
        return 0.18
    if "ROAD CROSSING" in v or "TRAFFIC LIGHT" in v:
        return 0.12
    return 0.08


class DataStore:
    """Loads all JSON once and serves the API a single canonical zone universe."""

    def __init__(self, data_dir: Path = DATA) -> None:
        # Root of the pre-computed JSON artifacts. Defaults to the repo's `data/`
        # dir; overridable (e.g. a test fixture dir) so the loader can be pointed
        # at an alternate artifact set without touching the committed files.
        self.data_dir = Path(data_dir)
        self.loaded = False
        self.zones: list[dict] = []
        self.zones_by_id: dict[str, dict] = {}
        # Canonical Congestion Impact Score (CIS) artifact, loaded once at startup
        # and keyed {h3_id: {time_bucket: breakdown}}. Empty when the artifact is
        # absent (graceful empty zone universe — Requirement 14.3). The rich
        # serving accessors over this structure are added in task 6.2.
        self.congestion: dict[str, dict[str, dict]] = {}
        self.traffic_raw: dict = {}
        self.explanations: dict = {}
        self.calibrated: dict = {}
        self.agent_summary: dict = {}
        self.sources: dict = {}

    # ── load ────────────────────────────────────────────────────────────
    def load(self) -> "DataStore":
        hotspots = _load(self.data_dir / "mock" / "hotspots.json", [])
        traffic = _load(self.data_dir / "enriched" / "traffic_context.json", {})
        calibrated = _load(self.data_dir / "processed" / "calibrated_scores.json", {})
        agent_log = _load(self.data_dir / "processed" / "agent_log.json", {})
        explanations = _load(self.data_dir / "processed" / "explanations_cache.json", {})

        # Canonical CIS artifact (the QUANTIFY pillar's single source of truth),
        # read as JSON only — no database, no network (Requirements 7.3, 7.4, 11.3).
        # A missing file is non-fatal: `_load` logs a warning and returns {}, so the
        # backend starts with an empty congestion universe rather than crashing
        # (Requirement 14.3). The artifact is keyed {h3_id: {time_bucket: breakdown}}.
        congestion = _load(self.data_dir / "processed" / "zone_congestion_impact.json", {})
        self.congestion = congestion if isinstance(congestion, dict) else {}

        self.traffic_raw = traffic
        self.calibrated = calibrated
        self.agent_summary = {k: v for k, v in agent_log.items() if k != "log"}
        self.explanations = explanations
        self.sources = {
            "hotspots": len(hotspots),
            "traffic_context_enriched": len(traffic),
            "calibrated_scores": len(calibrated),
            "explanations_cache": len(explanations),
            "congestion_artifact_zones": len(self.congestion),
        }

        max_viol = max((h.get("violation_count", 0) for h in hotspots), default=1) or 1
        zones: list[dict] = []
        for h in hotspots:
            zid = h["zone_id"]
            tc = traffic.get(zid, {})
            cal = calibrated.get(zid, {})
            score = float(h.get("congestion_impact", 0.0))
            # Congestion Impact Score served from the canonical artifact (NOT
            # aliased to risk_score). `all_day` is the zone's default rollup; None
            # when the artifact has no entry for this zone — e.g. the artifact is
            # absent at startup, giving an empty congestion universe (Req 14.3).
            cis = self.congestion.get(zid, {}).get("all_day")
            congestion_impact = cis.get("congestion_impact") if isinstance(cis, dict) else None
            ratio = tc.get("travel_time_ratio")
            road = tc.get("road_name") or tc.get("street") or h.get("station", zid)
            viol = int(h.get("violation_count", 0))

            zones.append({
                # identity / map
                "grid_cell_id": zid,
                "h3_id": zid,
                "grid_lat": h.get("lat"),
                "grid_lon": h.get("lon"),
                "hour": 9,
                # `risk_score` keeps its legacy enforcement-priority role — it
                # drives game-theory patrol allocation, simulation, and forecasts.
                # It is NO LONGER aliased to the congestion impact (Decision 2;
                # Requirements 10.1, 10.3).
                "risk_score": round(score, 1),
                # Congestion Impact Score (the QUANTIFY pillar) served straight from
                # the canonical CIS artifact — a distinct value and source from
                # `risk_score`; None when the artifact is absent (empty universe).
                "congestion_impact": congestion_impact,
                "calibrated_score": cal.get("calibrated_score", round(score, 1)),
                "risk_label": _risk_label(score),
                "impact_band": h.get("impact_band", _band(score)),
                # volume / derived risk components (documented proxies)
                "violation_count": viol,
                "density": round(viol / max_viol, 3),
                "road_importance": _road_importance(road, ratio),
                "peak_weight": 1.0,
                "repeat_offender": round(0.30 + 0.50 * (viol / max_viol), 3),
                "validation_trust": 0.70,
                "heavy_vehicle_ratio": _heavy_vehicle_ratio(h.get("top_violation", "")),
                # real MapMyIndia validation
                "travel_time_ratio": ratio,
                "mappls_ratio": ratio,
                "road_name": road,
                "road_type": tc.get("road_type") or ("primary" if _road_importance(road, ratio) > 0.8 else "secondary"),
                "nearby_pois": tc.get("nearby_pois", []),
                # context
                "police_station": h.get("station"),
                "station": h.get("station"),
                "top_junction": tc.get("locality"),
                "top_violation": h.get("top_violation"),
                "estimated_lane_hours_blocked": h.get("estimated_lane_hours_blocked"),
                # agent
                "agent_status": cal.get("status"),
                "agent_reasoning": cal.get("reasoning"),
            })

        # Game theory: Stackelberg patrol probability ∝ score^alpha (normalised).
        weights = [max(z["risk_score"], 0.0) ** PATROL_ALPHA for z in zones]
        wsum = sum(weights) or 1.0
        for z, w in zip(zones, weights):
            p = w / wsum
            z["patrol_probability"] = round(p, 6)
            z["baseline_weight"] = round(z["risk_score"] / max(sum(zz["risk_score"] for zz in zones), 1), 6)
            z["adjusted_weight"] = round(p, 6)
            # Violator expected utility: benefit if NOT caught, minus expected fine.
            benefit = (z["risk_score"] / 100.0) * VIOLATOR_TIME_SAVED
            expected_cost = p * VIOLATOR_FINE
            net_benefit = (1 - p) * benefit - expected_cost
            z["expected_cost"] = round(expected_cost, 2)
            z["net_benefit"] = round(net_benefit, 2)
            # Violator risk = where rational violators still profit most (0-100).
            z["violator_risk_score"] = round(max(0.0, min(100.0, net_benefit)), 2)

        zones.sort(key=lambda z: z["risk_score"], reverse=True)
        self.zones = zones
        self.zones_by_id = {z["grid_cell_id"]: z for z in zones}
        self.loaded = True
        logger.info("DataStore loaded: %d zones from real H3 data.", len(zones))
        return self

    # ── accessors ───────────────────────────────────────────────────────
    def ensure(self) -> "DataStore":
        if not self.loaded:
            self.load()
        return self

    def top_zones(self, n: int = 15) -> list[dict]:
        return self.ensure().zones[:n]

    def zone(self, zone_id: str) -> Optional[dict]:
        return self.ensure().zones_by_id.get(zone_id)

    def congestion_breakdown(
        self, zone_id: str, time_bucket: str = "all_day"
    ) -> Optional[dict]:
        """Return the REAL CIS breakdown for an H3 zone, with calibrated_impact.

        Resolves any of the 2,527 real H3 zones from the canonical CIS artifact
        (``self.congestion``, keyed ``{h3_id: {time_bucket: breakdown}}``) and
        returns that zone's breakdown for ``time_bucket`` (default ``all_day``).

        The returned dict conforms to ``backend.app.models.CongestionBreakdown``.
        Its ``calibrated_impact`` is attached additively from the self-validating
        agent's output (``self.calibrated[zone_id].calibrated_score``) when an
        entry exists for this zone; otherwise it is left as ``None`` (NOT 0.0, and
        NOT the raw CIS) so consumers can tell "agent-calibrated" from "no agent
        data". Only ~10 of the 2,527 zones carry a calibration entry.

        Returns ``None`` when the zone (or the requested bucket) is absent from the
        artifact, so the caller can fall back to its legacy behaviour.
        """
        self.ensure()
        buckets = self.congestion.get(zone_id)
        if not isinstance(buckets, dict):
            return None
        breakdown = buckets.get(time_bucket)
        if not isinstance(breakdown, dict):
            return None

        # Shallow copy so the in-memory artifact is never mutated by serving.
        result = dict(breakdown)
        cal = self.calibrated.get(zone_id)
        calibrated_score = cal.get("calibrated_score") if isinstance(cal, dict) else None
        result["calibrated_impact"] = (
            float(calibrated_score) if isinstance(calibrated_score, (int, float)) else None
        )
        return result

    def heatmap_points(self, layer: str) -> list[dict]:
        """Points for the map. layer: raw (violation density) | risk (congestion
        impact) | spillover (agent-calibrated)."""
        self.ensure()
        pts = []
        for z in self.zones:
            if layer == "raw":
                intensity = z["violation_count"]
            elif layer == "spillover":
                intensity = z["calibrated_score"]
            else:  # risk / congestion
                intensity = z["risk_score"]
            pts.append({"lat": z["grid_lat"], "lon": z["grid_lon"],
                        "h3_id": z["grid_cell_id"], "intensity": round(float(intensity), 3)})
        pts.sort(key=lambda p: p["intensity"], reverse=True)
        return pts

    def stations(self) -> list[dict]:
        """Aggregate zones by police station."""
        self.ensure()
        agg: dict[str, dict] = {}
        for z in self.zones:
            s = z["station"] or "Unknown"
            a = agg.setdefault(s, {"name": s, "zone_count": 0, "total_violations": 0,
                                   "_lat": 0.0, "_lon": 0.0})
            a["zone_count"] += 1
            a["total_violations"] += z["violation_count"]
            a["_lat"] += z["grid_lat"] or 0.0
            a["_lon"] += z["grid_lon"] or 0.0
        out = []
        for a in agg.values():
            n = a["zone_count"] or 1
            out.append({"name": a["name"], "zone_count": a["zone_count"],
                        "total_violations": a["total_violations"],
                        "lat": round(a["_lat"] / n, 6), "lon": round(a["_lon"] / n, 6)})
        out.sort(key=lambda x: x["total_violations"], reverse=True)
        return out

    def station_zones(self, station: str) -> list[dict]:
        self.ensure()
        return [z for z in self.zones if (z["station"] or "").lower() == station.lower()]

    # ── game theory ─────────────────────────────────────────────────────
    def stackelberg(self, limit: int = 100) -> list[dict]:
        """Zones ranked by Stackelberg patrol probability."""
        self.ensure()
        return sorted(self.zones, key=lambda z: z["patrol_probability"], reverse=True)[:limit]

    def violators(self, limit: int = 100) -> list[dict]:
        """Zones ranked by violator net-benefit (where rational violators profit)."""
        self.ensure()
        return sorted(self.zones, key=lambda z: z["violator_risk_score"], reverse=True)[:limit]

    @staticmethod
    def _dist2(a: dict, b: dict) -> float:
        return (a["grid_lat"] - b["grid_lat"]) ** 2 + (a["grid_lon"] - b["grid_lon"]) ** 2

    def simulate(self, num_teams: int, hour: int = 9, strategy: str = "stackelberg") -> dict:
        """Allocate teams to the highest-impact zones; compute coverage + waterbed spillover."""
        self.ensure()
        zones = self.zones
        total_risk = sum(z["risk_score"] for z in zones) or 1.0
        num_teams = max(0, min(num_teams, len(zones)))
        covered, uncovered = zones[:num_teams], zones[num_teams:]

        assignments = [{
            "team_id": i + 1, "grid_cell_id": z["grid_cell_id"],
            "grid_lat": z["grid_lat"], "grid_lon": z["grid_lon"],
            "risk_score": z["risk_score"], "patrol_probability": z["patrol_probability"],
            "priority_rank": i + 1,
        } for i, z in enumerate(covered)]

        covered_risk = sum(z["risk_score"] for z in covered)
        uncovered_high = [{
            "grid_cell_id": z["grid_cell_id"], "grid_lat": z["grid_lat"],
            "grid_lon": z["grid_lon"], "risk_score": z["risk_score"],
        } for z in uncovered if z["risk_score"] >= 67]

        # Waterbed effect: each enforced zone displaces part of its violator
        # pressure to the nearest UNcovered zone (violations are conserved).
        bumps: dict[str, dict] = {}
        for cz in covered:
            if not uncovered:
                break
            nearest = min(uncovered, key=lambda u: self._dist2(cz, u))
            e = bumps.setdefault(nearest["grid_cell_id"], {**nearest, "_bump": 0.0})
            e["_bump"] += 0.12 * cz["patrol_probability"]
        spillover_zones = []
        for e in bumps.values():
            bump = min(e["_bump"], 0.25)
            spillover_zones.append({
                "grid_cell_id": e["grid_cell_id"], "grid_lat": e["grid_lat"],
                "grid_lon": e["grid_lon"], "original_risk": round(e["risk_score"], 1),
                "adjusted_risk": round(e["risk_score"] * (1 + bump), 1),
                "risk_change_pct": round(bump * 100, 1), "spillover_type": "neighbor_1",
            })
        spillover_zones.sort(key=lambda s: s["risk_change_pct"], reverse=True)

        return {
            "num_teams": num_teams, "hour": hour, "strategy": strategy,
            "assignments": assignments, "uncovered_high_risk": uncovered_high[:20],
            "coverage_pct": round(covered_risk / total_risk * 100, 2),
            "total_risk_covered": round(covered_risk, 2),
            "spillover_zones": spillover_zones,
        }

    def spillover_arrows(self, top: int = 5) -> dict:
        """Displacement arrows from each top patrolled zone to its nearest neighbour."""
        self.ensure()
        arrows = []
        for cz in self.zones[:top]:
            pool = [z for z in self.zones if z["grid_cell_id"] != cz["grid_cell_id"]]
            if not pool:
                continue
            nearest = min(pool, key=lambda u: self._dist2(cz, u))
            arrows.append({
                "from_zone": cz["grid_cell_id"], "to_zone": nearest["grid_cell_id"],
                "from_lat": cz["grid_lat"], "from_lon": cz["grid_lon"],
                "to_lat": nearest["grid_lat"], "to_lon": nearest["grid_lon"],
                "weight": round(cz["patrol_probability"], 4),
            })
        return {"arrows": arrows}

    def spillover_forecast(self, limit: int = 200) -> list[dict]:
        """Spillover relative to a default 5-team enforcement."""
        return self.simulate(5)["spillover_zones"][:limit]

    def whatif_coverage(self, max_teams: int = 10) -> dict:
        """Coverage % and uncovered-high count across team counts (for the slider)."""
        self.ensure()
        out = {}
        for n in range(1, min(max_teams, len(self.zones)) + 1):
            sim = self.simulate(n)
            out[str(n)] = {"num_teams": n, "coverage_pct": sim["coverage_pct"],
                           "uncovered_high_risk": len(sim["uncovered_high_risk"])}
        return out

    def agent_report(self) -> dict:
        """Self-validating agent: summary + per-zone calibration log."""
        self.ensure()
        return {"summary": self.agent_summary,
                "zones": list(self.calibrated.values())}


# Module-level singleton (loaded at app startup in main.py).
store = DataStore()
