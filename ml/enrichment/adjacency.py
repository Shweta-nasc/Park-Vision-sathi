"""
ParkVision-Saathi — MapMyIndia driving-time zone adjacency (Task 8)
====================================================================

Builds a *road-connected* neighbor graph for the top-N hotspot zones using
MapMyIndia Distance Matrix driving times — so the forecast's spatial lag uses
real road adjacency, not straight-line distance.

Efficiency / budget
-------------------
A full N×N matrix is wasteful for a k-NN graph. Instead, for each zone we
haversine-prefilter the nearest ``MAX_CANDIDATES`` zones (free, no API), then make
ONE distance-matrix call over ``[zone] + candidates`` and read the zone→candidate
driving-time row, keeping the ``k`` smallest as road-connected neighbors. That is
one matrix call per zone (each ≤ ``MAX_CANDIDATES + 1`` points, well under
``MAX_MATRIX_SIZE``). The collector refuses to run when the estimate exceeds the
``--budget`` call cap.

``⚠️ VERIFY`` the live plan's maximum matrix size per call before raising
``MAX_CANDIDATES``; the conservative default keeps every call small.

Output: ``data/enriched/zone_adjacency.json`` ::

    {"k": 6, "n_zones": N, "method": "mapmyindia_distance_matrix_knn",
     "zones": {h3_id: {"neighbors": [h3, ...], "driving_times_s": [..]}}, ...}
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Mapping, Optional, Sequence

from ml.enrichment.congestion_collector import (
    DM_BASE,
    RUPEES_PER_CALL,
    BudgetExceededError,
    GetJson,
    _default_get_json,
    _require_token,
    estimate_rupees,
    haversine_m,
)

# ─── Paths ───────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ARTIFACT_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "enriched" / "zone_adjacency.json"

# ─── Constants ───────────────────────────────────────────────────────────────

K_NEIGHBORS = 6
MAX_CANDIDATES = 12          # haversine prefilter size per zone (<= MAX_MATRIX_SIZE - 1)
MAX_MATRIX_SIZE = 50         # ⚠️ VERIFY against the live plan's per-call matrix cap
DEFAULT_TOP_N = 60           # operational hotspot universe (matches HOTSPOT_UNIVERSE_SIZE)
DEFAULT_BUDGET_CALLS = 200   # one matrix call per zone + headroom
SLEEP_BETWEEN_CALLS = 0.3
METHOD_TAG = "mapmyindia_distance_matrix_knn"


def estimate_adjacency_calls(n_zones: int) -> int:
    """One distance-matrix call per zone (zone -> its candidate set)."""
    return int(n_zones)


# ─── Zone selection ──────────────────────────────────────────────────────────

def select_zones(
    artifact: Mapping[str, Mapping],
    *,
    top_n: int = DEFAULT_TOP_N,
    time_bucket: str = "all_day",
) -> list[tuple[str, float, float]]:
    """Top-``top_n`` zones by violation volume -> ``[(h3_id, lat, lon), ...]``."""
    rows: list[tuple[str, float, float, int]] = []
    for h3_id, buckets in artifact.items():
        if h3_id.startswith("_") or not isinstance(buckets, Mapping):
            continue
        bd = buckets.get(time_bucket) or buckets.get("all_day")
        if not isinstance(bd, Mapping):
            continue
        lat, lon = bd.get("lat"), bd.get("lon")
        if lat is None or lon is None:
            continue
        vol = int(bd.get("total_records") or 0)
        rows.append((str(h3_id), float(lat), float(lon), vol))
    rows.sort(key=lambda r: (-r[3], r[0]))
    if top_n and top_n > 0:
        rows = rows[:top_n]
    return [(h3, lat, lon) for h3, lat, lon, _ in rows]


def candidate_indices(zones: Sequence[tuple[str, float, float]], i: int, max_candidates: int) -> list[int]:
    """Indices of the ``max_candidates`` nearest zones to zone ``i`` by haversine."""
    _, lat_i, lon_i = zones[i]
    dists = [
        (j, haversine_m(lat_i, lon_i, zones[j][1], zones[j][2]))
        for j in range(len(zones)) if j != i
    ]
    dists.sort(key=lambda t: (t[1], zones[t[0]][0]))
    return [j for j, _ in dists[:max_candidates]]


# ─── Distance-matrix row ─────────────────────────────────────────────────────

def parse_matrix_row(data: Optional[Mapping]) -> Optional[list[float]]:
    """Return ``results.durations[0]`` (the src->all row) or ``None``."""
    if not data:
        return None
    results = data.get("results", {})
    if not isinstance(results, Mapping) or results.get("code") != "Ok":
        return None
    durations = results.get("durations")
    if not isinstance(durations, Sequence) or not durations:
        return None
    row = durations[0]
    if not isinstance(row, Sequence):
        return None
    out: list[float] = []
    for v in row:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(float("inf"))
    return out


def query_driving_times(
    get_json: GetJson,
    token: str,
    src: tuple[float, float],
    dests: Sequence[tuple[float, float]],
    resource: str = "distance_matrix",
) -> Optional[list[float]]:
    """Driving times (s) from ``src`` to each ``dest`` via one matrix call.

    Coordinates are sent as ``lon,lat`` per the Mappls spec; the response matrix's
    first row is ``src -> [src, *dests]``, so its tail (index 1..) is returned.
    """
    points = [src, *dests]
    coords = ";".join(f"{lon},{lat}" for (lat, lon) in points)
    url = f"{DM_BASE}/{resource}/driving/{coords}"
    params = {"access_token": token, "rtype": 0, "region": "ind"}
    row = parse_matrix_row(get_json(url, params, "distance_matrix"))
    if row is None or len(row) < len(points):
        return None
    return row[1:1 + len(dests)]


# ─── Build ───────────────────────────────────────────────────────────────────

def build_adjacency(
    zones: Sequence[tuple[str, float, float]],
    get_json: GetJson,
    token: str,
    *,
    k: int = K_NEIGHBORS,
    max_candidates: int = MAX_CANDIDATES,
    sleep_between_calls: float = 0.0,
) -> dict[str, dict]:
    """Build the driving-time k-NN adjacency map for ``zones``."""
    if max_candidates + 1 > MAX_MATRIX_SIZE:
        raise ValueError(
            f"max_candidates+1 ({max_candidates + 1}) exceeds MAX_MATRIX_SIZE "
            f"({MAX_MATRIX_SIZE}); lower max_candidates or chunk the request."
        )
    out: dict[str, dict] = {}
    for i, (h3_id, lat, lon) in enumerate(zones):
        cand = candidate_indices(zones, i, max_candidates)
        if not cand:
            out[h3_id] = {"neighbors": [], "driving_times_s": []}
            continue
        dests = [(zones[j][1], zones[j][2]) for j in cand]
        times = query_driving_times(get_json, token, (lat, lon), dests)
        if times is None:
            # API failure for this zone: leave it with no neighbors (graceful).
            out[h3_id] = {"neighbors": [], "driving_times_s": []}
        else:
            paired = sorted(
                ((zones[j][0], t) for j, t in zip(cand, times)),
                key=lambda p: (p[1], p[0]),
            )[:k]
            out[h3_id] = {
                "neighbors": [nid for nid, _ in paired],
                "driving_times_s": [round(t, 1) for _, t in paired],
            }
        if sleep_between_calls:
            time.sleep(sleep_between_calls)
    return out


def neighbor_map(adjacency_report: Mapping) -> dict[str, list[str]]:
    """Flatten a report to ``{h3_id: [neighbor_h3, ...]}`` (the forecast consumer)."""
    zones = adjacency_report.get("zones", adjacency_report)
    out: dict[str, list[str]] = {}
    for h3_id, entry in zones.items():
        if h3_id.startswith("_"):
            continue
        if isinstance(entry, Mapping) and isinstance(entry.get("neighbors"), list):
            out[str(h3_id)] = [str(n) for n in entry["neighbors"]]
    return out


# ─── Runner ──────────────────────────────────────────────────────────────────

def collect(
    artifact_path: Path = DEFAULT_ARTIFACT_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    *,
    top_n: int = DEFAULT_TOP_N,
    k: int = K_NEIGHBORS,
    max_candidates: int = MAX_CANDIDATES,
    budget: int = DEFAULT_BUDGET_CALLS,
    rupees_per_call: float = RUPEES_PER_CALL,
    dry_run: bool = False,
    get_json: Optional[GetJson] = None,
    token: Optional[str] = None,
    sleep_between_calls: float = SLEEP_BETWEEN_CALLS,
    verbose: bool = True,
) -> dict:
    """Select zones, build the adjacency graph (budget-capped), write JSON."""
    with Path(artifact_path).open("r", encoding="utf-8") as handle:
        artifact = json.load(handle)
    zones = select_zones(artifact, top_n=top_n)

    est_calls = estimate_adjacency_calls(len(zones))
    est_rupees = estimate_rupees(est_calls, rupees_per_call)
    if verbose:
        print(f"\n🛣️  Zone adjacency (k={k}) over {len(zones)} zones")
        print(f"   Est. calls: {est_calls} (budget {budget}) | Est. cost ₹{est_rupees:.2f} "
              f"@ ₹{rupees_per_call}/call ⚠️ VERIFY")
    if est_calls > budget:
        raise BudgetExceededError(
            f"Estimated {est_calls} matrix calls exceeds budget {budget}. "
            f"Lower --top-n or raise --budget."
        )
    if dry_run:
        if verbose:
            print("   --dry-run: no API calls made.\n")
        return {"k": k, "n_zones": len(zones), "method": METHOD_TAG, "zones": {}, "_dry_run": True}

    active_get_json = get_json or _default_get_json
    auth = _require_token(token)
    adjacency = build_adjacency(
        zones, active_get_json, auth, k=k, max_candidates=max_candidates,
        sleep_between_calls=sleep_between_calls,
    )
    report = {
        "k": k,
        "n_zones": len(zones),
        "top_n": top_n,
        "method": METHOD_TAG,
        "source": "mapmyindia",
        "zones": adjacency,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    if verbose:
        avg = sum(len(z["neighbors"]) for z in adjacency.values()) / max(len(adjacency), 1)
        print(f"   ✅ wrote {output_path}: {len(adjacency)} zones, avg {avg:.1f} neighbors\n")
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MapMyIndia driving-time zone adjacency (Task 8)")
    parser.add_argument("--artifact", default=str(DEFAULT_ARTIFACT_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--k", type=int, default=K_NEIGHBORS)
    parser.add_argument("--max-candidates", type=int, default=MAX_CANDIDATES)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET_CALLS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        collect(
            artifact_path=Path(args.artifact), output_path=Path(args.output),
            top_n=args.top_n, k=args.k, max_candidates=args.max_candidates,
            budget=args.budget, dry_run=args.dry_run,
        )
    except BudgetExceededError as exc:
        print(f"\n❌ {exc}\n", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"\n❌ {exc}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
