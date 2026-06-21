"""
Integration tests for the self-validating agent over fixture CIS artifacts
(``ml.agent.validation_agent``).
================================================================================

This module UNIONS two complementary integration suites that drive the two
distinct production seams of the agent end to end:

A. **GUARD / artifact path** (``calibrate_artifact_zones`` / ``run_from_artifact``)
   over a tiny in-test ``{h3_id: {time_bucket: breakdown}}`` fixture. Pins the
   contract the backend wiring depends on:
     (a) every calibrated zone's ``calibrated_score`` (and the ``calibrated_impact``
         surfaced through the backend) is within [0, 100];
     (b) GUARD — only zones with ``is_traffic_degradation_defaulted == False`` AND a
         valid, strictly-positive ``mappls_travel_time_ratio`` are calibrated; every
         other ("no_data") zone produces NO entry in ``calibrated_scores`` and yields
         ``calibrated_impact = None`` when served by the backend;
     (c) determinism — running the agent twice over the same artifact yields
         byte-identical output (no randomness, no clock-dependence).
   It also pins the canonical calibration formula exactly and checks that the served
   breakdown validates against the typed ``backend.app.models.CongestionBreakdown``
   contract.

B. **``run()`` / ``load_cis_scores`` path** over a hand-built fixture CIS artifact
   plus a matching ``traffic_context.json``. ``ml.agent.validation_agent.run`` reads
   each zone's ``all_day`` rollup ``congestion_impact`` (keyed by ``h3_id``) via
   :func:`load_cis_scores`, calibrates it against the real MapMyIndia
   ``travel_time_ratio``, and the ``DataStore`` then surfaces the agent's calibrated
   value as ``calibrated_impact`` on the :class:`CongestionBreakdown`. Asserts the
   calibrated values are bounded, the run is deterministic, the score source is the
   CIS artifact, the ``no_data`` path preserves the raw score, an absent artifact with
   the fallback disabled yields empty output, the DataStore surfaces
   ``calibrated_impact`` end to end, and the committed ``data/processed`` artifacts are
   never written.

Every file these tests write lives under pytest's per-test ``tmp_path``; the committed
``data/processed/{calibrated_scores,agent_log,zone_congestion_impact}.json`` are never
written (asserted explicitly in suite B).

**Validates: Requirements 7.1, 8.8, 6.6**

Framework: pytest (per design "Dependencies: ... ``hypothesis`` + ``pytest``"). These
are example-based integration tests, so they use plain pytest fixtures and asserts
rather than Hypothesis.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ml.agent import validation_agent
from ml.agent.validation_agent import (
    ALPHA,
    SCORE_TO_RATIO_GAIN,
    calibrate_artifact_zones,
    run_from_artifact,
)
from ml.congestion.impact_score import (
    DEFAULT_TRAFFIC_DEGRADATION,
    WEIGHTS,
    impact_band,
)
from backend.app.data_loader import DataStore
from backend.app.models import ComponentBreakdown, CongestionBreakdown


# ═════════════════════════════════════════════════════════════════════════════
# Suite A — GUARD / artifact path (calibrate_artifact_zones / run_from_artifact)
# ═════════════════════════════════════════════════════════════════════════════

# ─── Fixture artifact (tiny, valid CongestionBreakdown shape per zone) ───────

_CANONICAL_WEIGHTS = {
    "lane_blockage": 0.30,
    "intersection_impact": 0.25,
    "traffic_degradation": 0.25,
    "access_blockage": 0.10,
    "vehicle_size": 0.10,
}


def _guard_breakdown(
    h3_id: str,
    congestion_impact: float,
    *,
    ratio,
    defaulted: bool,
    station: str = "Test PS",
    time_bucket: str = "all_day",
) -> dict:
    """Return one valid ``CongestionBreakdown``-shaped dict for the fixture artifact."""
    return {
        "zone_id": h3_id,
        "h3_id": h3_id,
        "time_bucket": time_bucket,
        "lat": 12.97,
        "lon": 77.59,
        "congestion_impact": congestion_impact,
        "impact_band": "MODERATE" if congestion_impact > 25 else "MINIMAL",
        "components": {
            "lane_blockage": 0.4,
            "intersection_impact": 0.3,
            "traffic_degradation": 0.5,
            "access_blockage": 0.2,
            "vehicle_size": 0.35,
            "severity": 0.45,
        },
        "weights": dict(_CANONICAL_WEIGHTS),
        "estimated_lane_hours_blocked": 12.5,
        "total_records": 42,
        "top_violations": ["WRONG PARKING"],
        "station": station,
        "junction": None,
        "mappls_travel_time_ratio": ratio,
        "is_traffic_degradation_defaulted": defaulted,
        "calibrated_impact": None,
    }


# Two measured zones (calibratable) + four no_data zones spanning every reason a
# zone is excluded by the GUARD.
MEASURED_HIGH = "89aaaaaaaa1ffff"   # high CIS, ratio below implied -> adjusted_down
MEASURED_LOW = "89aaaaaaaa2ffff"    # low CIS, ratio above implied  -> adjusted_up
NO_DATA_DEFAULTED = "89bbbbbbbb1ffff"  # flag True (used the 0.5 fallback)
NO_DATA_RATIO_NONE = "89bbbbbbbb2ffff"  # flag False but ratio missing
NO_DATA_RATIO_ZERO = "89bbbbbbbb3ffff"  # flag False but ratio not positive
NO_DATA_RATIO_NAN = "89bbbbbbbb4ffff"   # flag False but ratio NaN


def _fixture_artifact() -> dict:
    return {
        MEASURED_HIGH: {"all_day": _guard_breakdown(MEASURED_HIGH, 80.0, ratio=1.10, defaulted=False)},
        MEASURED_LOW: {"all_day": _guard_breakdown(MEASURED_LOW, 10.0, ratio=1.90, defaulted=False)},
        NO_DATA_DEFAULTED: {"all_day": _guard_breakdown(NO_DATA_DEFAULTED, 30.0, ratio=None, defaulted=True)},
        NO_DATA_RATIO_NONE: {"all_day": _guard_breakdown(NO_DATA_RATIO_NONE, 30.0, ratio=None, defaulted=False)},
        NO_DATA_RATIO_ZERO: {"all_day": _guard_breakdown(NO_DATA_RATIO_ZERO, 30.0, ratio=0.0, defaulted=False)},
        NO_DATA_RATIO_NAN: {"all_day": _guard_breakdown(NO_DATA_RATIO_NAN, 30.0, ratio=float("nan"), defaulted=False)},
    }


MEASURED_ZONES = {MEASURED_HIGH, MEASURED_LOW}
NO_DATA_ZONES = {
    NO_DATA_DEFAULTED,
    NO_DATA_RATIO_NONE,
    NO_DATA_RATIO_ZERO,
    NO_DATA_RATIO_NAN,
}


# ─── (b) GUARD: only measured zones calibrated; no_data omitted ──────────────

def test_guard_calibrates_only_measured_zones():
    """Only the two measured zones are calibrated; all four no_data zones are omitted."""
    calibrated, summary = calibrate_artifact_zones(_fixture_artifact())

    assert set(calibrated) == MEASURED_ZONES
    for zone_id in NO_DATA_ZONES:
        assert zone_id not in calibrated, f"{zone_id} should have NO calibrated entry"

    assert summary["total_zones"] == 6
    assert summary["calibrated"] == 2
    assert summary["no_data"] == 4
    # The counts partition every input zone.
    assert summary["calibrated"] + summary["no_data"] == summary["total_zones"]


# ─── (a) calibrated_score within [0, 100] ────────────────────────────────────

def test_calibrated_scores_within_bounds():
    """Every calibrated zone's calibrated_score stays within [0, 100]."""
    calibrated, _ = calibrate_artifact_zones(_fixture_artifact())
    assert calibrated, "expected at least one calibrated zone"
    for zone_id, record in calibrated.items():
        assert 0.0 <= record["calibrated_score"] <= 100.0, zone_id
        assert 0.0 <= record["raw_score"] <= 100.0, zone_id


