"""
ParkVision-Saathi — calibrated CIS artifact builder (Task 5, additive-shadow)
=============================================================================

Produces the **v2** CIS artifact from:
  * the fitted weights of Task 3 (``cis_calibration.json``), and
  * the measured/predicted traffic-degradation of Task 4
    (``predicted_degradation.json``),

without touching the v1 path. The v1 builder
(``ml.congestion.build_artifact.build_congestion_artifact``) is reused with its
new ``weights`` / ``degradation_lookup`` seams; this module only orchestrates the
inputs and attaches a self-describing ``_calibration`` metadata block.

Additive-shadow guarantees
---------------------------
* v1 (``data/processed/zone_congestion_impact.json``) is never modified.
* v2 is written to ``data/processed/zone_congestion_impact_v2.json``.
* The backend (``data_loader``) defaults to v2 but **falls back to v1** when v2
  is absent, so removing/renaming v2 cleanly reverts to v1.
* The per-zone schema is identical to v1 (additive only) — every entry still
  validates against ``CongestionBreakdown``. The only extra top-level key is the
  reserved ``_calibration`` metadata block, which the loader filters out before
  iterating zones (its key starts with ``_``, which no H3 id ever does).

HARD DATA BOUNDARY: this runner must be invoked on the **real** Task 1 collector
output (``congestion_observations.json``) plus the real CSV. It is intentionally
not run on synthetic fixtures, and no synthetic v2 artifact is committed.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Union

import pandas as pd

from ml.congestion.build_artifact import build_congestion_artifact, build_from_real_csv  # noqa: F401
from ml.congestion.impact_score import WEIGHTS
from ml.congestion.predict_degradation import degradation_lookup

logger = logging.getLogger(__name__)

# ─── Paths / constants ───────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CALIBRATION_PATH = PROJECT_ROOT / "data" / "processed" / "cis_calibration.json"
DEFAULT_DEGRADATION_PATH = PROJECT_ROOT / "data" / "processed" / "predicted_degradation.json"
DEFAULT_VALIDATION_PATH = PROJECT_ROOT / "data" / "processed" / "cis_validation_report.json"
DEFAULT_TRAFFIC_CONTEXT_PATH = PROJECT_ROOT / "data" / "enriched" / "traffic_context.json"
DEFAULT_OBSERVATIONS_PATH = PROJECT_ROOT / "data" / "enriched" / "congestion_observations.json"
DEFAULT_V2_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact_v2.json"

# Reserved top-level key carrying calibration metadata inside the artifact. It
# starts with "_" so the loader can distinguish it from H3-id zone keys (which
# are 15-char hex strings, never beginning with "_").
CALIBRATION_META_KEY = "_calibration"
CIS_VERSION = "v2"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _load_json(path: Union[str, Path]) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def load_calibrated_weights(calibration_path: Union[str, Path]) -> tuple[Optional[dict], dict]:
    """Return ``(new_weights_or_None, calibration_report)`` from Task 3 output.

    Falls back to ``None`` weights (the canonical v1 weights are then used) when
    the calibration file is missing or malformed.
    """
    report = _load_json(calibration_path)
    weights = report.get("new_weights")
    if isinstance(weights, Mapping) and abs(sum(weights.values()) - 1.0) < 1e-6:
        return dict(weights), report
    return None, report


def build_calibration_metadata(
    *,
    weights: Mapping[str, float],
    calibration_report: Mapping,
    degradation_report: Mapping,
    validation_report: Mapping,
    collection_date: Optional[str],
    generated_at: str,
) -> dict:
    """Assemble the self-describing ``_calibration`` block (Task 5 metadata)."""
    n_measured = (
        validation_report.get("n_measured")
        or degradation_report.get("n")
        or (calibration_report.get("n_train", 0) + calibration_report.get("n_test", 0))
        or None
    )
    return {
        "cis_version": CIS_VERSION,
        "weights": dict(weights),
        "weights_method": calibration_report.get("method"),
        "spearman_test": calibration_report.get("spearman_new_test"),
        "spearman_old_test": calibration_report.get("spearman_old_test"),
        "n_measured": n_measured,
        "n_exploration": validation_report.get("n_exploration"),
        "degradation_model": degradation_report.get("model"),
        "degradation_lozo_r2": degradation_report.get("lozo_r2"),
        "degradation_lozo_spearman": degradation_report.get("lozo_spearman"),
        "collection_date": collection_date,
        "generated_at": generated_at,
    }


# ─── v2 builder ──────────────────────────────────────────────────────────────

def build_calibrated_artifact(
    violations: Union[str, Path, pd.DataFrame],
    *,
    calibration_path: Union[str, Path] = DEFAULT_CALIBRATION_PATH,
    degradation_path: Union[str, Path] = DEFAULT_DEGRADATION_PATH,
    validation_path: Union[str, Path] = DEFAULT_VALIDATION_PATH,
    traffic_context_path: Union[str, Path] = DEFAULT_TRAFFIC_CONTEXT_PATH,
    observations_path: Union[str, Path] = DEFAULT_OBSERVATIONS_PATH,
    out_path: Union[str, Path] = DEFAULT_V2_PATH,
    resolution: int = 9,
    travel_time_ratios: Optional[Mapping[str, float]] = None,
    collection_date: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> dict:
    """Build the v2 artifact (fitted weights + predicted degradation + metadata).

    Returns the in-memory artifact (``{h3_id: {bucket: breakdown}}`` plus the
    reserved ``_calibration`` key) and writes it to ``out_path``.
    """
    weights, calibration_report = load_calibrated_weights(calibration_path)
    if weights is None:
        logger.warning(
            "No usable calibrated weights at %s — building v2 with canonical weights.",
            calibration_path,
        )
        weights = dict(WEIGHTS)

    degradation_report = _load_json(degradation_path)
    deg_lookup = degradation_lookup(degradation_report) if degradation_report else {}
    if not deg_lookup:
        logger.warning(
            "No predicted degradation at %s — v2 keeps the from-ratio/default component.",
            degradation_path,
        )

    validation_report = _load_json(validation_path)

    # Build per-zone breakdowns through the v1 builder's calibration seams. The v1
    # builder writes the pure artifact to out_path and returns it in-memory.
    artifact = build_congestion_artifact(
        violations,
        traffic_context_path=traffic_context_path,
        out_path=out_path,
        resolution=resolution,
        travel_time_ratios=travel_time_ratios,
        weights=weights,
        degradation_lookup=deg_lookup or None,
    )

    # Derive a collection_date from the observations when not supplied.
    if collection_date is None:
        observations = _load_json(observations_path)
        for obs in observations.values():
            if isinstance(obs, Mapping) and obs.get("measured_at"):
                collection_date = obs["measured_at"]
                break

    gen = generated_at or datetime.now(timezone.utc).isoformat()
    artifact[CALIBRATION_META_KEY] = build_calibration_metadata(
        weights=weights,
        calibration_report=calibration_report,
        degradation_report=degradation_report,
        validation_report=validation_report,
        collection_date=collection_date,
        generated_at=gen,
    )

    # Re-write with the metadata block included (the v1 builder wrote the pure
    # artifact a moment ago; this overwrites it with the metadata-carrying version).
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(artifact, handle, indent=2, ensure_ascii=False)

    n_zones = sum(1 for k in artifact if k != CALIBRATION_META_KEY)
    logger.info("Wrote calibrated v2 CIS artifact to %s: %d zone(s).", out_path, n_zones)
    return artifact


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    parser = argparse.ArgumentParser(description="Build the calibrated v2 CIS artifact (Task 5)")
    parser.add_argument("--csv", default=None, help="real violations CSV (defaults to dataset lookup)")
    parser.add_argument("--calibration", default=str(DEFAULT_CALIBRATION_PATH))
    parser.add_argument("--degradation", default=str(DEFAULT_DEGRADATION_PATH))
    parser.add_argument("--validation", default=str(DEFAULT_VALIDATION_PATH))
    parser.add_argument("--traffic-context", default=str(DEFAULT_TRAFFIC_CONTEXT_PATH))
    parser.add_argument("--observations", default=str(DEFAULT_OBSERVATIONS_PATH))
    parser.add_argument("--out", default=str(DEFAULT_V2_PATH))
    args = parser.parse_args(argv)

    from ml.congestion.build_artifact import _resolve_real_csv

    csv_path = Path(args.csv) if args.csv else _resolve_real_csv()
    frame = pd.read_csv(csv_path, low_memory=False)
    build_calibrated_artifact(
        frame,
        calibration_path=Path(args.calibration),
        degradation_path=Path(args.degradation),
        validation_path=Path(args.validation),
        traffic_context_path=Path(args.traffic_context),
        observations_path=Path(args.observations),
        out_path=Path(args.out),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
