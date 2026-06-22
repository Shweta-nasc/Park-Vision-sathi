"""
ParkVision-Saathi — before/after enforcement throughput simulation (Task 7)
============================================================================

The "put traffic on the map" payoff: how much does shifting patrol teams to the
highest-impact zones reduce modeled city congestion? This is the demo moment that
answers the theme's *"quantify impact on traffic flow"* with a city-level
throughput number, grounded in the **calibrated** Congestion Impact Score.

Transparent model (every constant documented in :data:`CONSTANTS`)
------------------------------------------------------------------
City congestion index over the operational hotspot universe::

    C = Σ_zone (CIS_zone / 100) · w_zone          # w_zone = 1.0 by default

Patrolling concentrates on the highest-impact zones via the same Stackelberg
mixed strategy used everywhere else — single-team probability ``p_zone ∝
CIS_zone^PATROL_ALPHA`` (normalized to sum 1). With ``n`` independent teams the
expected probability a zone is covered by at least one team is::

    coverage_n(zone) = 1 − (1 − p_zone)^n         # = p_zone at n = 1

Enforcement removes a documented fraction of a covered zone's blockage::

    reduction(zone) = ENFORCEMENT_EFFECTIVENESS · coverage_n(zone)
    CIS_after(zone) = CIS_zone · (1 − reduction(zone))

``C_before`` is the no-enforcement index; ``C_after`` uses ``CIS_after``. The
reported ``modeled_minutes_saved`` multiplies the index drop by a documented,
**illustrative** conversion factor — it is labeled a *modeled estimate under
stated assumptions*, never presented as a measured value.

Honesty
-------
* No fabricated precision: ``modeled_minutes_saved`` is explicitly illustrative.
* Monotonic by construction: more teams never reduce the modeled improvement
  (``coverage_n`` is non-decreasing in ``n``).
* Deterministic / offline: no randomness, network, or database.

Output: ``data/processed/throughput_sim.json``.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CIS_V1_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact.json"
CIS_V2_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact_v2.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "throughput_sim.json"

# ─── Documented model constants ──────────────────────────────────────────────
#
# Every number that shapes the modeled output lives here so a judge (or the team)
# can audit and defend the assumptions. None of these are measured quantities.

ENFORCEMENT_EFFECTIVENESS = 0.6   # fraction of a fully-covered zone's blockage removed
PATROL_ALPHA = 1.5                # Stackelberg emphasis (matches data_loader.PATROL_ALPHA)
MAX_TEAMS = 20                    # team-count sweep upper bound
DEFAULT_TOP_N = 60                # operational hotspot universe (matches HOTSPOT_UNIVERSE_SIZE)
# Illustrative conversion: modeled vehicle-minutes saved per 1.0 drop in the
# city congestion index C. A unit of C ≈ one zone fully congested (CIS=100), so
# this is "minutes of delay relieved when one such zone is fully cleared". It is a
# STATED ASSUMPTION for storytelling, not a measured calibration.
MINUTES_PER_INDEX_UNIT = 45.0

CONSTANTS: dict = {
    "enforcement_effectiveness": ENFORCEMENT_EFFECTIVENESS,
    "patrol_alpha": PATROL_ALPHA,
    "max_teams": MAX_TEAMS,
    "top_n": DEFAULT_TOP_N,
    "minutes_per_index_unit": MINUTES_PER_INDEX_UNIT,
    "coverage_model": "1 - (1 - p_zone)^n  (>=1 of n i.i.d. Stackelberg teams)",
    "weight_model": "w_zone = 1.0 (uniform); C = sum(CIS/100 * w_zone)",
    "disclaimer": (
        "modeled_minutes_saved is an illustrative modeled estimate under the "
        "stated assumptions above, NOT a measured value."
    ),
}

DEFAULT_TIME_BUCKET = "all_day"


# ─── Pure model ──────────────────────────────────────────────────────────────

def stackelberg_probabilities(cis_values: Sequence[float], alpha: float = PATROL_ALPHA) -> list[float]:
    """Single-team patrol probabilities ``∝ CIS^alpha`` normalized to sum to 1.

    Guarded: when every CIS is 0 (or the list is empty) all probabilities are 0.0
    (no division by zero), matching ``DataStore.congestion_patrol_probabilities``.
    """
    weights = [max(float(c), 0.0) ** alpha for c in cis_values]
    total = sum(weights)
    if total <= 0:
        return [0.0 for _ in weights]
    return [w / total for w in weights]


def zone_coverage_probability(p_zone: float, n_teams: int) -> float:
    """Expected probability a zone is covered by ≥1 of ``n_teams`` i.i.d. teams."""
    p = min(max(p_zone, 0.0), 1.0)
    return 1.0 - (1.0 - p) ** max(int(n_teams), 0)


def congestion_index(cis_values: Sequence[float], weights: Optional[Sequence[float]] = None) -> float:
    """City congestion index ``C = Σ (CIS/100) · w`` (uniform ``w = 1`` by default)."""
    if weights is None:
        weights = [1.0] * len(cis_values)
    return float(sum((float(c) / 100.0) * float(w) for c, w in zip(cis_values, weights)))


def simulate_throughput(
    cis_values: Sequence[float],
    *,
    max_teams: int = MAX_TEAMS,
    effectiveness: float = ENFORCEMENT_EFFECTIVENESS,
    alpha: float = PATROL_ALPHA,
    minutes_per_index_unit: float = MINUTES_PER_INDEX_UNIT,
    zone_weights: Optional[Sequence[float]] = None,
    generated_at: Optional[str] = None,
) -> dict:
    """Compute the before/after congestion index across 1..max_teams (pure).

    Returns ``{constants, n_zones, congestion_index_before, teams: {n: {...}},
    generated_at}`` where each team entry carries ``congestion_index_before``,
    ``congestion_index_after``, ``pct_reduction``, and ``modeled_minutes_saved``.
    """
    cis_values = [float(c) for c in cis_values]
    n_zones = len(cis_values)
    weights = list(zone_weights) if zone_weights is not None else [1.0] * n_zones

    c_before = congestion_index(cis_values, weights)
    probs = stackelberg_probabilities(cis_values, alpha=alpha)

    teams: dict[str, dict] = {}
    for n in range(1, max_teams + 1):
        cis_after = [
            cis * (1.0 - effectiveness * zone_coverage_probability(p, n))
            for cis, p in zip(cis_values, probs)
        ]
        c_after = congestion_index(cis_after, weights)
        delta = c_before - c_after
        pct_reduction = (delta / c_before * 100.0) if c_before > 0 else 0.0
        teams[str(n)] = {
            "num_teams": n,
            "congestion_index_before": round(c_before, 4),
            "congestion_index_after": round(c_after, 4),
            "pct_reduction": round(pct_reduction, 2),
            "modeled_minutes_saved": round(delta * minutes_per_index_unit, 1),
        }

    constants = dict(CONSTANTS)
    constants.update({
        "enforcement_effectiveness": effectiveness,
        "patrol_alpha": alpha,
        "max_teams": max_teams,
        "minutes_per_index_unit": minutes_per_index_unit,
    })

    return {
        "constants": constants,
        "n_zones": n_zones,
        "congestion_index_before": round(c_before, 4),
        "teams": teams,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
    }


# ─── Artifact loading / selection ────────────────────────────────────────────

def _resolve_cis_path() -> Path:
    """Prefer the calibrated v2 artifact, fall back to v1 (additive-shadow)."""
    return CIS_V2_PATH if CIS_V2_PATH.exists() else CIS_V1_PATH


def select_top_cis(
    artifact: Mapping[str, Mapping],
    *,
    top_n: int = DEFAULT_TOP_N,
    time_bucket: str = DEFAULT_TIME_BUCKET,
) -> list[float]:
    """Return the top-``top_n`` zones' calibrated CIS (descending), pure values.

    Uses each zone's ``all_day`` (or requested) bucket ``congestion_impact``. Ties
    broken by ``h3_id`` for determinism. Reserved ``_``-prefixed keys are ignored.
    """
    rows: list[tuple[str, float]] = []
    for h3_id, buckets in artifact.items():
        if h3_id.startswith("_") or not isinstance(buckets, Mapping):
            continue
        bd = buckets.get(time_bucket) or buckets.get("all_day")
        if not isinstance(bd, Mapping):
            continue
        cis = bd.get("congestion_impact")
        if isinstance(cis, bool) or not isinstance(cis, (int, float)):
            continue
        rows.append((str(h3_id), float(cis)))
    rows.sort(key=lambda r: (-r[1], r[0]))
    if top_n and top_n > 0:
        rows = rows[:top_n]
    return [cis for _, cis in rows]


# ─── Runner ──────────────────────────────────────────────────────────────────

def run(
    cis_artifact_path: Optional[Path] = None,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    *,
    top_n: int = DEFAULT_TOP_N,
    max_teams: int = MAX_TEAMS,
    time_bucket: str = DEFAULT_TIME_BUCKET,
    generated_at: Optional[str] = None,
    verbose: bool = True,
) -> dict:
    """Load the CIS artifact, select the top-N hotspots, simulate, write JSON."""
    cis_path = Path(cis_artifact_path) if cis_artifact_path else _resolve_cis_path()
    with cis_path.open("r", encoding="utf-8") as handle:
        artifact = json.load(handle)

    cis_values = select_top_cis(artifact, top_n=top_n, time_bucket=time_bucket)
    result = simulate_throughput(
        cis_values, max_teams=max_teams, generated_at=generated_at,
    )
    result["cis_artifact"] = cis_path.name
    result["top_n"] = top_n

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)

    if verbose and result["teams"]:
        peak = result["teams"][str(max_teams)]
        print(
            f"Throughput sim ({cis_path.name}, top {top_n} zones): shifting "
            f"{max_teams} teams cuts modeled congestion by {peak['pct_reduction']}% "
            f"(~{peak['modeled_minutes_saved']} modeled min saved). "
            f"[illustrative modeled estimate]"
        )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Before/after throughput simulation (Task 7)")
    parser.add_argument("--cis", default=None, help="CIS artifact path (defaults to v2 else v1)")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--max-teams", type=int, default=MAX_TEAMS)
    parser.add_argument("--time-bucket", default=DEFAULT_TIME_BUCKET)
    args = parser.parse_args(argv)

    run(
        cis_artifact_path=Path(args.cis) if args.cis else None,
        output_path=Path(args.out),
        top_n=args.top_n,
        max_teams=args.max_teams,
        time_bucket=args.time_bucket,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