# ─── Canonical formula is implemented exactly ────────────────────────────────

def test_calibration_matches_canonical_formula():
    """The agent's per-zone maths equals the canonical formula bit-for-bit.

    expected_ratio = 1 + (CIS/100)*2.0 ; discrepancy = actual - expected ;
    adjustment = 0.3*(discrepancy/max(expected,1)) ; calibrated = clamp(CIS*(1+adj),0,100).
    """
    assert ALPHA == 0.3
    assert SCORE_TO_RATIO_GAIN == 2.0

    raw, ratio = 80.0, 1.10  # MEASURED_HIGH
    expected_ratio = 1.0 + (raw / 100.0) * 2.0
    discrepancy = ratio - expected_ratio
    adjustment = 0.3 * (discrepancy / max(expected_ratio, 1.0))
    calibrated_score = max(0.0, min(100.0, raw * (1.0 + adjustment)))

    calibrated, _ = calibrate_artifact_zones(_fixture_artifact())
    rec = calibrated[MEASURED_HIGH]
    assert rec["expected_ratio"] == pytest.approx(round(expected_ratio, 3))
    assert rec["discrepancy"] == pytest.approx(round(discrepancy, 3))
    assert rec["adjustment"] == pytest.approx(round(adjustment, 4))
    assert rec["calibrated_score"] == pytest.approx(round(calibrated_score, 1))


