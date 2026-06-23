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

from ml.congestion.impact_score import WEIGHTS
from ml.congestion.stats_utils import bootstrap_spearman_ci, content_sha256

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CIS_ARTIFACT_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact.json"
DEFAULT_OBSERVATIONS_PATH = PROJECT_ROOT / "data" / "enriched" / "congestion_observations.json"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "processed" / "cis_validation_report.json"
DEFAULT_CALIBRATION_PATH = PROJECT_ROOT / "data" / "processed" / "cis_calibration.json"

# ─── Constants ───────────────────────────────────────────────────────────────

DEFAULT_SPLIT_SEED = 1337
DEFAULT_TIME_BUCKET = "all_day"
TRAIN_FRACTION_PCT = 70  # 70% train / 30% test
MIN_POINTS_FOR_CORR = 5  # below this, correlations are reported as null

# The four violation/road-derived components — the ONLY inputs to the honest
# (non-circular) CIS predictor. traffic_degradation is EXCLUDED because it is
# derived from the measured ratio we validate against (using it would inflate the
# correlation by construction).
NON_TRAFFIC_COMPONENTS = ("lane_blockage", "intersection_impact", "access_blockage", "vehicle_size")
TRAFFIC_COMPONENT = "traffic_degradation"


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


# ─── Honest (non-circular) predictor weights ─────────────────────────────────

def honest_weights(calibration_report: Optional[Mapping] = None) -> dict[str, float]:
    """The four non-traffic component weights, renormalized to sum to 1.

    Uses the Task 3 calibrated ``new_weights`` when available, else the expert
    :data:`WEIGHTS`; in both cases it takes ONLY the four
    :data:`NON_TRAFFIC_COMPONENTS` and renormalizes them. The result provably
    **excludes** ``traffic_degradation`` — that exclusion is what makes the honest
    trust metric non-circular.
    """
    src: Mapping[str, float] = WEIGHTS
    if isinstance(calibration_report, Mapping):
        nw = calibration_report.get("new_weights")
        if isinstance(nw, Mapping):
            src = nw

    raw = {c: float(src.get(c, 0.0)) for c in NON_TRAFFIC_COMPONENTS}
    total = sum(raw.values())
    if total <= 0:
        w = {c: 1.0 / len(NON_TRAFFIC_COMPONENTS) for c in NON_TRAFFIC_COMPONENTS}
    else:
        w = {c: v / total for c, v in raw.items()}

    # Airtight anti-circularity invariants.
    assert TRAFFIC_COMPONENT not in w, "honest weights must EXCLUDE traffic_degradation"
    assert tuple(w.keys()) == NON_TRAFFIC_COMPONENTS, "honest weights must be exactly the 4 non-traffic components"
    assert abs(sum(w.values()) - 1.0) < 1e-9
    return w


# ─── Join CIS with measured congestion ───────────────────────────────────────

def _bucket(buckets: Mapping, time_bucket: str) -> Optional[Mapping]:
    """Return the requested bucket breakdown, falling back to ``all_day``."""
    if not isinstance(buckets, Mapping):
        return None
    bd = buckets.get(time_bucket)
    if not isinstance(bd, Mapping):
        bd = buckets.get(DEFAULT_TIME_BUCKET)
    return bd if isinstance(bd, Mapping) else None


