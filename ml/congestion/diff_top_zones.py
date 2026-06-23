"""
ParkVision-Saathi — v1 ↔ v2 top-zone diff (Task 14)
====================================================

A small, deterministic, offline utility that compares the **uncalibrated v1** and
**calibrated v2** Congestion Impact Score artifacts and reports how the headline
top-N ranking changed: which zones the calibration **added** to the top list,
which it **dropped**, and how zones that stayed in the list **moved** in rank.

This makes the calibration's effect legible — "after calibrating the weights
against real MapMyIndia congestion, these N zones entered the critical list and
these N left" — without anyone re-deriving it by hand.

Pure ranking + set arithmetic on the two ``{h3_id: {time_bucket: breakdown}}``
artifacts (the ``all_day`` ``congestion_impact`` by default). Reserved
``_``-prefixed keys (defensive; the artifacts are pure) are ignored. No network,
no database; ranking ties are broken by ``h3_id`` so the diff is reproducible.

Output: ``data/processed/cis_top_zone_diff.json`` (only from real v1/v2 artifacts;
never committed from synthetic fixtures).
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_V1_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact.json"
DEFAULT_V2_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact_v2.json"
DEFAULT_OUT_PATH = PROJECT_ROOT / "data" / "processed" / "cis_top_zone_diff.json"

DEFAULT_TIME_BUCKET = "all_day"
DEFAULT_TOP_N = 15


def _cis_for(buckets: Mapping, time_bucket: str) -> Optional[float]:
    """A zone's ``congestion_impact`` for ``time_bucket`` (``all_day`` fallback)."""
    if not isinstance(buckets, Mapping):
        return None
    bd = buckets.get(time_bucket)
    if not isinstance(bd, Mapping):
        bd = buckets.get(DEFAULT_TIME_BUCKET)
    if not isinstance(bd, Mapping):
        return None
    value = bd.get("congestion_impact")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def rank_zones(
    artifact: Mapping[str, Mapping],
    *,
    time_bucket: str = DEFAULT_TIME_BUCKET,
    top_n: int = DEFAULT_TOP_N,
) -> list[dict]:
    """Rank zones by descending CIS (ties broken by ``h3_id``); take the top ``top_n``.

    Returns ``[{h3_id, cis, rank}]`` with 1-based ranks. Reserved ``_``-prefixed
    keys are skipped (defensive — the artifacts are pure).
    """
    scored = [
        (h3_id, cis)
        for h3_id, buckets in artifact.items()
        if not str(h3_id).startswith("_")
        and (cis := _cis_for(buckets, time_bucket)) is not None
    ]
    scored.sort(key=lambda t: (-t[1], t[0]))
    if top_n and top_n > 0:
        scored = scored[:top_n]
    return [{"h3_id": h, "cis": round(c, 4), "rank": i + 1} for i, (h, c) in enumerate(scored)]


def diff_top_zones(
    v1_artifact: Mapping[str, Mapping],
    v2_artifact: Mapping[str, Mapping],
    *,
    time_bucket: str = DEFAULT_TIME_BUCKET,
    top_n: int = DEFAULT_TOP_N,
    generated_at: Optional[str] = None,
) -> dict:
    """Compare v1 vs v2 top-``top_n`` rankings (no I/O).

    Returns the v1/v2 top lists plus:
      * ``added``   — zones in the v2 top list but NOT the v1 top list;
      * ``dropped`` — zones in the v1 top list but NOT the v2 top list;
      * ``rank_moves`` — for zones in BOTH lists, ``{h3_id, v1_rank, v2_rank,
        delta}`` where ``delta = v1_rank - v2_rank`` (positive = moved UP toward
        rank 1), sorted by largest absolute move then ``h3_id``.
    """
    v1_top = rank_zones(v1_artifact, time_bucket=time_bucket, top_n=top_n)
    v2_top = rank_zones(v2_artifact, time_bucket=time_bucket, top_n=top_n)

    v1_rank = {z["h3_id"]: z["rank"] for z in v1_top}
    v2_rank = {z["h3_id"]: z["rank"] for z in v2_top}
    v1_ids, v2_ids = set(v1_rank), set(v2_rank)

    added = sorted(v2_ids - v1_ids, key=lambda h: (v2_rank[h], h))
    dropped = sorted(v1_ids - v2_ids, key=lambda h: (v1_rank[h], h))

    rank_moves = [
        {"h3_id": h, "v1_rank": v1_rank[h], "v2_rank": v2_rank[h],
         "delta": v1_rank[h] - v2_rank[h]}
        for h in (v1_ids & v2_ids)
    ]
    rank_moves.sort(key=lambda m: (-abs(m["delta"]), m["h3_id"]))

    return {
        "time_bucket": time_bucket,
        "top_n": top_n,
        "v1_top": v1_top,
        "v2_top": v2_top,
        "added": [{"h3_id": h, "v2_rank": v2_rank[h]} for h in added],
        "dropped": [{"h3_id": h, "v1_rank": v1_rank[h]} for h in dropped],
        "rank_moves": rank_moves,
        "n_added": len(added),
        "n_dropped": len(dropped),
        "n_unchanged_membership": len(v1_ids & v2_ids),
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
    }


# ─── I/O ─────────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def run(
    v1_path: Path = DEFAULT_V1_PATH,
    v2_path: Path = DEFAULT_V2_PATH,
    out_path: Path = DEFAULT_OUT_PATH,
    *,
    time_bucket: str = DEFAULT_TIME_BUCKET,
    top_n: int = DEFAULT_TOP_N,
    generated_at: Optional[str] = None,
    verbose: bool = True,
) -> dict:
    """Read both artifacts, diff their top-N, write the result, print a summary."""
    v1 = _load_json(Path(v1_path))
    v2 = _load_json(Path(v2_path))
    report = diff_top_zones(v1, v2, time_bucket=time_bucket, top_n=top_n, generated_at=generated_at)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    if verbose:
        print(
            f"v1↔v2 top-{top_n} ({time_bucket}): "
            f"{report['n_added']} added, {report['n_dropped']} dropped, "
            f"{report['n_unchanged_membership']} stayed."
        )
        for m in report["rank_moves"][:5]:
            arrow = "↑" if m["delta"] > 0 else ("↓" if m["delta"] < 0 else "·")
            print(f"  {m['h3_id']}  rank {m['v1_rank']} → {m['v2_rank']} {arrow}{abs(m['delta'])}")
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="v1↔v2 CIS top-zone diff (Task 14)")
    parser.add_argument("--v1", default=str(DEFAULT_V1_PATH))
    parser.add_argument("--v2", default=str(DEFAULT_V2_PATH))
    parser.add_argument("--out", default=str(DEFAULT_OUT_PATH))
    parser.add_argument("--time-bucket", default=DEFAULT_TIME_BUCKET)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    args = parser.parse_args(argv)
    run(v1_path=Path(args.v1), v2_path=Path(args.v2), out_path=Path(args.out),
        time_bucket=args.time_bucket, top_n=args.top_n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