# ─── (c) determinism: run twice -> identical output ──────────────────────────

def test_determinism_in_memory():
    """Calibrating the same artifact twice yields equal, equally-ordered output."""
    artifact = _fixture_artifact()
    cal1, sum1 = calibrate_artifact_zones(artifact)
    cal2, sum2 = calibrate_artifact_zones(artifact)

    assert cal1 == cal2
    assert sum1 == sum2
    # Insertion order (worst CIS first) and serialization are identical too.
    assert list(cal1) == list(cal2)
    assert json.dumps(cal1) == json.dumps(cal2)
    assert json.dumps(sum1) == json.dumps(sum2)


def test_determinism_written_files(tmp_path):
    """run_from_artifact writes byte-identical files across runs (no committed I/O)."""
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(_fixture_artifact()), encoding="utf-8")
    out1 = tmp_path / "calibrated_1.json"
    out2 = tmp_path / "calibrated_2.json"
    log1 = tmp_path / "log_1.json"
    log2 = tmp_path / "log_2.json"

    run_from_artifact(artifact_path, out1, log1, verbose=False)
    run_from_artifact(artifact_path, out2, log2, verbose=False)

    assert out1.read_bytes() == out2.read_bytes()
    assert log1.read_bytes() == log2.read_bytes()

    written = json.loads(out1.read_text(encoding="utf-8"))
    assert set(written) == MEASURED_ZONES


# ─── Backend wiring: breakdown conforms + calibrated_impact number vs None ───

def test_backend_breakdown_conforms_and_calibrated_impact_number_vs_none():
    """DataStore.congestion_breakdown returns a valid CongestionBreakdown with
    ``calibrated_impact`` a number for a calibrated zone and ``None`` for a
    no_data zone."""
    artifact = _fixture_artifact()
    calibrated, _ = calibrate_artifact_zones(artifact)

    # Wire a DataStore directly to the fixture artifact + agent output (no disk).
    store = DataStore()
    store.loaded = True
    store.congestion = artifact
    store.calibrated = calibrated

    # Calibrated zone -> calibrated_impact is a number, and the dict validates.
    measured = store.congestion_breakdown(MEASURED_HIGH)
    assert measured is not None
    assert isinstance(measured["calibrated_impact"], (int, float))
    assert 0.0 <= measured["calibrated_impact"] <= 100.0
    model = CongestionBreakdown.model_validate(measured)
    assert model.calibrated_impact == pytest.approx(calibrated[MEASURED_HIGH]["calibrated_score"])

    # no_data zone -> present in the CIS artifact but calibrated_impact is None.
    no_data = store.congestion_breakdown(NO_DATA_DEFAULTED)
    assert no_data is not None
    assert no_data["calibrated_impact"] is None
    model_nd = CongestionBreakdown.model_validate(no_data)
    assert model_nd.calibrated_impact is None

    # A zone absent from the artifact resolves to None (caller falls back).
    assert store.congestion_breakdown("89zzzzzzzzz0ffff") is None


