"""
ParkVision-Saathi — MapMyIndia congestion collector v2 (local-segment)
=======================================================================

Task 1 of the calibration brief. Measures *local* congestion at H3 zones via
MapMyIndia, within a hard call budget, into a clean artifact the calibration
pipeline (Tasks 2-4) consumes.

Why a new module (and not an edit to ``ml/enrichment/mapmyindia.py``)
---------------------------------------------------------------------
The legacy collector measures one trip **zone -> Bengaluru city centre**. That
conflates congestion along the *whole corridor* into the city, not the
congestion *at the zone*. This module instead measures four short ~350 m legs
around each zone centroid (N/E/S/W) and takes the **median** of their
``eta/baseline`` ratios, so the signal reflects local conditions. The legacy
module and its ``data/enriched/traffic_context.json`` output are left untouched
(additive-shadow rule).

Local-segment method (``method = "local_segment_v2"``)
------------------------------------------------------
For each zone centroid ``(lat, lon)`` we build 4 destination points offset by
~350 m to the N/E/S/W (``Δlat ≈ 0.0035``, ``Δlon ≈ 0.0036`` at ~13°N). For each
leg we query:
  * ``distance_matrix``      (no traffic)   -> baseline seconds + distance metres
  * ``distance_matrix_eta``  (live traffic) -> eta seconds
and set ``ratio = eta_s / baseline_s`` per leg. The zone's
``congestion_ratio = median(ratio over legs)``.

Free-flow speed (road-size proxy used by later tasks)
-----------------------------------------------------
Preferred: the ``results.distances`` array returned by the *baseline* distance
matrix response (``⚠️ VERIFY`` it is present for the configured plan). When
present, ``free_flow_speed_kmph = distance_m / baseline_s * 3.6`` (median over
legs) with ``free_flow_speed_approx = False``. When the API omits distances we
fall back to the haversine length of each leg (≈350 m by construction) and set
``free_flow_speed_approx = True``.

Budget guard
------------
``--budget MAX_CALLS`` caps the number of API calls. Estimated calls per
*uncached* zone ``= legs*2 + 1 (reverse geocode) + 1 (nearby POI)`` (= 10 for the
default 4 legs). The collector prints the call estimate and the ₹ cost
(``RUPEES_PER_CALL`` — ``⚠️ VERIFY`` against the live plan) and **refuses to run**
(raises :class:`BudgetExceededError`) when the estimate exceeds the budget.

Caching
-------
Per-zone results are written incrementally to the output JSON. A second run
re-reads that file and makes **zero** calls for already-collected zones (pass
``--refresh`` to force re-collection).

Exploration sampling
--------------------
Zones = the top ``--top-n`` by violation volume (``all_day`` ``total_records``)
**plus** a seeded random ``--explore-n`` lower-volume zones, each tagged
``is_exploration``. This keeps the downstream trust metric from being measured
only on dense zones and supports the bias-mitigation story (Task 9).

Peak-time
---------
MapMyIndia's distance matrix exposes no departure-time/predictive parameter
(``⚠️ VERIFY``), so the collector records ``measured_at`` (ISO + IST hour) and
**prints a warning** when run outside the Bengaluru congestion windows
(~08:00-11:00 and ~18:00-20:00 IST) — off-peak runs make every ratio ≈ 1.0 and
destroy the calibration.

Output: ``data/enriched/congestion_observations.json`` keyed by ``h3_id``.

Secrets: the key is read from ``MAPPLS_STATIC_KEY`` and is **never** printed or
written to the artifact.

Run::

    python ml/enrichment/congestion_collector.py --dry-run
    python ml/enrichment/congestion_collector.py --budget 1600 --top-n 110 --explore-n 40
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Callable, Mapping, Optional, Sequence

# ─── Paths ───────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ARTIFACT_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "enriched" / "congestion_observations.json"

# ─── MapMyIndia endpoints (duplicated from mapmyindia.py on purpose: importing
#     that module triggers its import-time key check / sys.exit, which would
#     break tests and --dry-run when no key is present). ────────────────────────

DM_BASE = "https://route.mappls.com/route/dm"
RG_BASE = "https://search.mappls.com/search/address/rev-geocode"
POI_BASE = "https://search.mappls.com/search/places/nearby/json"

ENV_KEY = "MAPPLS_STATIC_KEY"

# ─── Local-segment geometry ──────────────────────────────────────────────────
#
# ~350 m offsets. 1° latitude ≈ 111.32 km -> 0.0035° ≈ 389 m (we use the
# haversine length in output, this is just the construction offset). 1° longitude
# at ~13°N ≈ 108.5 km -> 0.0036° ≈ 390 m. Kept symmetric and documented.
OFFSET_LAT = 0.0035
OFFSET_LON = 0.0036
TARGET_LEG_METRES = 350.0

# (direction_label, d_lat, d_lon) for the four legs around a centroid.
LEG_OFFSETS: tuple[tuple[str, float, float], ...] = (
    ("N", OFFSET_LAT, 0.0),
    ("E", 0.0, OFFSET_LON),
    ("S", -OFFSET_LAT, 0.0),
    ("W", 0.0, -OFFSET_LON),
)

# ─── Budget / pricing ────────────────────────────────────────────────────────
#
# ⚠️ VERIFY against the live MapMyIndia plan. Public pricing is not published
# per-call; the mid-tier "Business" plan (~₹30,000/month for ~1M transactions)
# implies ~₹0.03 / transaction. We keep a conservative documented default and
# expose it as a CLI flag so the printed ₹ figure can be corrected without code
# changes. The hard budget guard is enforced on the *call count* (--budget),
# which is plan-independent.
RUPEES_PER_CALL = 0.03
DEFAULT_BUDGET_CALLS = 1600  # 150 zones * 10 calls + headroom; refuse if exceeded
TOTAL_RUPEE_BUDGET = 1000.0  # informational only (the brief's MapMyIndia budget)

# Calls per uncached zone = legs*2 (baseline + eta) + reverse_geocode + nearby.
REVERSE_GEOCODE_CALLS = 1
NEARBY_CALLS = 1

# ─── Sampling defaults ───────────────────────────────────────────────────────

DEFAULT_TOP_N = 110          # top zones by violation volume (is_exploration=False)
DEFAULT_EXPLORE_N = 40       # seeded random lower-volume zones (is_exploration=True)
DEFAULT_SEED = 42

# ─── POI query defaults ──────────────────────────────────────────────────────

DEFAULT_POI_KEYWORDS = "bus stop"
DEFAULT_POI_RADIUS = 500
POI_LIMIT = 5

# ─── Rate limiting ───────────────────────────────────────────────────────────

SLEEP_BETWEEN_ZONES = 0.6
SLEEP_BETWEEN_APIS = 0.3
API_TIMEOUT = 20

# ─── Peak-time windows (IST hour-of-day, inclusive start, exclusive end) ─────

IST = timezone(timedelta(hours=5, minutes=30))
PEAK_WINDOWS: tuple[tuple[int, int], ...] = ((8, 11), (18, 20))

METHOD_TAG = "local_segment_v2"
SOURCE_TAG = "mapmyindia"


class BudgetExceededError(RuntimeError):
    """Raised when the estimated number of API calls exceeds the budget."""


class SnapshotFrozenError(RuntimeError):
    """Raised when a frozen observations snapshot would be overwritten without --force."""


# ─── Typed zone selection ────────────────────────────────────────────────────

@dataclass(frozen=True)
class ZoneSpec:
    """One zone selected for measurement."""

    zone_id: str
    lat: float
    lon: float
    total_records: int
    station: Optional[str]
    is_exploration: bool


# ─── Pure geometry / math helpers (no I/O — unit-tested directly) ────────────

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in metres."""
    r = 6_371_000.0  # mean Earth radius (m)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def leg_endpoints(lat: float, lon: float) -> list[tuple[str, float, float]]:
    """Return the four ~350 m N/E/S/W destination points around a centroid."""
    return [(d, lat + dlat, lon + dlon) for d, dlat, dlon in LEG_OFFSETS]


