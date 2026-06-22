"""
ParkVision-Saathi — CIS validation harness (Task 2)
====================================================

Quantifies how well the **current** Congestion Impact Score (a deterministic
weighted formula) agrees with the **measured** MapMyIndia congestion ratio from
the Task 1 collector. This is the baseline-trust artifact: it is produced
*before* any weights are changed (Task 3) so the "before" number is honest.

Method
------
Join, per zone (keyed by ``h3_id``):
  * CIS = the ``all_day`` ``congestion_impact`` from
    ``data/processed/zone_congestion_impact.json``;
  * measured = the ``congestion_ratio`` from
    ``data/enriched/congestion_observations.json`` (Task 1 output).

Then compute rank correlation (**Spearman**, primary) and linear correlation
(**Pearson**) between CIS and the measured ratio, reported on:
  * all measured zones,
  * the held-out **test** split (a deterministic 70/30 hash split on ``h3_id``),
  * the **exploration** subset (the seeded low-volume zones tagged by Task 1).

Determinism
-----------
The train/test split hashes ``f"{seed}:{h3_id}"`` with SHA-256 (stable across
processes, unlike Python's salted ``hash()``), so the split — and therefore every
reported correlation — is identical across runs for a fixed seed.

Honesty
-------
Correlations are reported as measured. With fewer than :data:`MIN_POINTS_FOR_CORR`
points a correlation is reported as ``null`` (a warning is logged) rather than a
misleading number; a constant input (no rank variation) is likewise ``null``.

Output: ``data/processed/cis_validation_report.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CIS_ARTIFACT_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact.json"
DEFAULT_OBSERVATIONS_PATH = PROJECT_ROOT / "data" / "enriched" / "congestion_observations.json"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "processed" / "cis_validation_report.json"

# ─── Constants ───────────────────────────────────────────────────────────────

DEFAULT_SPLIT_SEED = 1337
DEFAULT_TIME_BUCKET = "all_day"
TRAIN_FRACTION_PCT = 70  # 70% train / 30% test
MIN_POINTS_FOR_CORR = 5  # below this, correlations are reported as null


# ─── Deterministic split ─────────────────────────────────────────────────────

def deterministic_split(h3_id: str, seed: int = DEFAULT_SPLIT_SEED) -> str:
    """Assign a zone to ``"train"`` or ``"test"`` deterministically from its id.

    Hashes ``f"{seed}:{h3_id}"`` with SHA-256 and buckets the result into
    ``[0, 100)``; buckets ``< 70`` are train, the rest test. Stable across
    processes and runs (no salted ``hash()``), so the split never drifts.
    """
    digest = hashlib.sha256(f"{seed}:{h3_id}".encode("utf-8")).hexdigest()
    bucket = int(digest, 16) % 100
    return "train" if bucket < TRAIN_FRACTION_PCT else "test"


# ─── Correlation helpers (guarded) ───────────────────────────────────────────

def _is_constant(values: Sequence[float]) -> bool:
    return len(set(values)) <= 1


def spearman(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    """Spearman rank correlation, or ``None`` when undefined or under-powered.

    Returns ``None`` when there are fewer than :data:`MIN_POINTS_FOR_CORR` pairs
    or when either series is constant (rank correlation undefined). Otherwise the
    coefficient is rounded to 4 dp.
    """
    if len(x) != len(y):
        raise ValueError("x and y must be the same length")
    if len(x) < MIN_POINTS_FOR_CORR or _is_constant(x) or _is_constant(y):
        return None
    from scipy.stats import spearmanr

    rho, _ = spearmanr(x, y)
    if rho is None or (isinstance(rho, float) and rho != rho):  # NaN guard
        return None
    return round(float(rho), 4)


def pearson(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    """Pearson linear correlation, or ``None`` when undefined or under-powered."""
    if len(x) != len(y):
        raise ValueError("x and y must be the same length")
    if len(x) < MIN_POINTS_FOR_CORR or _is_constant(x) or _is_constant(y):
        return None
    from scipy.stats import pearsonr

    r, _ = pearsonr(x, y)
    if r is None or (isinstance(r, float) and r != r):
        return None
    return round(float(r), 4)


# ─── Join CIS with measured congestion ───────────────────────────────────────

def _all_day_cis(buckets: Mapping, time_bucket: str) -> Optional[float]:
    """Return the requested bucket's ``congestion_impact`` (or None)."""
    bd = buckets.get(time_bucket) if isinstance(buckets, Mapping) else None
    if not isinstance(bd, Mapping):
        return None
    value = bd.get("congestion_impact")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def join_points(
    cis_artifact: Mapping[str, Mapping],
    observations: Mapping[str, Mapping],
    *,
    seed: int = DEFAULT_SPLIT_SEED,
    time_bucket: str = DEFAULT_TIME_BUCKET,
) -> list[dict]:
    """Join CIS and measured congestion into per-zone points.

    One point per zone present in **both** the CIS artifact (with a usable
    ``congestion_impact`` in ``time_bucket``) and the observations (with a finite
    ``congestion_ratio``). Each point carries its deterministic split and the
    Task-1 ``is_exploration`` flag. Output is sorted by ``h3_id`` for stable JSON.
    """
    points: list[dict] = []
    for h3_id, obs in observations.items():
        if not isinstance(obs, Mapping):
            continue
        ratio = obs.get("congestion_ratio")
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
            continue
        if not (ratio == ratio) or ratio <= 0:  # NaN / non-positive
            continue
        cis = _all_day_cis(cis_artifact.get(h3_id, {}), time_bucket)
        if cis is None:
            continue
        points.append(
            {
                "h3_id": str(h3_id),
                "cis": round(cis, 4),
                "measured_ratio": round(float(ratio), 4),
                "is_exploration": bool(obs.get("is_exploration", False)),
                "split": deterministic_split(str(h3_id), seed),
            }
        )
    points.sort(key=lambda p: p["h3_id"])
    return points