# ═════════════════════════════════════════════════════════════════════════════
# Suite B — run() / load_cis_scores path + DataStore surfacing end-to-end
# ═════════════════════════════════════════════════════════════════════════════

# ─── Fixture zones ───────────────────────────────────────────────────────────
#
# Illustrative H3 res-9 ids (used only as artifact / context dict keys; nothing
# here validates them as real cells). Each zone exercises a distinct branch:
#
#   ZONE_A — measured, high CIS  -> validated + calibrated (in traffic context)
#   ZONE_B — measured, mid CIS   -> validated + calibrated (in traffic context)
#   ZONE_C — present but NO ratio -> the `no_data` path (score preserved)
#   ZONE_D — keyed under `morning_peak` only (no `all_day`) -> the agent SKIPS it
#            (load_cis_scores needs an all_day/requested bucket), so it has NO
#            calibration record, yet the DataStore still surfaces its breakdown
#            (via the all_day fallback) with `calibrated_impact = None`.
ZONE_A = "8960145b483ffff"
ZONE_B = "8960145b48bffff"
ZONE_C = "8960145b497ffff"
ZONE_D = "8960145b4d3ffff"

# Measured MapMyIndia travel-time ratios for the validated zones.
RATIO_A = 1.9
RATIO_B = 1.25

# Known per-zone congestion_impact baked into the fixture artifact.
SCORE_A = 82.0
SCORE_B = 48.0
SCORE_C = 18.0
SCORE_D = 60.0

# Repo-root-anchored committed files this test must never write.
REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_FILES = (
    REPO_ROOT / "data" / "processed" / "calibrated_scores.json",
    REPO_ROOT / "data" / "processed" / "agent_log.json",
    REPO_ROOT / "data" / "processed" / "zone_congestion_impact.json",
)


# ─── Fixture builders ────────────────────────────────────────────────────────

def _breakdown(
    h3_id: str,
    time_bucket: str,
    congestion_impact: float,
    *,
    ratio: float | None,
    station: str,
    total_records: int,
) -> dict:
    """A valid serialized :class:`CongestionBreakdown` for one zone-bucket.

    Built through the real Pydantic contract and ``model_dump()`` so each artifact
    entry matches exactly what ``ml.congestion.build_artifact`` writes (every key
    present, including ``calibrated_impact = None``). Only ``congestion_impact`` is
    read by the agent; the rest makes the entry a contract-valid breakdown the
    ``DataStore`` can serve and re-validate. ``traffic_degradation`` mirrors the
    scorer's mapping so the breakdown stays internally consistent, but note the
    agent calibrates against ``traffic_context.json`` (below), not this field.
    """
    if ratio is None:
        traffic_degradation = DEFAULT_TRAFFIC_DEGRADATION
    else:
        traffic_degradation = min(max((ratio - 1.0) / 2.0, 0.0), 1.0)

    model = CongestionBreakdown(
        zone_id=h3_id,
        h3_id=h3_id,
        time_bucket=time_bucket,
        lat=12.97,
        lon=77.59,
        congestion_impact=congestion_impact,
        impact_band=impact_band(congestion_impact),
        components=ComponentBreakdown(
            lane_blockage=0.40,
            intersection_impact=0.30,
            traffic_degradation=traffic_degradation,
            access_blockage=0.20,
            vehicle_size=0.50,
            severity=0.50,
        ),
        weights=dict(WEIGHTS),
        estimated_lane_hours_blocked=12.5,
        total_records=total_records,
        top_violations=["WRONG PARKING", "PARKING IN A MAIN ROAD"],
        station=station,
        mappls_travel_time_ratio=ratio,
        is_traffic_degradation_defaulted=ratio is None,
    )
    return model.model_dump()


