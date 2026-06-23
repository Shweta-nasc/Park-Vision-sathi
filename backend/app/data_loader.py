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
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA = PROJECT_ROOT / "data"

# ── Calibrated CIS artifact resolution (additive-shadow, Task 5) ─────────────
# The backend serves the v2 (calibrated) artifact by default but FALLS BACK to v1
# when v2 is absent, so the working demo never breaks and v1 stays one
# rename/removal away. An explicit CIS_ARTIFACT_PATH env var overrides both.
CIS_V1_FILENAME = "zone_congestion_impact.json"
CIS_V2_FILENAME = "zone_congestion_impact_v2.json"
# Calibration metadata sidecar (Option A): metadata is NEVER embedded in the
# artifact, so no consumer can miscount a phantom metadata "zone".
CIS_CALIBRATION_META_FILENAME = "cis_calibration_meta.json"
# CIS validation report (Task 2/10): the density≠impact proof artifact — the
# non-circular trust metric + per-zone scatter points served at /validation/proof.
CIS_VALIDATION_REPORT_FILENAME = "cis_validation_report.json"
# Defensive only: a key that could never be a real H3 id. The v2 artifact is pure
# (metadata lives in the sidecar), so this filter is a no-op safety net.
CALIBRATION_META_KEY = "_calibration"


def _resolve_cis_artifact_path(data_dir: Path) -> Path:
    """Return the CIS artifact path: env override, else v2, else v1 fallback."""
    env = os.getenv("CIS_ARTIFACT_PATH")
    if env:
        return Path(env)
    v2 = data_dir / "processed" / CIS_V2_FILENAME
    if v2.exists():
        return v2
    return data_dir / "processed" / CIS_V1_FILENAME

