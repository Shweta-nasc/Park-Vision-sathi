"""
ParkVision-Saathi — Self-Validating Congestion Agent
=====================================================

Demo "wow moment" #4: *"Our AI validates itself against real traffic data."*

This agent closes the loop between the model and reality. After Person 2's
Congestion Impact Scores are produced, this agent:

  1. READS the model's raw congestion scores per zone.
  2. QUERIES the real MapMyIndia (Mappls) travel-time data already enriched
     into ``data/enriched/traffic_context.json`` (``travel_time_ratio`` =
     live-traffic ETA ÷ free-flow baseline).
  3. COMPARES the score the model implies against what the road actually does.
  4. CALIBRATES each score up or down with a bounded, trust-weighted adjustment.
  5. LOGS a human-readable reason for every decision.

The maths is taken verbatim from the build bible
(EXECUTION_PLANNER.md, "SELF-VALIDATING CONGESTION AGENT", lines 1463-1524):

    expected_ratio   = 1.0 + (raw_score / 100) * 2.0     # score → implied slowdown
    discrepancy      = actual_ratio - expected_ratio
    alpha            = 0.3                                 # trust weight on Mappls
    adjustment       = alpha * (discrepancy / max(expected_ratio, 1.0))
    calibrated_score = clamp(raw_score * (1 + adjustment), 0, 100)

Design choices (documented so the team can defend them to judges):

  * RULE-BASED reasoning, not Gemini. The agent is deterministic, costs zero
    quota, and runs fully offline — which the demo reliability protocol
    requires ("kill the internet, the demo must survive"). It never hallucinates.
  * ONE consistent category threshold. The planner used ±0.3 on *discrepancy*
    for the reasoning text but ±0.05 on *adjustment* for the summary counts —
    two different cut-offs that can disagree. We categorise every zone once,
    by |adjustment| ≤ 0.05 (i.e. how much the score actually moved), and drive
    BOTH the reasoning string and the summary from it. The log a judge reads
    and the headline numbers can never contradict each other.

Inputs (PRODUCTION run — REAL data, no mocks)
---------------------------------------------
  data/processed/zone_congestion_impact.json → canonical CIS artifact
        ``{h3_id: {time_bucket: breakdown}}`` (2,527 real H3 zones). Each zone's
        ``all_day`` bucket supplies raw_score = ``congestion_impact``,
        actual_ratio = ``mappls_travel_time_ratio``, and the guard flag
        ``is_traffic_degradation_defaulted``.

GUARD (Error-Handling Scenario 1)
---------------------------------
  A zone is calibrated ONLY when ``is_traffic_degradation_defaulted`` is False
  AND ``mappls_travel_time_ratio`` is a valid, strictly-positive number. Every
  other zone is classified ``no_data`` and OMITTED from the calibrated output.
  Over the committed artifact that means ~10 zones get a REAL calibration and
  the remaining ~2,517 are no_data.

Legacy input (mock path, kept for the library API only)
-------------------------------------------------------
  data/mock/hotspots.json              → raw congestion scores (zone_id, congestion_impact)
  data/enriched/traffic_context.json   → real Mappls travel_time_ratio per zone

Outputs
-------
  data/processed/calibrated_scores.json → {h3_id: {raw_score, calibrated_score, ...}}
                                          (ONLY the calibrated zones)
  data/processed/agent_log.json         → {summary counts (calibrated vs no_data) + log}

Usage
-----
    # As a script (PRODUCTION run — calibrates the REAL CIS artifact, no mocks):
    python -m ml.agent.validation_agent
    python ml/agent/validation_agent.py

    # As a library — production (REAL artifact + GUARD):
    from ml.agent.validation_agent import calibrate_artifact_zones, run_from_artifact
    calibrated, summary = calibrate_artifact_zones(artifact)

    # As a library — legacy mock-keyed path:
    from ml.agent.validation_agent import validate_and_calibrate, run
    calibrated, summary = validate_and_calibrate(congestion_scores, mappls_data)
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
HOTSPOTS_PATH = PROJECT_ROOT / "data" / "mock" / "hotspots.json"
TRAFFIC_PATH = PROJECT_ROOT / "data" / "enriched" / "traffic_context.json"
CALIBRATED_OUT = PROJECT_ROOT / "data" / "processed" / "calibrated_scores.json"
AGENT_LOG_OUT = PROJECT_ROOT / "data" / "processed" / "agent_log.json"

# The canonical Congestion Impact Score (CIS) artifact — the REAL production
# input for the calibration run: ``{h3_id: {time_bucket: breakdown}}`` produced
# by ``ml.congestion.build_artifact``. Each zone's ``all_day`` bucket carries the
# raw ``congestion_impact`` (the CIS), the MapMyIndia ``mappls_travel_time_ratio``,
# and the ``is_traffic_degradation_defaulted`` guard flag.
ARTIFACT_PATH = PROJECT_ROOT / "data" / "processed" / "zone_congestion_impact.json"

# ─── Tunable constants (kept verbatim from the planner) ──────────────────────

ALPHA = 0.3                 # trust weight placed on the Mappls measurement
SCORE_TO_RATIO_GAIN = 2.0   # a 100/100 score implies a (1 + 2.0) = 3.0x slowdown
ACCURATE_BAND = 0.05        # |adjustment| ≤ 5% → the model was already accurate


# ─── Core agent ──────────────────────────────────────────────────────────────

def _impact_band(score: float) -> str:
    """Map a 0-100 score to its congestion impact band (matches impact_score.py)."""
    if score <= 25:
        return "MINIMAL"
    elif score <= 50:
        return "MODERATE"
    elif score <= 75:
        return "SEVERE"
    return "CRITICAL"


def validate_and_calibrate(congestion_scores: dict, mappls_data: dict) -> tuple[dict, dict]:
    """Agentic validation loop: calibrate model scores against real Mappls data.

    Parameters
    ----------
    congestion_scores : dict
        ``{zone_id: raw_score}`` — the model's Congestion Impact Score (0-100).
    mappls_data : dict
        ``{zone_id: {... "travel_time_ratio": float, "station": str ...}}`` —
        the enriched MapMyIndia context (``data/enriched/traffic_context.json``).

    Returns
    -------
    (calibrated, summary) : tuple[dict, dict]
        ``calibrated`` maps each zone to its full calibration record.
        ``summary`` holds the headline counts plus an ordered reasoning log.
    """
    calibrated: dict = {}
    agent_log: list = []

    # Process highest-scoring zones first so the log reads worst → best.
    ordered = sorted(congestion_scores.items(), key=lambda kv: kv[1], reverse=True)

    for zone_id, raw_score in ordered:
        raw_score = float(raw_score)
        traffic = mappls_data.get(zone_id, {})
        station = traffic.get("station", "Unknown PS")
        road = traffic.get("road_name") or traffic.get("street") or zone_id
        actual_ratio = traffic.get("travel_time_ratio")

        # ── No real traffic data → cannot validate, fall back to the model ──
        if not actual_ratio:
            record = {
                "zone_id": zone_id,
                "station": station,
                "road_name": road,
                "raw_score": round(raw_score, 1),
                "calibrated_score": round(raw_score, 1),
                "impact_band": _impact_band(raw_score),
                "validated": False,
                "mappls_ratio": None,
                "expected_ratio": None,
                "discrepancy": None,
                "adjustment": 0.0,
                "status": "no_data",
                "reasoning": (
                    f"⚠️ No Mappls traffic data for {road} — keeping the model "
                    f"score of {raw_score:.0f}/100 unvalidated."
                ),
            }
            calibrated[zone_id] = record
            agent_log.append({
                "zone_id": zone_id, "station": station,
                "raw_score": record["raw_score"],
                "calibrated_score": record["calibrated_score"],
                "mappls_ratio": None, "status": "no_data",
                "reasoning": record["reasoning"],
            })
            continue

        # ── Calibration maths (verbatim from the build bible) ───────────────
        actual_ratio = float(actual_ratio)
        expected_ratio = 1.0 + (raw_score / 100.0) * SCORE_TO_RATIO_GAIN
        discrepancy = actual_ratio - expected_ratio
        adjustment = ALPHA * (discrepancy / max(expected_ratio, 1.0))
        calibrated_score = max(0.0, min(100.0, raw_score * (1.0 + adjustment)))

        # ── Single, consistent categorisation drives text AND summary ───────
        if adjustment > ACCURATE_BAND:
            status = "adjusted_up"
            reasoning = (
                f"⬆️ Adjusted UP {raw_score:.0f}→{calibrated_score:.0f}: "
                f"Mappls shows {actual_ratio:.2f}x travel time on {road}, worse "
                f"than the {expected_ratio:.2f}x our score implied. Parking impact "
                f"was UNDERESTIMATED."
            )
        elif adjustment < -ACCURATE_BAND:
            status = "adjusted_down"
            reasoning = (
                f"⬇️ Adjusted DOWN {raw_score:.0f}→{calibrated_score:.0f}: "
                f"Mappls shows only {actual_ratio:.2f}x travel time on {road} vs the "
                f"{expected_ratio:.2f}x our score implied. The road appears to absorb "
                f"the parking load better than violations alone suggest."
            )
        else:
            status = "validated_accurate"
            reasoning = (
                f"✅ Validated: {raw_score:.0f}/100 matches Mappls data on {road} "
                f"({actual_ratio:.2f}x travel time, within tolerance of the "
                f"{expected_ratio:.2f}x implied). Model accurate — no change."
            )

        record = {
            "zone_id": zone_id,
            "station": station,
            "road_name": road,
            "raw_score": round(raw_score, 1),
            "calibrated_score": round(calibrated_score, 1),
            "impact_band": _impact_band(calibrated_score),
            "validated": True,
            "mappls_ratio": round(actual_ratio, 3),
            "expected_ratio": round(expected_ratio, 3),
            "discrepancy": round(discrepancy, 3),
            "adjustment": round(adjustment, 4),
            "status": status,
            "reasoning": reasoning,
        }
        calibrated[zone_id] = record
        agent_log.append({
            "zone_id": zone_id, "station": station,
            "raw_score": record["raw_score"],
            "calibrated_score": record["calibrated_score"],
            "mappls_ratio": record["mappls_ratio"], "status": status,
            "reasoning": reasoning,
        })

    # ── Summary (counts derive from the SAME status field as the log) ───────
    validated = [v for v in calibrated.values() if v["validated"]]
    adjustments = [abs(v["adjustment"]) for v in validated]
    summary = {
        "total_zones": len(calibrated),
        "validated": len(validated),
        "no_data": sum(1 for v in calibrated.values() if v["status"] == "no_data"),
        "accurate": sum(1 for v in validated if v["status"] == "validated_accurate"),
        "adjusted_up": sum(1 for v in validated if v["status"] == "adjusted_up"),
        "adjusted_down": sum(1 for v in validated if v["status"] == "adjusted_down"),
        "mean_abs_adjustment_pct": round(100 * (sum(adjustments) / len(adjustments)), 1) if adjustments else 0.0,
        "max_abs_adjustment_pct": round(100 * max(adjustments), 1) if adjustments else 0.0,
        "log": agent_log,
    }
    return calibrated, summary


# ─── Input loaders ───────────────────────────────────────────────────────────

def load_congestion_scores(path: Path = HOTSPOTS_PATH) -> dict:
    """Build ``{zone_id: congestion_impact}`` from the hotspots ranking file.

    Accepts either a list of hotspot dicts (mock/hotspots.json) or a flat
    ``{zone_id: score}`` mapping, so it keeps working if Person 2 later swaps in
    a real scores file.
    """
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        # Already {zone_id: score} or {zone_id: {congestion_impact: ...}}
        scores = {}
        for zone_id, val in data.items():
            if isinstance(val, dict):
                scores[zone_id] = float(val.get("congestion_impact", 0.0))
            else:
                scores[zone_id] = float(val)
        return scores

    # List of hotspot items
    return {
        item["zone_id"]: float(item["congestion_impact"])
        for item in data
        if "zone_id" in item and "congestion_impact" in item
    }


def load_mappls_data(path: Path = TRAFFIC_PATH) -> dict:
    """Load the enriched MapMyIndia traffic context (``{zone_id: {...}}``)."""
    with open(path) as f:
        return json.load(f)


# ─── Runner ──────────────────────────────────────────────────────────────────

def run(
    hotspots_path: Path = HOTSPOTS_PATH,
    traffic_path: Path = TRAFFIC_PATH,
    calibrated_out: Path = CALIBRATED_OUT,
    log_out: Path = AGENT_LOG_OUT,
    verbose: bool = True,
) -> tuple[dict, dict]:
    """Load inputs, run the agent, persist both JSON outputs, and report."""
    congestion_scores = load_congestion_scores(hotspots_path)
    mappls_data = load_mappls_data(traffic_path)

    calibrated, summary = validate_and_calibrate(congestion_scores, mappls_data)

    calibrated_out.parent.mkdir(parents=True, exist_ok=True)
    with open(calibrated_out, "w") as f:
        json.dump(calibrated, f, indent=2, ensure_ascii=False)
    with open(log_out, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    if verbose:
        _print_report(calibrated, summary, calibrated_out, log_out)

    return calibrated, summary


def _print_report(calibrated: dict, summary: dict, calibrated_out: Path, log_out: Path) -> None:
    """Pretty-print the calibration run to the console for the demo."""
    print("\n" + "=" * 74)
    print("  SELF-VALIDATING CONGESTION AGENT — calibration run")
    print("=" * 74)
    print(
        f"  {'ZONE / ROAD':<34} {'RAW':>5} {'→':^3} {'CAL':>5} {'RATIO':>6}  STATUS"
    )
    print("  " + "-" * 70)
    icon = {
        "adjusted_up": "⬆️", "adjusted_down": "⬇️",
        "validated_accurate": "✅", "no_data": "⚠️",
    }
    for rec in calibrated.values():
        road = (rec["road_name"] or rec["zone_id"])[:32]
        ratio = f"{rec['mappls_ratio']:.2f}x" if rec["mappls_ratio"] else "  n/a"
        print(
            f"  {road:<34} {rec['raw_score']:>5.0f}  →  {rec['calibrated_score']:>5.0f} "
            f"{ratio:>6}  {icon.get(rec['status'], '')} {rec['status']}"
        )

    print("  " + "-" * 70)
    print(
        f"  {summary['total_zones']} zones | "
        f"{summary['validated']} validated against Mappls | "
        f"{summary['accurate']} accurate, "
        f"{summary['adjusted_up']} up, "
        f"{summary['adjusted_down']} down, "
        f"{summary['no_data']} no-data"
    )
    print(
        f"  mean |adjustment| = {summary['mean_abs_adjustment_pct']}% | "
        f"max |adjustment| = {summary['max_abs_adjustment_pct']}%"
    )
    print("=" * 74)
    print(f"  ✓ wrote {calibrated_out.relative_to(PROJECT_ROOT)}")
    print(f"  ✓ wrote {log_out.relative_to(PROJECT_ROOT)}")
    print("=" * 74 + "\n")


# ─── REAL artifact calibration (production run) ──────────────────────────────
#
# The functions above (``validate_and_calibrate`` / ``run``) are the legacy
# mock-keyed path. The production self-validating run reads the canonical CIS
# artifact (``data/processed/zone_congestion_impact.json``, 2,527 real H3 zones)
# and calibrates ONLY the zones that carry a genuine MapMyIndia measurement —
# everything else is left strictly uncalibrated. No mocks, no randomness, no
# clock-dependence.


def _is_valid_ratio(ratio: object) -> bool:
    """True only for a real, finite, strictly-positive travel-time ratio.

    ``bool`` is rejected explicitly (``True``/``False`` are ``int`` subclasses);
    ``None``, NaN, ±inf, and non-positive values are all rejected so the GUARD
    never lets a missing/garbage ratio through to calibration.
    """
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
        return False
    return math.isfinite(float(ratio)) and float(ratio) > 0.0


def load_congestion_artifact(path: Path = ARTIFACT_PATH) -> dict:
    """Load the canonical CIS artifact ``{h3_id: {time_bucket: breakdown}}``."""
    with open(path) as f:
        return json.load(f)


def calibrate_artifact_zones(
    artifact: dict, time_bucket: str = "all_day"
) -> tuple[dict, dict]:
    """Calibrate REAL CIS zones against MapMyIndia travel-time, with the GUARD.

    For every zone in ``artifact`` the chosen ``time_bucket`` bucket (default
    ``all_day``) supplies:

      * ``raw_score``    = ``congestion_impact``                 (the CIS)
      * ``actual_ratio`` = ``mappls_travel_time_ratio``          (real Mappls)
      * guard flag       = ``is_traffic_degradation_defaulted``  (True == fallback)

    GUARD (Error-Handling Scenario 1): a zone is calibrated ONLY when its guard
    flag is ``False`` **and** its ratio is a valid, strictly-positive number.
    Every other zone is classified ``no_data`` and is **omitted entirely** from
    the returned ``calibrated`` mapping — no entry is written for it.

    The calibration maths is the canonical formula (identical to
    :func:`validate_and_calibrate`)::

        expected_ratio   = 1.0 + (raw_score / 100) * SCORE_TO_RATIO_GAIN  # gain 2.0
        discrepancy      = actual_ratio - expected_ratio
        adjustment       = ALPHA * (discrepancy / max(expected_ratio, 1.0))  # ALPHA 0.3
        calibrated_score = clamp(raw_score * (1 + adjustment), 0, 100)

    Deterministic: zones are processed in a fixed order (descending CIS, ties
    broken by ``h3_id``) and the maths has no randomness or clock-dependence, so
    repeated runs over the same artifact yield byte-identical output.

    Returns ``(calibrated, summary)`` where ``calibrated`` is keyed by ``h3_id``
    (the same key scheme as the artifact) and contains only the calibrated zones.
    """
    calibrated: dict = {}
    agent_log: list = []
    no_data_count = 0

    # Deterministic processing order: highest CIS first, ties broken by h3_id, so
    # the log reads worst -> best and the run is reproducible (no dict-order or
    # clock dependence).
    def _raw_of(item: tuple[str, dict]) -> float:
        bucket = item[1].get(time_bucket) if isinstance(item[1], dict) else None
        raw = bucket.get("congestion_impact") if isinstance(bucket, dict) else None
        return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else -1.0

    ordered = sorted(artifact.items(), key=lambda kv: (-_raw_of(kv), kv[0]))

    for h3_id, buckets in ordered:
        bucket = buckets.get(time_bucket) if isinstance(buckets, dict) else None
        if not isinstance(bucket, dict):
            no_data_count += 1
            continue

        raw_score = bucket.get("congestion_impact")
        actual_ratio = bucket.get("mappls_travel_time_ratio")
        defaulted = bucket.get("is_traffic_degradation_defaulted", True)
        station = bucket.get("station") or "Unknown PS"
        junction = bucket.get("junction")
        where = junction or station or h3_id

        # ── GUARD: only genuine measurements are calibrated ────────────────
        valid_raw = isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool)
        if defaulted is not False or not _is_valid_ratio(actual_ratio) or not valid_raw:
            # no_data → classified but DELIBERATELY OMITTED from `calibrated`.
            no_data_count += 1
            continue

        # ── Calibration maths (canonical formula, verbatim) ────────────────
        raw_score = float(raw_score)
        actual_ratio = float(actual_ratio)
        expected_ratio = 1.0 + (raw_score / 100.0) * SCORE_TO_RATIO_GAIN
        discrepancy = actual_ratio - expected_ratio
        adjustment = ALPHA * (discrepancy / max(expected_ratio, 1.0))
        calibrated_score = max(0.0, min(100.0, raw_score * (1.0 + adjustment)))

        # ── Single, consistent categorisation drives text AND summary ──────
        if adjustment > ACCURATE_BAND:
            status = "adjusted_up"
            reasoning = (
                f"⬆️ Adjusted UP {raw_score:.0f}→{calibrated_score:.0f}: Mappls "
                f"shows {actual_ratio:.2f}x travel time near {where}, worse than the "
                f"{expected_ratio:.2f}x our CIS implied. Parking impact was "
                f"UNDERESTIMATED."
            )
        elif adjustment < -ACCURATE_BAND:
            status = "adjusted_down"
            reasoning = (
                f"⬇️ Adjusted DOWN {raw_score:.0f}→{calibrated_score:.0f}: Mappls "
                f"shows only {actual_ratio:.2f}x travel time near {where} vs the "
                f"{expected_ratio:.2f}x our CIS implied. The corridor absorbs the "
                f"parking load better than violations alone suggest."
            )
        else:
            status = "validated_accurate"
            reasoning = (
                f"✅ Validated: CIS {raw_score:.0f}/100 matches Mappls near {where} "
                f"({actual_ratio:.2f}x travel time, within tolerance of the "
                f"{expected_ratio:.2f}x implied). Model accurate — no change."
            )

        record = {
            "zone_id": h3_id,
            "h3_id": h3_id,
            "station": station,
            "raw_score": round(raw_score, 1),       # = CIS (congestion_impact)
            "calibrated_score": round(calibrated_score, 1),
            "impact_band": _impact_band(calibrated_score),
            "validated": True,
            "mappls_ratio": round(actual_ratio, 3),
            "expected_ratio": round(expected_ratio, 3),
            "discrepancy": round(discrepancy, 3),
            "adjustment": round(adjustment, 4),
            "status": status,
            "reasoning": reasoning,
        }
        calibrated[h3_id] = record
        agent_log.append({
            "zone_id": h3_id, "h3_id": h3_id, "station": station,
            "raw_score": record["raw_score"],
            "calibrated_score": record["calibrated_score"],
            "mappls_ratio": record["mappls_ratio"], "status": status,
            "reasoning": reasoning,
        })

    adjustments = [abs(v["adjustment"]) for v in calibrated.values()]
    summary = {
        "total_zones": len(artifact),
        "calibrated": len(calibrated),
        "no_data": no_data_count,
        # `validated` mirrors `calibrated` so the existing /health agent panel and
        # the legacy summary shape keep working.
        "validated": len(calibrated),
        "accurate": sum(1 for v in calibrated.values() if v["status"] == "validated_accurate"),
        "adjusted_up": sum(1 for v in calibrated.values() if v["status"] == "adjusted_up"),
        "adjusted_down": sum(1 for v in calibrated.values() if v["status"] == "adjusted_down"),
        "mean_abs_adjustment_pct": round(100 * (sum(adjustments) / len(adjustments)), 1) if adjustments else 0.0,
        "max_abs_adjustment_pct": round(100 * max(adjustments), 1) if adjustments else 0.0,
        "time_bucket": time_bucket,
        "source": "data/processed/zone_congestion_impact.json",
        "log": agent_log,
    }
    return calibrated, summary


def run_from_artifact(
    artifact_path: Path = ARTIFACT_PATH,
    calibrated_out: Path = CALIBRATED_OUT,
    log_out: Path = AGENT_LOG_OUT,
    time_bucket: str = "all_day",
    verbose: bool = True,
) -> tuple[dict, dict]:
    """Production run: load the REAL CIS artifact, calibrate, persist, report.

    Writes ``calibrated_scores.json`` keyed by ``h3_id`` (only the calibrated
    zones) and ``agent_log.json`` (summary counts + the per-calibrated-zone log).
    """
    artifact = load_congestion_artifact(artifact_path)
    calibrated, summary = calibrate_artifact_zones(artifact, time_bucket=time_bucket)

    calibrated_out.parent.mkdir(parents=True, exist_ok=True)
    with open(calibrated_out, "w") as f:
        json.dump(calibrated, f, indent=2, ensure_ascii=False)
    with open(log_out, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    if verbose:
        _print_artifact_report(calibrated, summary, calibrated_out, log_out)

    return calibrated, summary


def _print_artifact_report(calibrated: dict, summary: dict, calibrated_out: Path, log_out: Path) -> None:
    """Pretty-print the REAL calibration run, leading with the headline counts."""
    print("\n" + "=" * 74)
    print("  SELF-VALIDATING CONGESTION AGENT — REAL artifact calibration run")
    print("=" * 74)
    print(
        f"  {summary['total_zones']} H3 zones scanned  →  "
        f"{summary['calibrated']} REAL calibration, "
        f"{summary['no_data']} no_data (omitted)"
    )
    print("  " + "-" * 70)
    print(f"  {'H3 ZONE / STATION':<40} {'CIS':>5} {'→':^3} {'CAL':>5} {'RATIO':>6}  STATUS")
    print("  " + "-" * 70)
    icon = {
        "adjusted_up": "⬆️", "adjusted_down": "⬇️", "validated_accurate": "✅",
    }
    for rec in calibrated.values():
        label = f"{rec['h3_id']} {rec['station']}"[:38]
        ratio = f"{rec['mappls_ratio']:.2f}x" if rec["mappls_ratio"] else "  n/a"
        print(
            f"  {label:<40} {rec['raw_score']:>5.0f}  →  {rec['calibrated_score']:>5.0f} "
            f"{ratio:>6}  {icon.get(rec['status'], '')} {rec['status']}"
        )
    print("  " + "-" * 70)
    print(
        f"  calibrated={summary['calibrated']} "
        f"(accurate={summary['accurate']}, up={summary['adjusted_up']}, "
        f"down={summary['adjusted_down']})  |  no_data={summary['no_data']}"
    )
    print(
        f"  mean |adjustment| = {summary['mean_abs_adjustment_pct']}% | "
        f"max |adjustment| = {summary['max_abs_adjustment_pct']}%"
    )
    print("=" * 74)
    print(f"  ✓ wrote {calibrated_out.relative_to(PROJECT_ROOT)}")
    print(f"  ✓ wrote {log_out.relative_to(PROJECT_ROOT)}")
    print("=" * 74 + "\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    # Production run: calibrate the REAL CIS artifact (no mocks).
    run_from_artifact()