def _cis_artifact() -> dict:
    """The fixture CIS artifact: ``{h3_id: {time_bucket: breakdown}}``.

    A/B/C carry an ``all_day`` rollup (the canonical shape the agent reads); D is
    keyed under ``morning_peak`` only, so the agent skips it (see ZONE_D note).
    """
    return {
        ZONE_A: {"all_day": _breakdown(ZONE_A, "all_day", SCORE_A, ratio=RATIO_A,
                                       station="Upparpet PS", total_records=540)},
        ZONE_B: {"all_day": _breakdown(ZONE_B, "all_day", SCORE_B, ratio=RATIO_B,
                                       station="Cubbon Park PS", total_records=320)},
        ZONE_C: {"all_day": _breakdown(ZONE_C, "all_day", SCORE_C, ratio=None,
                                       station="Halasuru PS", total_records=95)},
        ZONE_D: {"morning_peak": _breakdown(ZONE_D, "morning_peak", SCORE_D, ratio=None,
                                            station="Shivajinagar PS", total_records=210)},
    }


def _traffic_context() -> dict:
    """Matching enrichment: A/B carry a ``travel_time_ratio``; C does NOT.

    C is present (so it is a real, named zone) but has no ``travel_time_ratio`` —
    this is the ``no_data`` branch the agent must record without crashing. D is
    absent here (the agent never reaches it).
    """
    return {
        ZONE_A: {"zone_id": ZONE_A, "travel_time_ratio": RATIO_A,
                 "station": "Upparpet PS", "road_name": "Old Madras Road"},
        ZONE_B: {"zone_id": ZONE_B, "travel_time_ratio": RATIO_B,
                 "station": "Cubbon Park PS", "road_name": "Kasturba Road"},
        ZONE_C: {"zone_id": ZONE_C, "station": "Halasuru PS",
                 "road_name": "100 Ft Road"},  # NO travel_time_ratio -> no_data
    }


@pytest.fixture
def agent_run(tmp_path) -> SimpleNamespace:
    """Write the fixture inputs under ``tmp_path`` and run the agent once.

    Runs with ``hotspots_path=None`` so the CIS artifact is the sole score source
    and the legacy hotspots fallback is disabled. All inputs/outputs live under
    ``tmp_path`` — the committed artifacts are never touched.
    """
    artifact_path = tmp_path / "zone_congestion_impact.json"
    artifact_path.write_text(json.dumps(_cis_artifact()), encoding="utf-8")
    ctx_path = tmp_path / "traffic_context.json"
    ctx_path.write_text(json.dumps(_traffic_context()), encoding="utf-8")

    cal_out = tmp_path / "out" / "calibrated_scores.json"
    log_out = tmp_path / "out" / "agent_log.json"

    calibrated, summary = validation_agent.run(
        cis_artifact_path=artifact_path,
        traffic_path=ctx_path,
        calibrated_out=cal_out,
        log_out=log_out,
        hotspots_path=None,
        verbose=False,
    )
    return SimpleNamespace(
        tmp_path=tmp_path,
        artifact_path=artifact_path,
        ctx_path=ctx_path,
        cal_out=cal_out,
        log_out=log_out,
        calibrated=calibrated,
        summary=summary,
    )


# ─── Agent end-to-end tests ──────────────────────────────────────────────────