def parse_distance_matrix(data: Optional[Mapping]) -> tuple[Optional[float], Optional[float]]:
    """Parse a Mappls distance-matrix response into ``(duration_s, distance_m)``.

    Reads ``results.durations[0][1]`` (source->dest seconds) and, when present,
    ``results.distances[0][1]`` (metres). Returns ``(None, None)`` for a missing
    or non-``Ok`` response. ``distance_m`` is ``None`` when the plan omits the
    distances matrix (``⚠️ VERIFY``), which triggers the haversine fallback.
    """
    if not data:
        return None, None
    results = data.get("results", {})
    if not isinstance(results, Mapping) or results.get("code") != "Ok":
        return None, None

    duration_s: Optional[float] = None
    durations = results.get("durations")
    if isinstance(durations, Sequence) and durations and isinstance(durations[0], Sequence) and len(durations[0]) >= 2:
        try:
            duration_s = float(durations[0][1])
        except (TypeError, ValueError):
            duration_s = None

    distance_m: Optional[float] = None
    distances = results.get("distances")
    if isinstance(distances, Sequence) and distances and isinstance(distances[0], Sequence) and len(distances[0]) >= 2:
        try:
            distance_m = float(distances[0][1])
        except (TypeError, ValueError):
            distance_m = None

    return duration_s, distance_m