# ─── Report ──────────────────────────────────────────────────────────────────

def build_report(
    cis_artifact: Mapping[str, Mapping],
    observations: Mapping[str, Mapping],
    *,
    seed: int = DEFAULT_SPLIT_SEED,
    time_bucket: str = DEFAULT_TIME_BUCKET,
    generated_at: Optional[str] = None,
) -> dict:
    """Build the validation report dict (no I/O)."""
    points = join_points(cis_artifact, observations, seed=seed, time_bucket=time_bucket)
    n = len(points)

    if n < MIN_POINTS_FOR_CORR:
        logger.warning(
            "Only %d measured zones joined (need >= %d for correlations); "
            "reporting null correlations.",
            n,
            MIN_POINTS_FOR_CORR,
        )

    def _corr(subset: list[dict], fn):
        xs = [p["cis"] for p in subset]
        ys = [p["measured_ratio"] for p in subset]
        return fn(xs, ys)

    test_points = [p for p in points if p["split"] == "test"]
    explore_points = [p for p in points if p["is_exploration"]]

    return {
        "n_measured": n,
        "n_test": len(test_points),
        "n_exploration": len(explore_points),
        "spearman_all": _corr(points, spearman),
        "pearson_all": _corr(points, pearson),
        "spearman_test": _corr(test_points, spearman),
        "spearman_exploration": _corr(explore_points, spearman),
        "split_seed": seed,
        "time_bucket": time_bucket,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "points": points,
    }


# ─── I/O ─────────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def run(
    cis_artifact_path: Path = DEFAULT_CIS_ARTIFACT_PATH,
    observations_path: Path = DEFAULT_OBSERVATIONS_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    *,
    seed: int = DEFAULT_SPLIT_SEED,
    time_bucket: str = DEFAULT_TIME_BUCKET,
    generated_at: Optional[str] = None,
    verbose: bool = True,
) -> dict:
    """Read inputs, build the report, write it, and print the summary line."""
    cis_artifact = _load_json(Path(cis_artifact_path))
    observations = (
        _load_json(Path(observations_path)) if Path(observations_path).exists() else {}
    )
    if not observations:
        logger.warning(
            "No congestion observations at %s — run the Task 1 collector first. "
            "Report will have n_measured=0.",
            observations_path,
        )

    report = build_report(
        cis_artifact, observations, seed=seed, time_bucket=time_bucket,
        generated_at=generated_at,
    )

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    if verbose:
        rho = report["spearman_all"]
        rho_test = report["spearman_test"]
        rho_str = f"{rho:.3f}" if rho is not None else "n/a"
        test_str = f"{rho_test:.3f}" if rho_test is not None else "n/a"
        print(
            f"Current CIS vs measured congestion: Spearman ρ={rho_str} "
            f"on {report['n_measured']} zones (test ρ={test_str})"
        )
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CIS validation harness (Task 2)")
    parser.add_argument("--cis", default=str(DEFAULT_CIS_ARTIFACT_PATH))
    parser.add_argument("--observations", default=str(DEFAULT_OBSERVATIONS_PATH))
    parser.add_argument("--out", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--seed", type=int, default=DEFAULT_SPLIT_SEED)
    parser.add_argument("--time-bucket", default=DEFAULT_TIME_BUCKET)
    args = parser.parse_args(argv)

    run(
        cis_artifact_path=Path(args.cis),
        observations_path=Path(args.observations),
        report_path=Path(args.out),
        seed=args.seed,
        time_bucket=args.time_bucket,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