def test_agent_reads_cis_artifact_and_calibrates_expected_zones(agent_run):
    """The agent's score source is the CIS artifact and it calibrates exactly the
    artifact zones that expose a readable ``all_day`` ``congestion_impact``, keyed
    by ``h3_id``.

    Zones A/B/C (each with an ``all_day`` rollup) are calibrated; D is skipped
    because it has no ``all_day`` (and no requested) bucket for ``load_cis_scores``.

    Validates: Requirements 8.8.
    """
    assert agent_run.summary["score_source"] == "cis_artifact"
    assert set(agent_run.calibrated) == {ZONE_A, ZONE_B, ZONE_C}
    assert agent_run.summary["total_zones"] == 3
    # A/B were measured against Mappls; C had no ratio.
    assert agent_run.summary["validated"] == 2
    assert agent_run.summary["no_data"] == 1


def test_every_calibrated_score_is_within_bounds(agent_run):
    """Every produced ``calibrated_score`` lies in the closed interval [0, 100].

    The calibration clamps to ``max(0, min(100, raw * (1 + adjustment)))`` for
    validated zones and preserves the (already in-range) raw score for ``no_data``
    zones, so no zone can leave the band.

    Validates: Requirements 8.8.
    """
    assert agent_run.calibrated, "expected a non-empty calibration result"
    for zone_id, rec in agent_run.calibrated.items():
        score = rec["calibrated_score"]
        assert isinstance(score, (int, float)) and not isinstance(score, bool)
        assert 0.0 <= score <= 100.0, f"{zone_id} calibrated_score {score} out of [0,100]"
        # The agent's reported band is consistent with the calibrated score.
        assert rec["impact_band"] == impact_band(score)


def test_zone_without_ratio_is_recorded_no_data_with_score_preserved(agent_run):
    """A zone present in the context but lacking a ``travel_time_ratio`` is recorded
    ``no_data`` (unvalidated) with its raw CIS preserved as the calibrated score.

    Validates: Requirements 8.8.
    """
    rec_c = agent_run.calibrated[ZONE_C]
    assert rec_c["status"] == "no_data"
    assert rec_c["validated"] is False
    assert rec_c["mappls_ratio"] is None
    # Score preserved: calibrated == raw == the fixture's known CIS.
    assert rec_c["raw_score"] == pytest.approx(SCORE_C)
    assert rec_c["calibrated_score"] == pytest.approx(SCORE_C)


def test_run_is_deterministic(agent_run):
    """Running twice on identical inputs yields identical calibrated output.

    The same fixture input files drive a second run into fresh output paths; the
    returned ``calibrated``/``summary`` dicts and the written ``calibrated_scores``
    JSON are all identical (no randomness, clock, or network).

    Validates: Requirements 7.1.
    """
    cal_out_2 = agent_run.tmp_path / "out2" / "calibrated_scores.json"
    log_out_2 = agent_run.tmp_path / "out2" / "agent_log.json"

    calibrated_2, summary_2 = validation_agent.run(
        cis_artifact_path=agent_run.artifact_path,
        traffic_path=agent_run.ctx_path,
        calibrated_out=cal_out_2,
        log_out=log_out_2,
        hotspots_path=None,
        verbose=False,
    )

    assert calibrated_2 == agent_run.calibrated
    assert summary_2 == agent_run.summary
    assert cal_out_2.read_text(encoding="utf-8") == agent_run.cal_out.read_text(
        encoding="utf-8"
    )


def test_absent_artifact_with_no_fallback_yields_empty_output(tmp_path):
    """An absent CIS artifact with ``hotspots_path=None`` produces empty calibrated
    output and does not crash.

    Validates: Requirements 8.8.
    """
    missing_artifact = tmp_path / "does_not_exist.json"
    missing_ctx = tmp_path / "no_context.json"
    cal_out = tmp_path / "out" / "calibrated_scores.json"
    log_out = tmp_path / "out" / "agent_log.json"

    calibrated, summary = validation_agent.run(
        cis_artifact_path=missing_artifact,
        traffic_path=missing_ctx,
        calibrated_out=cal_out,
        log_out=log_out,
        hotspots_path=None,
        verbose=False,
    )

    assert calibrated == {}
    assert summary["total_zones"] == 0
    assert summary["score_source"] == "cis_artifact"  # fallback disabled
    # Outputs are still written (empty), proving the run completed cleanly.
    assert cal_out.exists() and json.loads(cal_out.read_text(encoding="utf-8")) == {}