def compute_congestion_ratio(legs: Sequence[Mapping]) -> Optional[float]:
    """Median ``eta/baseline`` ratio over the legs with valid, positive timings."""
    ratios = [
        float(leg["ratio"])
        for leg in legs
        if leg.get("ratio") is not None and math.isfinite(float(leg["ratio"])) and leg["ratio"] > 0
    ]
    if not ratios:
        return None
    return float(median(ratios))


def compute_free_flow_speed(legs: Sequence[Mapping]) -> tuple[Optional[float], bool]:
    """Median free-flow speed (km/h) over legs; flag True if any leg used haversine.

    ``free_flow_speed_kmph = distance_m / baseline_s * 3.6`` per leg, using the
    API distance when available and the haversine leg length otherwise. The
    returned ``approx`` flag is True when *any* contributing leg fell back to the
    haversine length (so consumers know the proxy is approximate).
    """
    speeds: list[float] = []
    approx = False
    for leg in legs:
        baseline_s = leg.get("baseline_s")
        if not baseline_s or baseline_s <= 0:
            continue
        dist = leg.get("distance_m")
        if dist is None:
            dist = leg.get("haversine_m")
            if dist is not None:
                approx = True
        if dist is None or dist <= 0:
            continue
        speeds.append(float(dist) / float(baseline_s) * 3.6)
    if not speeds:
        return None, approx
    return float(median(speeds)), approx


def estimate_calls(n_zones: int, legs: int = len(LEG_OFFSETS)) -> int:
    """Estimated API calls for ``n_zones`` uncached zones."""
    per_zone = legs * 2 + REVERSE_GEOCODE_CALLS + NEARBY_CALLS
    return n_zones * per_zone


def estimate_rupees(n_calls: int, rupees_per_call: float = RUPEES_PER_CALL) -> float:
    """Estimated ₹ cost for ``n_calls`` API calls."""
    return n_calls * rupees_per_call


def is_peak_ist(hour: int, windows: Sequence[tuple[int, int]] = PEAK_WINDOWS) -> bool:
    """True when ``hour`` (IST 0-23) falls inside any congestion window."""
    return any(start <= hour < end for start, end in windows)


# ─── Zone selection ──────────────────────────────────────────────────────────

def _all_day_breakdown(buckets: Mapping) -> Optional[Mapping]:
    """Return the ``all_day`` breakdown, or any bucket as a fallback."""
    if "all_day" in buckets:
        return buckets["all_day"]
    for value in buckets.values():
        if isinstance(value, Mapping):
            return value
    return None


def select_zones(
    artifact: Mapping[str, Mapping],
    *,
    top_n: int = DEFAULT_TOP_N,
    explore_n: int = DEFAULT_EXPLORE_N,
    seed: int = DEFAULT_SEED,
) -> list[ZoneSpec]:
    """Select top-by-volume zones plus a seeded random exploration sample.

    Zones are ranked by ``all_day`` ``total_records`` (descending, ``zone_id`` as a
    deterministic tie-break). The top ``top_n`` are core (``is_exploration=False``);
    a seeded random ``explore_n`` are drawn from the remaining lower-volume zones
    (``is_exploration=True``). Selection is fully deterministic for a fixed seed.
    """
    candidates: list[ZoneSpec] = []
    for zone_id, buckets in artifact.items():
        if not isinstance(buckets, Mapping):
            continue
        bd = _all_day_breakdown(buckets)
        if bd is None:
            continue
        lat, lon = bd.get("lat"), bd.get("lon")
        if lat is None or lon is None:
            continue
        candidates.append(
            ZoneSpec(
                zone_id=str(zone_id),
                lat=float(lat),
                lon=float(lon),
                total_records=int(bd.get("total_records", 0) or 0),
                station=bd.get("station"),
                is_exploration=False,
            )
        )

    # Deterministic ranking: volume desc, then zone_id asc.
    candidates.sort(key=lambda z: (-z.total_records, z.zone_id))

    core = candidates[:top_n]
    remainder = candidates[top_n:]

    rng = random.Random(seed)
    explore_sample: list[ZoneSpec] = []
    if remainder and explore_n > 0:
        k = min(explore_n, len(remainder))
        chosen = rng.sample(remainder, k)
        # Re-tag as exploration; keep a stable order by zone_id for reproducibility.
        explore_sample = [
            ZoneSpec(z.zone_id, z.lat, z.lon, z.total_records, z.station, True)
            for z in sorted(chosen, key=lambda z: z.zone_id)
        ]

    return core + explore_sample