# Stackelberg emphasis exponent (docs/README: patrol_prob ∝ score^α, α=1.5).
PATROL_ALPHA = 1.5
# Size of the served hotspot / OPTIMIZE zone universe — the top-N real CIS zones
# (ranked by violation volume) that drive markers, game theory, simulation, and
# the station views. Kept modest so the simulation's risk-weighted coverage % is
# meaningful (covering a few teams over the whole 2,527-zone city would read ~0%).
# The full 2,527-zone CIS artifact still powers the heatmap / hotspots / forecast.
HOTSPOT_UNIVERSE_SIZE = 60
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
        # Calibration metadata (Task 5): the artifact's reserved `_calibration`
        # block (cis_version, fitted weights, trust metric, …) when present, else a
        # v1/uncalibrated marker. Surfaced at /health. Empty/marker is honest when
        # no calibrated v2 artifact exists yet.
        self.calibration_meta: dict = {}
        self.cis_artifact_path: Optional[Path] = None
        # Served headline time bucket (Task 12): the calibrated "peak window" when
        # serving a calibrated v2 artifact, else "all_day".
        self.headline_bucket: str = "all_day"
        # H3-native daily forecast (PREDICT pillar), keyed by the SAME h3_id as the
        # CIS map. `forecasts` = {h3_id: {predicted_count, predicted_band, ...}};
        # `forecast_meta` = model name + held-out metrics + target date. Empty when
        # the artifact is absent (graceful — endpoints fall back to a proxy).
        self.forecasts: dict[str, dict] = {}
        self.forecast_meta: dict = {}
        # Per-zone SHAP explanations for the forecast (Task 9 sidecar). Empty when
        # the sidecar is absent (pending the v2 forecast build).
        self.forecast_explanations: dict = {}
        self.forecast_explanations_meta: dict = {}
        # CIS validation report (Task 2/10) — the density≠impact proof artifact,
        # served at /validation/proof. Empty until the offline validate_cis run
        # exists (pending the live MapMyIndia collection).
        self.validation_report: dict = {}
        self.traffic_raw: dict = {}
        # Pre-computed driving-route geometries (Route now feature), keyed by
        # rounded "from_lat,from_lon->to_lat,to_lon" coords. Loaded once from
        # data/enriched/routes.json so the demo's station→hotspot routes draw
        # road-following paths fully offline. Empty when absent (the /route
        # endpoint then degrades to a cache miss → null geometry). Cache misses
        # served live are merged back in-memory + persisted by the /route router.
        self.routes: dict = {}
        self.explanations: dict = {}
        self.calibrated: dict = {}
        self.agent_summary: dict = {}
        self.sources: dict = {}

    # ── load ────────────────────────────────────────────────────────────
    def load(self) -> "DataStore":
        # Real MapMyIndia enrichment, keyed by TRUE H3 ids so it matches the CIS
        # universe (Audit P0-2). Prefer the H3-keyed file produced by
        # run_pipeline.py; fall back to the legacy mock-keyed file only if it is
        # absent, so a partial checkout still boots.
        traffic = (_load(self.data_dir / "enriched" / "traffic_context_h3.json", None)
                   or _load(self.data_dir / "enriched" / "traffic_context.json", {}))
        calibrated = _load(self.data_dir / "processed" / "calibrated_scores.json", {})
        agent_log = _load(self.data_dir / "processed" / "agent_log.json", {})
        explanations = _load(self.data_dir / "processed" / "explanations_cache.json", {})

        # Canonical CIS artifact (the QUANTIFY pillar's single source of truth),
        # read as JSON only — no database, no network (Requirements 7.3, 7.4, 11.3).
        # The path resolves to the calibrated v2 artifact when present, else the v1
        # artifact (additive-shadow, Task 5). A missing file is non-fatal: `_load`
        # logs a warning and returns {}, so the backend starts with an empty
        # congestion universe rather than crashing (Requirement 14.3).
        # The artifact is keyed {h3_id: {time_bucket: breakdown}} and is PURE —
        # calibration metadata lives in a separate sidecar (Option A), so no
        # consumer can miscount a phantom metadata "zone".
        cis_path = _resolve_cis_artifact_path(self.data_dir)
        self.cis_artifact_path = cis_path
        serving_v2 = cis_path.name == CIS_V2_FILENAME
        congestion = _load(cis_path, {})
        congestion = congestion if isinstance(congestion, dict) else {}
        # Defensive only (the artifact is pure): drop any "_"-prefixed key so a
        # stray/legacy embedded block can never become a phantom zone.
        self.congestion = {k: v for k, v in congestion.items() if not k.startswith("_")}

        # Calibration metadata from the sidecar. It is trusted only when the v2
        # artifact is actually being served; otherwise we surface an honest
        # uncalibrated marker (never fabricated trust numbers).
        meta_block = _load(self.data_dir / "processed" / CIS_CALIBRATION_META_FILENAME, {})
        if serving_v2 and isinstance(meta_block, dict) and meta_block:
            self.calibration_meta = dict(meta_block)
        else:
            self.calibration_meta = {
                "cis_version": "v2" if serving_v2 else "v1",
                "calibrated": False,
            }

        # Served headline time bucket (Task 12 coherence). When a calibrated v2
        # artifact is being served, the headline "peak window" is the bucket whose
        # MapMyIndia travel-time ratios were measured/fitted (``calibrated_bucket``);
        # otherwise it is the ``all_day`` rollup. The frontend uses this to LABEL
        # which view is the calibrated peak window vs the uncalibrated all_day view.
        # Kept on a SEPARATE attribute (not inside ``calibration_meta``) so the
        # sidecar's exact shape is preserved.
        if self.calibration_meta.get("calibrated"):
            self.headline_bucket = self.calibration_meta.get("calibrated_bucket") or "all_day"
        else:
            self.headline_bucket = "all_day"

        # H3-native forecast artifact (map-aligned). Split into the per-zone map
        # (`zones`) and the model metadata/metrics (everything else).
        forecasts_raw = _load(self.data_dir / "processed" / "forecasts.json", {})
        if isinstance(forecasts_raw, dict):
            zones = forecasts_raw.get("zones")
            self.forecasts = zones if isinstance(zones, dict) else {}
            self.forecast_meta = {k: v for k, v in forecasts_raw.items() if k != "zones"}
        else:
            self.forecasts, self.forecast_meta = {}, {}

        # Forecast SHAP explanations sidecar (Task 9). Absent -> empty (the panel
        # shows the honest-limitations note without a SHAP breakdown).
        fexpl = _load(self.data_dir / "processed" / "forecast_explanations.json", {})
        if isinstance(fexpl, dict):
            self.forecast_explanations = fexpl.get("zones", {}) if isinstance(fexpl.get("zones"), dict) else {}
            self.forecast_explanations_meta = {k: v for k, v in fexpl.items() if k != "zones"}
        else:
            self.forecast_explanations, self.forecast_explanations_meta = {}, {}

        # CIS validation report (Task 2/10): the density≠impact proof. Read as a
        # plain dict; absent -> {} so /validation/proof reports available:False.
        validation_report = _load(
            self.data_dir / "processed" / CIS_VALIDATION_REPORT_FILENAME, {})
        self.validation_report = validation_report if isinstance(validation_report, dict) else {}

        self.traffic_raw = traffic
        self.calibrated = calibrated
        self.agent_summary = {k: v for k, v in agent_log.items() if k != "log"}
        self.explanations = explanations

        # Pre-computed driving-route geometry cache (Route now). Read as JSON only
        # (no network at load) so the demo can draw cached road routes fully
        # offline; absent -> {} (cache miss path). Keyed by rounded coord pairs.
        routes = _load(self.data_dir / "enriched" / "routes.json", {})
        self.routes = routes if isinstance(routes, dict) else {}

        # Build the served hotspot / OPTIMIZE zone universe from the REAL CIS
        # artifact (top-N by violation volume) instead of the legacy mock
        # hotspots. Every id here is a true H3 id matching the CIS map, the
        # traffic enrichment, the calibration, and the forecast — so game theory,
        # simulation, the station views, and /traffic all run on the SAME real
        # zones the map shows (Audit P0-1).
        zones = self._build_zone_universe(traffic, calibrated, HOTSPOT_UNIVERSE_SIZE)

        self.sources = {
            "congestion_artifact_zones": len(self.congestion),
            "cis_artifact": cis_path.name,
            "cis_version": self.calibration_meta.get("cis_version", "v1"),
            "hotspot_universe": len(zones),
            "traffic_context_enriched": len(traffic),
            "calibrated_scores": len(calibrated),
            "explanations_cache": len(explanations),
            "forecast_zones": len(self.forecasts),
        }

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
        logger.info("DataStore loaded: %d hotspot zones from the real CIS artifact "
                    "(%d total CIS zones).", len(zones), len(self.congestion))
        return self

    def _build_zone_universe(self, traffic: dict, calibrated: dict,
                             top_n: int) -> list[dict]:
        """Shape the served hotspot/OPTIMIZE zone universe from the REAL CIS artifact.

        Selects the top-``top_n`` H3 zones by violation volume (their ``all_day``
        rollup) and shapes each into the legacy zone dict the routers and the
        frontend already consume — but populated entirely from real data:

          * identity / coords / station / volume / top-violation / lane-hours,
            ``congestion_impact`` and ``impact_band``  → the CIS artifact
          * ``heavy_vehicle_ratio``                    → the CIS ``vehicle_size``
            component (a real, data-derived signal)
          * ``road_importance`` / ``travel_time_ratio`` / ``road_name`` / POIs
            → real MapMyIndia enrichment (``traffic_context_h3.json``)
          * ``calibrated_score``                       → the self-validating agent
          * ``risk_score`` (enforcement priority, "where violations happen") →
            violation volume scaled 0-100, kept DISTINCT from the CIS (the
            "density != impact" thesis: a busy wide road can have high volume but
            low congestion impact).

        Three fields the dataset genuinely cannot supply are transparent
        ILLUSTRATIVE proxies, not measured values (documented here and in
        API_DOCS): ``peak_weight`` (the ``all_day`` rollup carries no hourly peak),
        ``repeat_offender`` (no plate-level recurrence in the artifact), and
        ``validation_trust``. Everything else is real and id-aligned with the map.

        Returns ``[]`` when the CIS artifact is absent (graceful empty universe).
        """
        # Collect each zone's all_day rollup from the canonical CIS artifact.
        entries: list[tuple[str, dict]] = []
        for h3_id in self.congestion:
            entry = self._bucket_entry(self.congestion.get(h3_id), "all_day")
            if isinstance(entry, dict):
                entries.append((h3_id, entry))

        # Rank by violation volume (enforcement hotspots), deterministic tie-break.
        entries.sort(key=lambda t: (-(int(t[1].get("total_records") or 0)), t[0]))
        if top_n and top_n > 0:
            entries = entries[:top_n]
        max_vol = max((int(e.get("total_records") or 0) for _, e in entries), default=1) or 1

        zones: list[dict] = []
        n_zones = len(entries)
        for i, (h3_id, e) in enumerate(entries):
            tc = traffic.get(h3_id, {}) or {}
            cal = calibrated.get(h3_id, {}) or {}
            comps = e.get("components") or {}
            viol = int(e.get("total_records") or 0)
            cis = float(e.get("congestion_impact") or 0.0)
            ratio = tc.get("travel_time_ratio")
            road = tc.get("road_name") or tc.get("street") or e.get("station") or h3_id
            top_violations = e.get("top_violations") or []
            # Enforcement priority (distinct from CIS): relative priority RANK among
            # the city's hotspot zones, scaled 0-100 (entries are pre-sorted by
            # descending volume, so the busiest zone = 100). A rank percentile —
            # rather than raw min-max volume — gives a meaningful label spread (so
            # the simulation can surface genuinely uncovered HIGH-risk zones) and
            # balanced Stackelberg patrol probabilities, while still meaning "where
            # the most violations are recorded."
            risk_score = round(100.0 * (n_zones - i) / n_zones, 1) if n_zones else 0.0
            density = round(viol / max_vol, 3)
            # Heavy-vehicle obstruction is the REAL CIS vehicle_size component (0-1).
            heavy = round(float(comps.get("vehicle_size") or 0.0), 3)
            road_imp = _road_importance(road, ratio)

            zones.append({
                # identity / map
                "grid_cell_id": h3_id,
                "h3_id": h3_id,
                "grid_lat": e.get("lat"),
                "grid_lon": e.get("lon"),
                "hour": 9,
                # Enforcement-priority score — drives game theory / simulation /
                # markers. DISTINCT from the congestion impact (Decision 2).
                "risk_score": risk_score,
                # Congestion Impact Score (QUANTIFY pillar) straight from the CIS
                # artifact — a distinct value and source from risk_score.
                "congestion_impact": cis,
                "calibrated_score": cal.get("calibrated_score", round(cis, 1)),
                "risk_label": _risk_label(risk_score),
                "impact_band": e.get("impact_band", _band(cis)),
                # volume / risk components
                "violation_count": viol,
                "density": density,                       # REAL volume density
                "road_importance": road_imp,              # REAL (Mappls-informed)
                "peak_weight": 1.0,                       # illustrative (no hourly peak in all_day)
                "repeat_offender": round(0.30 + 0.50 * density, 3),  # illustrative proxy
                "validation_trust": 0.70,                 # illustrative
                "heavy_vehicle_ratio": heavy,             # REAL (CIS vehicle_size component)
                # real MapMyIndia validation
                "travel_time_ratio": ratio,
                "mappls_ratio": ratio,
                "road_name": road,
                "road_type": tc.get("road_type") or ("primary" if road_imp > 0.8 else "secondary"),
                "nearby_pois": tc.get("nearby_pois", []),
                # context
                "police_station": e.get("station"),
                "station": e.get("station"),
                "top_junction": tc.get("locality"),
                "top_violation": top_violations[0] if top_violations else None,
                "estimated_lane_hours_blocked": e.get("estimated_lane_hours_blocked"),
                # agent
                "agent_status": cal.get("status"),
                "agent_reasoning": cal.get("reasoning"),
            })
        return zones

    # ── accessors ───────────────────────────────────────────────────────
    def ensure(self) -> "DataStore":
        if not self.loaded:
            self.load()
        return self

    def _rescore_for_bucket(self, z: dict, time_bucket: str) -> dict:
        """Return a copy of zone ``z`` re-scored to ``time_bucket``'s CIS.

        The served 60-zone universe is built from each zone's ``all_day`` rollup,
        so its ``congestion_impact`` is the all_day value. This looks up the same
        zone's per-bucket breakdown in the full CIS artifact and overwrites ONLY
        the congestion fields (``congestion_impact`` + ``impact_band``) with the
        bucket's values, leaving enforcement fields (``risk_score``,
        ``patrol_probability``, …) as the time-stable all_day values (Decision 2 —
        bucketing enforcement is a separate game-theory change, out of scope).

        The zone SET is never changed (no zone appears/disappears): a missing
        bucket falls back to that zone's ``all_day`` entry via ``_bucket_entry``,
        so the value simply equals the all_day score. ``all_day`` (or empty)
        returns the zone unchanged so existing callers are byte-for-byte stable.
        """
        if not time_bucket or time_bucket == "all_day":
            return z
        entry = self._bucket_entry(self.congestion.get(z["grid_cell_id"]), time_bucket)
        if not isinstance(entry, dict):
            return z
        cis = entry.get("congestion_impact")
        if cis is None:
            return z
        out = dict(z)
        out["congestion_impact"] = float(cis)
        out["impact_band"] = entry.get("impact_band") or _band(float(cis))
        return out

    def top_zones(self, n: int = 15, time_bucket: str = "all_day") -> list[dict]:
        """Top N served zones. Default (``all_day``) is the legacy enforcement-ranked
        slice (unchanged). For a specific bucket, every served zone is RE-SCORED to
        that bucket's congestion_impact and the list is RE-RANKED by it — so the map
        markers / priority strip become time-aware without changing the zone set."""
        self.ensure()
        if not time_bucket or time_bucket == "all_day":
            return self.zones[:n]
        rescored = [self._rescore_for_bucket(z, time_bucket) for z in self.zones]
        rescored.sort(key=lambda z: z.get("congestion_impact") or 0.0, reverse=True)
        return rescored[:n]

    def zone(self, zone_id: str) -> Optional[dict]:
        return self.ensure().zones_by_id.get(zone_id)

    def heatmap_points(self, layer: str) -> list[dict]:
        """Points for the map. layer: raw (violation density) | risk (congestion
        impact) | spillover (agent-calibrated) | violator (game-theory net benefit)."""
        self.ensure()
        pts = []
        for z in self.zones:
            if layer == "raw":
                intensity = z["violation_count"]
            elif layer == "spillover":
                intensity = z["calibrated_score"]
            elif layer == "violator":
                intensity = z["violator_risk_score"]
            else:  # risk / congestion
                intensity = z["risk_score"]
            pts.append({"lat": z["grid_lat"], "lon": z["grid_lon"],
                        "h3_id": z["grid_cell_id"], "intensity": round(float(intensity), 3)})
        pts.sort(key=lambda p: p["intensity"], reverse=True)
        return pts

    # ── congestion impact score (CIS) serving ───────────────────────────
    #
    # These accessors read ONLY from the canonical CIS artifact (``self.congestion``,
    # keyed {h3_id: {time_bucket: breakdown}}). They never touch the legacy
    # enforcement ``risk_score`` — the Congestion Risk layer is served from a real
    # ``congestion_impact`` distinct from ``risk_score`` (Decision 2; Req 10.1,
    # 10.2, 10.3). Everything is in-memory and deterministic: a missing artifact
    # makes ``self.congestion`` empty, so every accessor degrades to ``None`` /
    # ``[]`` rather than raising (Req 7.3, 7.4, 14.3).

    def _bucket_entry(self, buckets: Optional[dict], time_bucket: str) -> Optional[dict]:
        """Pick one zone's breakdown for ``time_bucket`` with an ``all_day`` fallback.

        ``buckets`` is a single zone's ``{time_bucket: breakdown}`` map. The
        requested bucket is returned when present; otherwise the ``all_day`` rollup
        is used (Req 12.3). As a final guard, if neither exists (a hand-built or
        partial artifact with no ``all_day``), the lexicographically-first available
        bucket is returned so a zone that genuinely has data is never reported empty
        (Req 12.5). Returns ``None`` only when the zone carries no usable entry.
        """
        if not isinstance(buckets, dict) or not buckets:
            return None
        entry = buckets.get(time_bucket)
        if not isinstance(entry, dict):
            entry = buckets.get("all_day")
        if not isinstance(entry, dict):
            for key in sorted(buckets):
                candidate = buckets[key]
                if isinstance(candidate, dict):
                    return candidate
            return None
        return entry

    def _entries_for_bucket(self, time_bucket: str):
        """Yield ``(h3_id, breakdown)`` for every zone at ``time_bucket``.

        Iterates zones in sorted ``h3_id`` order (a stable base ordering that each
        accessor then re-sorts for its own purpose) and applies the per-zone
        ``all_day`` fallback via :meth:`_bucket_entry` (Req 12.3). Zones with no
        usable entry are skipped, so an empty artifact yields nothing.
        """
        for h3_id in sorted(self.congestion):
            entry = self._bucket_entry(self.congestion.get(h3_id), time_bucket)
            if entry is not None:
                yield h3_id, entry

    def _calibrated_impact_for(self, zone_id: str) -> Optional[float]:
        """The self-validating agent's calibrated CIS for ``zone_id``, or ``None``.

        Reads the agent's calibration output (``data/processed/calibrated_scores.json``,
        loaded once into ``self.calibrated`` keyed by ``zone_id``). Each record carries
        the agent's bounded, trust-weighted ``calibrated_score`` (always within
        [0, 100]); this returns it as a float WHERE a calibration record exists for
        the zone and its value is numeric, and ``None`` otherwise — so a zone with no
        calibration keeps ``calibrated_impact`` unset (Requirement 6.6). Reads only
        in-memory state; no network, LLM, or database (Req 7.4).
        """
        record = self.calibrated.get(zone_id)
        if not isinstance(record, dict):
            return None
        value = record.get("calibrated_score")
        # Reject bools (a bool is an int subclass) and non-numerics.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def congestion_breakdown(self, zone_id: str, time_bucket: str = "all_day") -> Optional[dict]:
        """Full Congestion Impact breakdown for one zone + time bucket.

        Returns the stored breakdown dict (the contract shape produced by
        ``ml.congestion.impact_score.score_zone`` and serialized into the artifact)
        for ``zone_id`` at ``time_bucket``, falling back to that zone's ``all_day``
        rollup when the requested bucket is unknown/missing (Req 12.3). Returns
        ``None`` for an unknown ``zone_id`` so the caller (the ``/risk`` router) can
        fall back to its legacy zone shape and, failing that, a structured 404
        (Req 14.4). Reads only from the artifact (Req 8.6, 10.2).

        The artifact carries ``calibrated_impact = None`` by default; WHERE the
        self-validating agent produced a calibration for this zone, that value is
        merged in here at serve time so ``/risk/{zone_id}`` exposes it (Req 6.6).
        The merge is done on a shallow copy so the in-memory artifact entry is never
        mutated; when no calibration exists the field stays ``None``.
        """
        self.ensure()
        entry = self._bucket_entry(self.congestion.get(zone_id), time_bucket)
        if entry is None:
            return None
        # Shallow copy so the in-memory artifact entry is never mutated; we attach
        # the agent's calibrated_impact (when present) and the Task 12 time_regime
        # label below without touching the canonical artifact.
        merged = dict(entry)
        calibrated_impact = self._calibrated_impact_for(zone_id)
        if calibrated_impact is not None:
            merged["calibrated_impact"] = calibrated_impact
        # Task 12 coherence: label the served breakdown's regime. It is
        # "calibrated" ONLY when a calibrated v2 artifact is being served AND the
        # requested bucket is the measured/fitted peak window (``calibrated_bucket``);
        # every other bucket — notably the ``all_day`` rollup — is honestly
        # "uncalibrated". Additive: the field is optional on the contract and was
        # absent (None) before this task.
        if (self.calibration_meta.get("calibrated")
                and time_bucket == self.calibration_meta.get("calibrated_bucket")):
            merged["time_regime"] = "calibrated"
        else:
            merged["time_regime"] = "uncalibrated"
        return merged


    def congestion_points(self, time_bucket: str = "all_day") -> list[dict]:
        """Congestion Risk heatmap layer — one point per zone, intensity = CIS.

        Each point carries ``lat``/``lon``/``h3_id``/``impact_band`` and an
        ``intensity`` equal to the zone's ``congestion_impact`` (Req 8.3, 10.2) —
        NOT the enforcement ``risk_score`` and NOT the raw violation count. Points
        are sorted by descending intensity (``h3_id`` tie-break) for deterministic
        output. An empty artifact yields ``[]`` (Req 14.3).
        """
        self.ensure()
        pts = [
            {
                "lat": e.get("lat"),
                "lon": e.get("lon"),
                "h3_id": h3_id,
                "intensity": round(float(e.get("congestion_impact") or 0.0), 3),
                "impact_band": e.get("impact_band"),
            }
            for h3_id, e in self._entries_for_bucket(time_bucket)
        ]
        pts.sort(key=lambda p: (-p["intensity"], p["h3_id"]))
        return pts

    def violation_density_points(self, time_bucket: str = "all_day") -> list[dict]:
        """Raw Violation Density heatmap layer — one point per zone, intensity = count.

        Identical point shape to :meth:`congestion_points`, but ``intensity`` is the
        zone's ``total_records`` (the raw violation count), NOT the CIS (Req 8.4).
        Serving the count here — rather than the score — is what makes the
        two-layer toggle genuinely different: a high-volume, low-impact zone ranks
        high on this layer yet low on the Congestion Risk layer. Sorted by
        descending intensity (``h3_id`` tie-break); empty artifact yields ``[]``.
        """
        self.ensure()
        pts = [
            {
                "lat": e.get("lat"),
                "lon": e.get("lon"),
                "h3_id": h3_id,
                "intensity": float(e.get("total_records") or 0),
                "impact_band": e.get("impact_band"),
            }
            for h3_id, e in self._entries_for_bucket(time_bucket)
        ]
        pts.sort(key=lambda p: (-p["intensity"], p["h3_id"]))
        return pts

    def congestion_hotspots(self, time_bucket: str = "all_day",
                            limit: Optional[int] = None) -> list[dict]:
        """Zones ranked in DESCENDING congestion impact (Req 8.5).

        Returns one dict per zone carrying every field the ``HotspotItem`` contract
        needs — ``rank`` (1-based, assigned after ranking), ``zone_id``, ``h3_id``,
        ``lat``, ``lon``, ``congestion_impact``, ``impact_band``,
        ``violation_count`` (the zone's ``total_records``), ``station``,
        ``top_violation`` (the most frequent of ``top_violations``), and
        ``estimated_lane_hours_blocked``. Ranking is by descending CIS with an
        ``h3_id`` tie-break for determinism; ``limit`` optionally truncates the list
        (ranks still start at 1). Empty artifact yields ``[]``.
        """
        self.ensure()
        items = []
        for h3_id, e in self._entries_for_bucket(time_bucket):
            top = e.get("top_violations") or []
            items.append({
                "zone_id": e.get("zone_id", h3_id),
                "h3_id": h3_id,
                "lat": e.get("lat"),
                "lon": e.get("lon"),
                "congestion_impact": float(e.get("congestion_impact") or 0.0),
                "impact_band": e.get("impact_band"),
                "violation_count": int(e.get("total_records") or 0),
                "station": e.get("station"),
                "top_violation": top[0] if top else None,
                "estimated_lane_hours_blocked": float(e.get("estimated_lane_hours_blocked") or 0.0),
            })
        items.sort(key=lambda d: (-d["congestion_impact"], d["h3_id"]))
        if limit is not None and limit >= 0:
            items = items[:limit]
        for rank, item in enumerate(items, start=1):
            item["rank"] = rank
        return items

    def congestion_patrol_probabilities(self, time_bucket: str = "all_day") -> list[dict]:
        """Stackelberg patrol probability per zone, proportional to CIS^1.5 (Req 8.7).

        For each zone the unnormalized weight is ``max(congestion_impact, 0) **
        PATROL_ALPHA`` (``PATROL_ALPHA == 1.5``); probabilities are those weights
        normalized across zones so they sum to 1.0. The all-zero / empty case is
        guarded: when every CIS is 0 (or there are no zones) the weight sum is 0,
        so each ``patrol_probability`` is set to 0.0 with no division by zero (and
        an empty artifact simply yields ``[]``). Probabilities are left unrounded so
        the normalized sum stays exact. Sorted by descending probability (``h3_id``
        tie-break); since probability is monotonic in CIS this is also descending
        CIS order.
        """
        self.ensure()
        rows: list[dict] = []
        weights: list[float] = []
        for h3_id, e in self._entries_for_bucket(time_bucket):
            cis = float(e.get("congestion_impact") or 0.0)
            rows.append({
                "zone_id": e.get("zone_id", h3_id),
                "h3_id": h3_id,
                "lat": e.get("lat"),
                "lon": e.get("lon"),
                "congestion_impact": cis,
            })
            weights.append(max(cis, 0.0) ** PATROL_ALPHA)

        wsum = sum(weights)
        for row, weight in zip(rows, weights):
            row["patrol_probability"] = (weight / wsum) if wsum > 0 else 0.0
        rows.sort(key=lambda r: (-r["patrol_probability"], r["h3_id"]))
        return rows

    # ── forecast (PREDICT pillar, H3-native, map-aligned) ───────────────
    def forecast_metrics(self) -> dict:
        """Model metadata + held-out metrics for the H3 forecast (no per-zone data)."""
        return self.ensure().forecast_meta

    def forecast_for_zone(self, zone_id: str) -> Optional[dict]:
        """Next-day forecast for one H3 zone (same id space as the CIS map)."""
        self.ensure()
        rec = self.forecasts.get(zone_id)
        return {**rec, "zone_id": zone_id, "h3_id": zone_id} if isinstance(rec, dict) else None

    def forecast_top_zones(self, n: int = 10) -> list[dict]:
        """Zones ranked by predicted next-day violation count (descending)."""
        self.ensure()
        rows = [{**rec, "zone_id": z, "h3_id": z} for z, rec in self.forecasts.items()]
        rows.sort(key=lambda r: (-(r.get("predicted_count") or 0.0), r["h3_id"]))
        return rows[:n] if n else rows

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

    def station_zones(self, station: str, time_bucket: str = "all_day") -> list[dict]:
        """Zones under a station. Default (``all_day``) is the legacy slice. For a
        specific bucket, zones are re-scored to that bucket's congestion_impact and
        re-ranked by it (enforcement fields stay all_day; the zone set is stable)."""
        self.ensure()
        zones = [z for z in self.zones if (z["station"] or "").lower() == station.lower()]
        if not time_bucket or time_bucket == "all_day":
            return zones
        rescored = [self._rescore_for_bucket(z, time_bucket) for z in zones]
        rescored.sort(key=lambda z: z.get("congestion_impact") or 0.0, reverse=True)
        return rescored

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

    def patrol_allocation_with_exploration(self, epsilon: float = 0.10) -> dict:
        """ε-greedy patrol allocation: 90% exploit (risk^1.5) + 10% explore (Task 9).

        Bias mitigation for the predictive-policing feedback loop: ``epsilon`` of
        the patrol mass is directed at under-observed (low violation-count) zones
        so the system can discover violations the enforcement record misses. The
        allocation sums to 1.0; the exploit-only ``patrol_probability`` field is
        left unchanged for backward compatibility.
        """
        self.ensure()
        from ml.game.exploration import HONEST_LIMITATION, epsilon_greedy_allocation

        zones = self.zones
        if not zones:
            return {"epsilon": epsilon, "exploration_pct": round(epsilon * 100, 1),
                    "n_zones": 0, "zones": [], "honest_limitation": HONEST_LIMITATION}

        risk = [z["risk_score"] for z in zones]
        counts = [z["violation_count"] for z in zones]
        alloc = epsilon_greedy_allocation(risk, counts, epsilon=epsilon)

        rows = []
        for z, p in zip(zones, alloc):
            rows.append({
                "grid_cell_id": z["grid_cell_id"],
                "h3_id": z["h3_id"],
                "lat": z["grid_lat"],
                "lon": z["grid_lon"],
                "risk_score": z["risk_score"],
                "violation_count": z["violation_count"],
                "patrol_probability": z["patrol_probability"],          # exploit-only (unchanged)
                "patrol_probability_explore": float(p),                 # ε-greedy (unrounded: exact sum 1.0)
            })
        rows.sort(key=lambda r: (-r["patrol_probability_explore"], r["grid_cell_id"]))
        return {
            "epsilon": epsilon,
            "exploration_pct": round(epsilon * 100, 1),
            "n_zones": len(rows),
            "zones": rows,
            "honest_limitation": HONEST_LIMITATION,
        }

    def forecast_explanation_for(self, zone_id: str) -> Optional[dict]:
        """Per-zone SHAP explanation for the forecast (Task 9), or ``None``."""
        self.ensure()
        rec = self.forecast_explanations.get(zone_id)
        return {**rec, "zone_id": zone_id, "h3_id": zone_id} if isinstance(rec, dict) else None

    def forecast_explanations_list(self, limit: int = 50) -> dict:
        """Forecast SHAP explanations: metadata + the first ``limit`` zones."""
        self.ensure()
        zones = self.forecast_explanations
        available = bool(zones)
        items = [{**rec, "zone_id": z, "h3_id": z} for z, rec in list(zones.items())[:limit]]
        return {
            "available": available,
            **self.forecast_explanations_meta,
            "zones": items,
        }

    def validation_proof(self) -> dict:
        """CIS density≠impact proof payload (Task 13), from the offline report.

        Reads ONLY ``cis_validation_report.json`` (the Task 2/10 output). Returns a
        stable, additive shape carrying the three held-out **test-split** Spearman
        correlations vs the measured MapMyIndia ratio — the honest non-circular CIS
        (the 4 violation/road components, NO traffic_degradation), the raw-violation
        ``count`` baseline, and the full CIS upper bound (flagged circular) — each
        with its bootstrap CI, plus ``baseline_beaten``, ``calibration_strength``
        (populated by Task 15; ``None`` until then), and the per-zone scatter
        points. Degrades to ``available: False`` with no points when the report is
        absent (pending the live peak-time collection) so the panel renders a
        graceful pending state rather than fabricated numbers. Reads only in-memory
        state — no network, LLM, or database.
        """
        self.ensure()
        r = self.validation_report if isinstance(self.validation_report, dict) else {}
        point_keys = ("h3_id", "cis", "cis_honest", "count",
                      "measured_ratio", "is_exploration", "split")
        points = [
            {k: p.get(k) for k in point_keys}
            for p in (r.get("points") or [])
            if isinstance(p, dict)
        ]
        available = bool(r) and (r.get("n_measured") is not None or bool(points))
        return {
            "available": bool(available),
            "n_measured": r.get("n_measured"),
            "n_proof": r.get("n_proof"),
            "n_exploration": r.get("n_exploration"),
            # Honest, non-circular CIS — the headline trust metric.
            "spearman_cis_honest": r.get("spearman_cis_honest_test"),
            "spearman_cis_honest_ci": r.get("spearman_cis_honest_test_ci"),
            # Raw violation-count baseline (the "density" view to beat).
            "spearman_count": r.get("spearman_count_test"),
            "spearman_count_ci": r.get("spearman_count_test_ci"),
            # Full CIS — circular upper bound (contains the measured ratio).
            "spearman_cis_full": r.get("spearman_cis_full_test"),
            "spearman_cis_full_ci": r.get("spearman_cis_full_test_ci"),
            "cis_full_note": r.get("cis_full_note"),
            "baseline_beaten": r.get("baseline_beaten"),
            "calibration_strength": r.get("calibration_strength"),
            "honest_weights": r.get("honest_weights"),
            "honest_excludes": r.get("honest_excludes"),
            "split_seed": r.get("split_seed"),
            "time_bucket": r.get("time_bucket"),
            "generated_at": r.get("generated_at"),
            "points": points,
        }

    def throughput_simulation(self, max_teams: int = 20,
                              top_n: Optional[int] = None,
                              time_bucket: str = "all_day") -> dict:
        """Before/after city congestion index across team counts (Task 7).

        Grounded in the **calibrated** CIS served by this store: selects the
        top-``top_n`` zones by congestion impact (defaults to the operational
        ``HOTSPOT_UNIVERSE_SIZE``) and runs the transparent, documented throughput
        model in ``ml.game.throughput_sim``. Offline and deterministic — every
        constant is returned in the ``constants`` block and the minutes figure is
        an explicitly illustrative modeled estimate.
        """
        self.ensure()
        from ml.game.throughput_sim import (
            compute_measured_minutes, select_top_cis, simulate_throughput,
        )

        if top_n is None:
            top_n = HOTSPOT_UNIVERSE_SIZE
        cis_values = select_top_cis(self.congestion, top_n=top_n, time_bucket=time_bucket)
        result = simulate_throughput(cis_values, max_teams=max_teams)
        result["cis_artifact"] = self.cis_artifact_path.name if self.cis_artifact_path else None
        result["cis_version"] = self.calibration_meta.get("cis_version", "v1")
        result["top_n"] = top_n
        # Additive (never changes the %-reduction headline above): the real,
        # MapMyIndia-grounded minutes-saved estimate on the MEASURED corridors.
        # Reports a pending block until a live collection + Task 4 model exist.
        obs_path = self.data_dir / "enriched" / "congestion_observations.json"
        if obs_path.exists():
            observations = _load(obs_path, {})
            result["measured_minutes"] = compute_measured_minutes(
                self.congestion, observations if isinstance(observations, dict) else {},
                n_teams=max_teams, time_bucket=time_bucket,
            )
        else:
            from ml.game.throughput_sim import _pending_measured_block
            result["measured_minutes"] = _pending_measured_block(
                "No measured corridors yet — pending a live MapMyIndia collector run."
            )
        return result

    def agent_report(self) -> dict:
        """Self-validating agent: summary + per-zone calibration log + calibration run.

        ``calibration_run`` is the agent's offline before/after weight + trust block
        (Task 6), baked into ``agent_log.json`` by the agent run and surfaced here
        additively. When absent (no calibration run yet) it degrades to an honest
        ``{"available": False}`` so the panel can render a "pending" state.
        """
        self.ensure()
        calibration_run = self.agent_summary.get("calibration_run") or {"available": False}
        return {"summary": self.agent_summary,
                "zones": list(self.calibrated.values()),
                "calibration_run": calibration_run}


# Module-level singleton (loaded at app startup in main.py).
store = DataStore()