def _all_day_cis(buckets: Mapping, time_bucket: str) -> Optional[float]:
    """Return the requested bucket's ``congestion_impact`` (or None)."""
    bd = _bucket(buckets, time_bucket)
    if bd is None:
        return None
    value = bd.get("congestion_impact")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _components_4(bd: Mapping) -> Optional[list[float]]:
    """Extract the 4 non-traffic component values from a bucket, or None."""
    comps = bd.get("components") if isinstance(bd, Mapping) else None
    if not isinstance(comps, Mapping):
        return None
    try:
        return [float(comps[c]) for c in NON_TRAFFIC_COMPONENTS]
    except (KeyError, TypeError, ValueError):
        return None


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
    ``congestion_ratio``). Each point carries its deterministic split, the Task-1
    ``is_exploration`` flag, the raw violation ``count`` (``total_records``), and
    — when the artifact carries components — the private ``_components4`` vector
    used to compute the honest predictor. Output is sorted by ``h3_id``.
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
        bd = _bucket(cis_artifact.get(h3_id, {}), time_bucket)
        if bd is None:
            continue
        cis = bd.get("congestion_impact")
        if isinstance(cis, bool) or not isinstance(cis, (int, float)):
            continue
        count = bd.get("total_records")
        count = int(count) if isinstance(count, (int, float)) and not isinstance(count, bool) else 0
        points.append(
            {
                "h3_id": str(h3_id),
                "cis": round(float(cis), 4),
                "count": count,
                "measured_ratio": round(float(ratio), 4),
                "is_exploration": bool(obs.get("is_exploration", False)),
                "split": deterministic_split(str(h3_id), seed),
                "_components4": _components_4(bd),
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
    calibration_report: Optional[Mapping] = None,
    generated_at: Optional[str] = None,
) -> dict:
    """Build the validation report dict (no I/O).

    Adds the density≠impact proof (Task 10): on the held-out **test** split, the
    three Spearman correlations vs the measured ratio — raw violation count (the
    baseline), the full CIS (flagged *circular*: it contains the measured ratio),
    and the **honest** CIS (the four non-traffic components only, calibrated
    weights renormalized — never the measured ratio). Each carries a bootstrap CI.
    """
    points = join_points(cis_artifact, observations, seed=seed, time_bucket=time_bucket)
    n = len(points)

    if n < MIN_POINTS_FOR_CORR:
        logger.warning(
            "Only %d measured zones joined (need >= %d for correlations); "
            "reporting null correlations.",
            n,
            MIN_POINTS_FOR_CORR,
        )

    # Honest predictor: weighted sum of the FOUR non-traffic components only.
    hw = honest_weights(calibration_report)
    for p in points:
        c4 = p.pop("_components4", None)
        if c4 is not None and len(c4) == len(NON_TRAFFIC_COMPONENTS):
            p["cis_honest"] = round(
                sum(hw[c] * v for c, v in zip(NON_TRAFFIC_COMPONENTS, c4)), 6
            )
        else:
            p["cis_honest"] = None

    def _corr(subset: list[dict], key: str, fn):
        xs = [p[key] for p in subset]
        ys = [p["measured_ratio"] for p in subset]
        return fn(xs, ys)

    test_points = [p for p in points if p["split"] == "test"]
    explore_points = [p for p in points if p["is_exploration"]]

    # Density≠impact head-to-head: all three correlations on the SAME test-split
    # subset (zones that carry components so the honest metric is defined).
    proof = [p for p in test_points if p["cis_honest"] is not None]
    proof_ys = [p["measured_ratio"] for p in proof]
    proof_counts = [p["count"] for p in proof]
    proof_full = [p["cis"] for p in proof]
    proof_honest = [p["cis_honest"] for p in proof]

    spearman_count_test = spearman(proof_counts, proof_ys)
    spearman_cis_full_test = spearman(proof_full, proof_ys)
    spearman_cis_honest_test = spearman(proof_honest, proof_ys)
    baseline_beaten = (
        spearman_cis_honest_test is not None
        and spearman_count_test is not None
        and spearman_cis_honest_test > spearman_count_test
    )

    obs_sha = content_sha256(dict(observations)) if observations else None

    return {
        "n_measured": n,
        "n_test": len(test_points),
        "n_exploration": len(explore_points),
        "n_proof": len(proof),
        "spearman_all": _corr(points, "cis", spearman),
        "spearman_all_ci": _corr(points, "cis", bootstrap_spearman_ci),
        "pearson_all": _corr(points, "cis", pearson),
        "spearman_test": _corr(test_points, "cis", spearman),
        "spearman_test_ci": _corr(test_points, "cis", bootstrap_spearman_ci),
        "spearman_exploration": _corr(explore_points, "cis", spearman),
        # ── density ≠ impact proof (Task 10) ──
        "spearman_count_test": spearman_count_test,
        "spearman_count_test_ci": bootstrap_spearman_ci(proof_counts, proof_ys),
        "spearman_cis_full_test": spearman_cis_full_test,
        "spearman_cis_full_test_ci": bootstrap_spearman_ci(proof_full, proof_ys),
        "cis_full_note": "circular / upper bound — contains the measured ratio (traffic_degradation)",
        "spearman_cis_honest_test": spearman_cis_honest_test,
        "spearman_cis_honest_test_ci": bootstrap_spearman_ci(proof_honest, proof_ys),
        "honest_weights": hw,
        "honest_excludes": TRAFFIC_COMPONENT,
        "baseline_beaten": bool(baseline_beaten),
        "split_seed": seed,
        "time_bucket": time_bucket,
        "observations_sha256": obs_sha,
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
    calibration_path: Optional[Path] = DEFAULT_CALIBRATION_PATH,
    generated_at: Optional[str] = None,
    verbose: bool = True,
) -> dict:
    """Read inputs, build the report, write it, and print the summary lines."""
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
    calibration_report = (
        _load_json(Path(calibration_path))
        if calibration_path and Path(calibration_path).exists()
        else None
    )

    report = build_report(
        cis_artifact, observations, seed=seed, time_bucket=time_bucket,
        calibration_report=calibration_report, generated_at=generated_at,
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
        print(_honest_trust_line(report))
    return report


def _fmt_rho_ci(rho: Optional[float], ci: Optional[Mapping]) -> str:
    """Format ``ρ=X [lo, hi]`` (CI omitted when unavailable)."""
    if rho is None:
        return "ρ=n/a"
    s = f"ρ={rho:.3f}"
    if isinstance(ci, Mapping) and ci.get("lo") is not None and ci.get("hi") is not None:
        s += f" [{ci['lo']:.3f}, {ci['hi']:.3f}]"
    return s


def _honest_trust_line(report: Mapping) -> str:
    """The density≠impact acceptance line."""
    honest = _fmt_rho_ci(report.get("spearman_cis_honest_test"), report.get("spearman_cis_honest_test_ci"))
    count = _fmt_rho_ci(report.get("spearman_count_test"), report.get("spearman_count_test_ci"))
    verdict = "PROVEN" if report.get("baseline_beaten") else "NOT"
    return (
        f"Honest trust: CIS(non-traffic) {honest} vs raw-count {count} "
        f"on {report.get('n_proof', 0)} zones — density!=impact: {verdict}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CIS validation harness (Task 2)")
    parser.add_argument("--cis", default=str(DEFAULT_CIS_ARTIFACT_PATH))
    parser.add_argument("--observations", default=str(DEFAULT_OBSERVATIONS_PATH))
    parser.add_argument("--out", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--calibration", default=str(DEFAULT_CALIBRATION_PATH))
    parser.add_argument("--seed", type=int, default=DEFAULT_SPLIT_SEED)
    parser.add_argument("--time-bucket", default=DEFAULT_TIME_BUCKET)
    args = parser.parse_args(argv)

    run(
        cis_artifact_path=Path(args.cis),
        observations_path=Path(args.observations),
        report_path=Path(args.out),
        calibration_path=Path(args.calibration),
        seed=args.seed,
        time_bucket=args.time_bucket,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