# ─── HTTP layer (injectable for tests) ───────────────────────────────────────

GetJson = Callable[[str, Mapping, str], Optional[dict]]


def _default_get_json(url: str, params: Mapping, label: str) -> Optional[dict]:
    """Real HTTP GET returning parsed JSON, or None on any error."""
    import httpx  # local import so the module imports without httpx installed

    try:
        resp = httpx.get(url, params=dict(params), timeout=API_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        print(f"      ⚠️  {label}: HTTP {resp.status_code}")
        return None
    except Exception as exc:  # noqa: BLE001 — network errors are non-fatal per zone
        print(f"      ⚠️  {label}: {type(exc).__name__}")
        return None


def query_distance_matrix(
    get_json: GetJson,
    token: str,
    src: tuple[float, float],
    dst: tuple[float, float],
    resource: str,
) -> tuple[Optional[float], Optional[float]]:
    """One distance-matrix call. ``src``/``dst`` are ``(lat, lon)``; coords go as
    ``lon,lat`` per the Mappls spec. Returns ``(duration_s, distance_m)``."""
    (slat, slon), (dlat, dlon) = src, dst
    coords = f"{slon},{slat};{dlon},{dlat}"
    url = f"{DM_BASE}/{resource}/driving/{coords}"
    params = {"access_token": token, "rtype": 0, "region": "ind"}
    return parse_distance_matrix(get_json(url, params, resource))


def query_reverse_geocode(get_json: GetJson, token: str, lat: float, lon: float) -> Optional[str]:
    """Reverse-geocode a centroid to a human road/locality name (or None)."""
    params = {"lat": lat, "lng": lon, "access_token": token}
    data = get_json(RG_BASE, params, "reverse_geocode")
    if not data:
        return None
    results = data.get("results") or []
    if not results:
        return None
    r = results[0]
    street = (r.get("street") or "").strip()
    locality = (r.get("locality") or "").strip()
    name = ", ".join(part for part in (street, locality) if part)
    return name or (r.get("formatted_address") or None)


def query_nearby_pois(
    get_json: GetJson,
    token: str,
    lat: float,
    lon: float,
    *,
    keywords: str = DEFAULT_POI_KEYWORDS,
    radius: int = DEFAULT_POI_RADIUS,
) -> list[dict]:
    """Nearby POIs around a centroid: ``[{name, category, distance_m}, ...]``."""
    params = {
        "keywords": keywords,
        "refLocation": f"{lat},{lon}",
        "radius": radius,
        "region": "IND",
        "sortBy": "dist:asc",
        "page": 1,
        "access_token": token,
    }
    data = get_json(POI_BASE, params, "nearby_poi")
    if not data:
        return []
    pois: list[dict] = []
    for item in (data.get("suggestedLocations") or [])[:POI_LIMIT]:
        cats = item.get("keywords") or []
        pois.append(
            {
                "name": item.get("placeName", "POI"),
                "category": cats[0] if isinstance(cats, list) and cats else None,
                "distance_m": item.get("distance"),
            }
        )
    return pois


# ─── Per-zone measurement ────────────────────────────────────────────────────

def measure_zone(
    zone: ZoneSpec,
    get_json: GetJson,
    token: str,
    *,
    measured_at: str,
    poi_keywords: str = DEFAULT_POI_KEYWORDS,
    poi_radius: int = DEFAULT_POI_RADIUS,
    sleep_between_apis: float = 0.0,
) -> dict:
    """Run the local-segment measurement for one zone and return its observation."""
    raw_legs: list[dict] = []
    for direction, dlat, dlon in LEG_OFFSETS:
        dst = (zone.lat + dlat, zone.lon + dlon)
        src = (zone.lat, zone.lon)

        baseline_s, distance_m = query_distance_matrix(get_json, token, src, dst, "distance_matrix")
        if sleep_between_apis:
            time.sleep(sleep_between_apis)
        eta_s, _ = query_distance_matrix(get_json, token, src, dst, "distance_matrix_eta")
        if sleep_between_apis:
            time.sleep(sleep_between_apis)

        ratio = (eta_s / baseline_s) if (baseline_s and baseline_s > 0 and eta_s) else None
        raw_legs.append(
            {
                "direction": direction,
                "baseline_s": baseline_s,
                "eta_s": eta_s,
                "distance_m": distance_m,
                "haversine_m": round(haversine_m(src[0], src[1], dst[0], dst[1]), 1),
                "ratio": round(ratio, 4) if ratio is not None else None,
            }
        )

    road_name = query_reverse_geocode(get_json, token, zone.lat, zone.lon)
    if sleep_between_apis:
        time.sleep(sleep_between_apis)
    pois = query_nearby_pois(get_json, token, zone.lat, zone.lon, keywords=poi_keywords, radius=poi_radius)

    ratio = compute_congestion_ratio(raw_legs)
    ff_speed, ff_approx = compute_free_flow_speed(raw_legs)
    n_legs = sum(1 for leg in raw_legs if leg["ratio"] is not None)

    return {
        "zone_id": zone.zone_id,
        "lat": zone.lat,
        "lon": zone.lon,
        "congestion_ratio": round(ratio, 4) if ratio is not None else None,
        "n_legs": n_legs,
        "raw_legs": [
            {"direction": leg["direction"], "baseline_s": leg["baseline_s"], "eta_s": leg["eta_s"], "ratio": leg["ratio"]}
            for leg in raw_legs
        ],
        "free_flow_speed_kmph": round(ff_speed, 2) if ff_speed is not None else None,
        "free_flow_speed_approx": ff_approx,
        "road_name": road_name,
        "station": zone.station,
        "pois": pois,
        "is_exploration": zone.is_exploration,
        "measured_at": measured_at,
        "method": METHOD_TAG,
        "source": SOURCE_TAG,
    }


# ─── I/O helpers ─────────────────────────────────────────────────────────────

def load_artifact(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_existing_observations(path: Path) -> dict:
    """Load already-collected observations for caching (empty dict if absent)."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


# ─── Immutable snapshot (frozen provenance, Task 11) ─────────────────────────

def snapshot_meta_path(output_path: Path) -> Path:
    """Sidecar path holding the frozen-snapshot metadata for an observations file."""
    output_path = Path(output_path)
    return output_path.with_name(output_path.name + ".meta.json")


def read_snapshot_meta(output_path: Path) -> dict:
    """Read the snapshot meta sidecar (``{}`` if absent/unreadable)."""
    meta_path = snapshot_meta_path(output_path)
    if not meta_path.exists():
        return {}
    try:
        with meta_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def is_frozen(output_path: Path) -> bool:
    """True when a frozen snapshot meta sidecar exists for ``output_path``."""
    return bool(read_snapshot_meta(output_path).get("frozen"))


def observations_content_sha256(observations: dict) -> str:
    """Content hash of an observations dict (auditable provenance chain)."""
    from ml.congestion.stats_utils import content_sha256
    return content_sha256(observations)


def write_snapshot_meta(output_path: Path, observations: dict, measured_at: str) -> dict:
    """Freeze the snapshot: write ``{frozen, content_sha256, measured_at, n_zones}``."""
    meta = {
        "frozen": True,
        "content_sha256": observations_content_sha256(observations),
        "measured_at": measured_at,
        "n_zones": len(observations),
        "source": SOURCE_TAG,
        "method": METHOD_TAG,
    }
    meta_path = snapshot_meta_path(output_path)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with meta_path.open("w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, ensure_ascii=False)
    return meta


def observations_provenance(observations_path: Path) -> Optional[str]:
    """The frozen snapshot's ``content_sha256`` (sidecar first, else computed).

    Downstream artifacts call this to record exactly which observations snapshot
    they consumed. Returns ``None`` when no observations exist.
    """
    observations_path = Path(observations_path)
    meta = read_snapshot_meta(observations_path)
    if meta.get("content_sha256"):
        return str(meta["content_sha256"])
    if observations_path.exists():
        return observations_content_sha256(load_existing_observations(observations_path))
    return None


def _require_token(token: Optional[str]) -> str:
    """Return the API token (explicit arg wins, else env). Never printed."""
    if token:
        return token
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    env_token = os.getenv(ENV_KEY)
    if not env_token:
        raise RuntimeError(
            f"{ENV_KEY} not found in environment/.env — cannot run live collection. "
            "Use --dry-run to preview the cost without a key."
        )
    return env_token


# ─── Orchestration ───────────────────────────────────────────────────────────

def collect(
    artifact_path: Path = DEFAULT_ARTIFACT_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    *,
    top_n: int = DEFAULT_TOP_N,
    explore_n: int = DEFAULT_EXPLORE_N,
    seed: int = DEFAULT_SEED,
    budget: int = DEFAULT_BUDGET_CALLS,
    rupees_per_call: float = RUPEES_PER_CALL,
    dry_run: bool = False,
    refresh: bool = False,
    force: bool = False,
    poi_keywords: str = DEFAULT_POI_KEYWORDS,
    poi_radius: int = DEFAULT_POI_RADIUS,
    get_json: Optional[GetJson] = None,
    now_ist: Optional[datetime] = None,
    token: Optional[str] = None,
    sleep_between_apis: float = SLEEP_BETWEEN_APIS,
    sleep_between_zones: float = SLEEP_BETWEEN_ZONES,
    verbose: bool = True,
) -> dict:
    """Run the local-segment congestion collection (or preview it with ``dry_run``).

    Returns the full observations dict (also written to ``output_path`` unless
    ``dry_run``). Raises :class:`BudgetExceededError` when the estimated call
    count for the uncached zones exceeds ``budget``. Raises
    :class:`SnapshotFrozenError` when a frozen snapshot would be overwritten and
    ``force`` is False.
    """
    artifact = load_artifact(artifact_path)
    zones = select_zones(artifact, top_n=top_n, explore_n=explore_n, seed=seed)

    existing = {} if refresh else load_existing_observations(output_path)
    todo = [z for z in zones if z.zone_id not in existing]

    # Immutable snapshot guard: refuse to overwrite a frozen snapshot unless forced.
    if not dry_run and not force and todo and is_frozen(output_path):
        raise SnapshotFrozenError(
            f"{output_path} is a frozen snapshot (see {snapshot_meta_path(output_path).name}). "
            "Re-collecting would change a validated provenance hash. Pass --force to override."
        )

    est_calls = estimate_calls(len(todo))
    est_rupees = estimate_rupees(est_calls, rupees_per_call)

    now = now_ist or datetime.now(IST)
    ist_hour = now.astimezone(IST).hour
    measured_at = now.astimezone(IST).isoformat()

    if verbose:
        n_explore = sum(1 for z in zones if z.is_exploration)
        print(f"\n{'='*64}")
        print("🗺️  ParkVision-Saathi — Congestion Collector v2 (local-segment)")
        print(f"{'='*64}")
        print(f"   Artifact:   {artifact_path}")
        print(f"   Output:     {output_path}")
        print(f"   Selected:   {len(zones)} zones ({len(zones)-n_explore} core + {n_explore} exploration)")
        print(f"   Cached:     {len(zones) - len(todo)}  |  To collect: {len(todo)}")
        print(f"   Legs/zone:  {len(LEG_OFFSETS)} (~{TARGET_LEG_METRES:.0f} m N/E/S/W)")
        print(f"   Est. calls: {est_calls}  (budget {budget})")
        print(f"   Est. cost:  ₹{est_rupees:.2f}  @ ₹{rupees_per_call}/call  ⚠️ VERIFY plan price")
        print(f"   Total ₹ budget: ₹{TOTAL_RUPEE_BUDGET:.0f}")
        print(f"   IST hour:   {ist_hour:02d}:00  ({'PEAK ✅' if is_peak_ist(ist_hour) else 'OFF-PEAK ⚠️'})")
        if not is_peak_ist(ist_hour) and not dry_run:
            print(
                "   ⚠️  WARNING: running OUTSIDE a Bengaluru congestion window "
                "(~08:00-11:00 / 18:00-20:00 IST). Off-peak ratios trend to ~1.0 "
                "and will not calibrate the CIS meaningfully."
            )

    if est_calls > budget:
        raise BudgetExceededError(
            f"Estimated {est_calls} API calls (₹{est_rupees:.2f}) exceeds the budget "
            f"of {budget} calls. Lower --top-n/--explore-n or raise --budget."
        )

    if dry_run:
        if verbose:
            print("\n   --dry-run: no API calls made. Plan validated.\n")
        return existing

    active_get_json = get_json or _default_get_json
    auth = _require_token(token)

    results = dict(existing)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    skipped: list[tuple[str, str]] = []
    for i, zone in enumerate(todo, 1):
        if verbose:
            tag = "explore" if zone.is_exploration else "core"
            print(f"[{i:3d}/{len(todo)}] {zone.zone_id} ({tag}) vol={zone.total_records}")
        # Per-zone isolation: one bad zone (network blip, malformed response,
        # unexpected error) must NEVER abort the whole run. Log it, mark it
        # skipped, and continue — the snapshot still freezes with whatever was
        # collected. Already-collected zones stay cached (never re-billed).
        try:
            obs = measure_zone(
                zone,
                active_get_json,
                auth,
                measured_at=measured_at,
                poi_keywords=poi_keywords,
                poi_radius=poi_radius,
                sleep_between_apis=sleep_between_apis,
            )
            results[zone.zone_id] = obs
            # Save incrementally so a crash never loses (or re-bills) collected zones.
            with output_path.open("w", encoding="utf-8") as handle:
                json.dump(results, handle, indent=2, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 — one bad zone must not abort the run
            reason = f"{type(exc).__name__}: {exc}"
            skipped.append((zone.zone_id, reason))
            if verbose:
                print(f"      ⚠️  SKIPPED {zone.zone_id}: {reason}")
        if i < len(todo) and sleep_between_zones:
            time.sleep(sleep_between_zones)

    # Final consistent write so the file always reflects `results`, even if the
    # last zone was skipped or every zone failed (covers the empty-todo case too).
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, ensure_ascii=False)

    if verbose:
        measured = [r for r in results.values() if r.get("congestion_ratio") is not None]
        ratios = sorted(r["congestion_ratio"] for r in measured)
        print(f"\n{'='*64}")
        print(f"✅ Collected {len(results)} zones -> {output_path}")
        if skipped:
            print(f"   ⚠️  {len(skipped)} zone(s) skipped after errors: "
                  + ", ".join(zid for zid, _ in skipped))
        if ratios:
            print(f"   congestion_ratio  min={ratios[0]:.2f}  median={median(ratios):.2f}  max={ratios[-1]:.2f}")
        print(f"{'='*64}\n")

    # Freeze the snapshot: write the provenance meta sidecar (content hash).
    meta = write_snapshot_meta(output_path, results, measured_at)
    if verbose:
        print(f"   🔒 frozen snapshot — sha256 {meta['content_sha256'][:12]}… "
              f"({snapshot_meta_path(output_path).name})\n")

    return results


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MapMyIndia local-segment congestion collector v2")
    parser.add_argument("--artifact", default=str(DEFAULT_ARTIFACT_PATH), help="CIS artifact (zone universe)")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="congestion_observations.json output")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="top zones by violation volume")
    parser.add_argument("--explore-n", type=int, default=DEFAULT_EXPLORE_N, help="seeded random low-volume zones")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="exploration sampling seed")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET_CALLS, help="max API calls (refuse if exceeded)")
    parser.add_argument("--rupees-per-call", type=float, default=RUPEES_PER_CALL, help="₹ per call (⚠️ VERIFY)")
    parser.add_argument("--dry-run", action="store_true", help="print cost/plan, make no API calls")
    parser.add_argument("--refresh", action="store_true", help="ignore cache and re-collect every zone")
    parser.add_argument("--force", action="store_true", help="overwrite a frozen snapshot")
    args = parser.parse_args(argv)

    try:
        collect(
            artifact_path=Path(args.artifact),
            output_path=Path(args.output),
            top_n=args.top_n,
            explore_n=args.explore_n,
            seed=args.seed,
            budget=args.budget,
            rupees_per_call=args.rupees_per_call,
            dry_run=args.dry_run,
            refresh=args.refresh,
            force=args.force,
        )
    except BudgetExceededError as exc:
        print(f"\n❌ {exc}\n", file=sys.stderr)
        return 2
    except SnapshotFrozenError as exc:
        print(f"\n❌ {exc}\n", file=sys.stderr)
        return 3
    except RuntimeError as exc:
        print(f"\n❌ {exc}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