# ─── DataStore surfacing end-to-end test ─────────────────────────────────────

def test_datastore_surfaces_calibrated_impact_end_to_end(agent_run, tmp_path):
    """The DataStore merges the agent's calibrated score onto the breakdown.

    Writing the SAME fixture artifact and the agent's calibrated output into a temp
    ``data`` dir, a loaded ``DataStore`` surfaces ``calibrated_impact`` equal to the
    agent's ``calibrated_score`` for a calibrated zone, ``None`` for a zone with no
    calibration record (ZONE_D), and the merged breakdown validates against the
    contract with ``0 <= calibrated_impact <= 100``.

    Validates: Requirements 6.6, 8.8.
    """
    data_dir = tmp_path / "datastore"
    processed = data_dir / "processed"
    processed.mkdir(parents=True)
    # SAME fixture CIS artifact + the agent's calibrated output (A/B/C; not D).
    (processed / "zone_congestion_impact.json").write_text(
        json.dumps(_cis_artifact()), encoding="utf-8"
    )
    (processed / "calibrated_scores.json").write_text(
        json.dumps(agent_run.calibrated), encoding="utf-8"
    )

    store = DataStore(data_dir=data_dir).load()

    # ── A calibrated zone: calibrated_impact == the agent's calibrated_score ──
    bd_a = store.congestion_breakdown(ZONE_A)
    assert bd_a is not None
    expected_a = agent_run.calibrated[ZONE_A]["calibrated_score"]
    assert bd_a["calibrated_impact"] == pytest.approx(expected_a)

    # The merged breakdown still validates against the typed contract (Req 6.6),
    # and the calibrated value is bounded (Req 8.8).
    model_a = CongestionBreakdown.model_validate(bd_a)
    assert model_a.calibrated_impact == pytest.approx(expected_a)
    assert 0.0 <= model_a.calibrated_impact <= 100.0

    # ── A zone with NO calibration record: calibrated_impact is None ──────────
    bd_d = store.congestion_breakdown(ZONE_D)
    assert bd_d is not None, "DataStore should still surface ZONE_D's breakdown"
    assert bd_d["calibrated_impact"] is None
    # It is a real, contract-valid breakdown served via the all_day fallback.
    CongestionBreakdown.model_validate(bd_d)

    # ── A no_data zone still surfaces its preserved score (record exists) ─────
    bd_c = store.congestion_breakdown(ZONE_C)
    assert bd_c is not None
    assert bd_c["calibrated_impact"] == pytest.approx(SCORE_C)


# ─── Safety: committed artifacts are never written ───────────────────────────

def test_committed_artifacts_are_not_overwritten(tmp_path):
    """Running the agent with temp output paths never creates or overwrites the
    committed ``data/processed`` artifacts.

    Each committed file is snapshotted before the run and asserted byte-identical
    (and unchanged in existence) afterwards, guaranteeing all I/O is confined to
    ``tmp_path``.
    """
    snapshots = [
        (p, p.exists(), p.read_bytes() if p.exists() else None) for p in COMMITTED_FILES
    ]

    artifact_path = tmp_path / "zone_congestion_impact.json"
    artifact_path.write_text(json.dumps(_cis_artifact()), encoding="utf-8")
    ctx_path = tmp_path / "traffic_context.json"
    ctx_path.write_text(json.dumps(_traffic_context()), encoding="utf-8")

    validation_agent.run(
        cis_artifact_path=artifact_path,
        traffic_path=ctx_path,
        calibrated_out=tmp_path / "out" / "calibrated_scores.json",
        log_out=tmp_path / "out" / "agent_log.json",
        hotspots_path=None,
        verbose=False,
    )

    for path, existed_before, bytes_before in snapshots:
        assert path.exists() == existed_before, (
            f"committed file {path} existence changed"
        )
        if existed_before:
            assert path.read_bytes() == bytes_before, (
                f"committed file {path} was overwritten"
            )