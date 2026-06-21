"""
rekey_traffic_context.py — Phase 3 (DOWNSTREAM PATCH of Person 4's enrichment).

PROBLEM
-------
``data/enriched/traffic_context.json`` carries REAL Bengaluru coordinates and a
REAL ``travel_time_ratio`` per entry, but it is keyed by PLACEHOLDER H3 ids
(``8928308280fffff`` …) that do NOT correspond to the cells those coordinates
fall in. The Congestion Impact artifact is keyed by the TRUE H3 res-9 cells
derived from the violation lat/lon, so the by-key join in
``ml.congestion.build_artifact.load_travel_time_ratios`` never resolves and every
zone falls back to the default traffic-degradation component (0 non-defaulted).

FIX (downstream)
----------------
Recompute each entry's key as ``h3.latlng_to_cell(lat, lon, 9)`` from its REAL
coordinates, preserving ``travel_time_ratio`` and every other field, and write a
corrected ``data/enriched/traffic_context_h3.json``. Entries with missing/invalid
coordinates are skipped. The CIS artifact rebuilt against this file activates the
travel-time join.

This is explicitly a PATCH applied inside the ML pipeline so our artifact is
correct for the demo. Person 4 should still fix the enrichment UPSTREAM (write the
true H3 key when the enrichment is generated) — see ``ml/enrichment/mapmyindia.py``.

Run:
    python ml/enrichment/rekey_traffic_context.py
    python ml/enrichment/rekey_traffic_context.py --rebuild-cis   # also rebuild the artifact
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import h3
except ImportError as exc:  # pragma: no cover
    raise ImportError("The 'h3' package is required. Install via: pip install h3") from exc

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "data" / "enriched" / "traffic_context.json"
OUT_PATH = PROJECT_ROOT / "data" / "enriched" / "traffic_context_h3.json"
H3_RESOLUTION = 9


def rekey(src_path: Path = SRC_PATH, out_path: Path = OUT_PATH,
          resolution: int = H3_RESOLUTION) -> dict:
    """Re-key the enrichment by true H3 ids computed from each entry's lat/lon."""
    with src_path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    rekeyed: dict[str, dict] = {}
    skipped = 0
    collisions = 0
    for old_key, payload in raw.items():
        if not isinstance(payload, dict):
            skipped += 1
            continue
        lat, lon = payload.get("lat"), payload.get("lon")
        try:
            lat_f, lon_f = float(lat), float(lon)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
            skipped += 1
            continue

        new_key = h3.latlng_to_cell(lat_f, lon_f, resolution)
        entry = dict(payload)
        entry["original_zone_id"] = old_key
        entry["zone_id"] = new_key
        if new_key in rekeyed:
            collisions += 1
        rekeyed[new_key] = entry

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(rekeyed, fh, indent=2, ensure_ascii=False)

    print(f"[rekey] {len(raw)} source entries → {len(rekeyed)} re-keyed H3 cells "
          f"(skipped {skipped} invalid, {collisions} coordinate collisions)")
    print(f"[rekey] Wrote {out_path}")
    return rekeyed


def _count_nondefaulted(artifact_path: Path) -> tuple[int, int]:
    if not artifact_path.exists():
        return 0, 0
    with artifact_path.open("r", encoding="utf-8") as fh:
        art = json.load(fh)
    zones = sum(1 for z in art.values()
                if any(b.get("is_traffic_degradation_defaulted") is False for b in z.values()))
    entries = sum(1 for z in art.values() for b in z.values()
                  if b.get("is_traffic_degradation_defaulted") is False)
    return zones, entries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-key traffic context to true H3 ids.")
    parser.add_argument("--rebuild-cis", action="store_true",
                        help="Rebuild data/processed/zone_congestion_impact.json with the re-keyed file")
    args = parser.parse_args()

    artifact_path = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact.json"
    before_zones, before_entries = _count_nondefaulted(artifact_path)
    print(f"[rekey] CIS non-defaulted BEFORE: {before_zones} zones / {before_entries} entries")

    rekey()

    if args.rebuild_cis:
        from ml.congestion.build_artifact import build_from_real_csv
        print("\n[rekey] Rebuilding canonical CIS artifact with re-keyed traffic context...")
        build_from_real_csv(traffic_context_path=str(OUT_PATH), out_path=str(artifact_path))
        after_zones, after_entries = _count_nondefaulted(artifact_path)
        print(f"[rekey] CIS non-defaulted AFTER: {after_zones} zones / {after_entries} entries "
              f"(was {before_zones} / {before_entries})")
