"""
Integration test for the built CIS artifact
(``ml.congestion.build_artifact.build_congestion_artifact``).
==========================================================================

Task 5.5 — integration test for the built artifact.

Where the property tests (tasks 5.2 / 5.3) exercise the *aggregation seam*
(``build_aggregates``) in isolation, this test drives the offline batch's public
**entry point end to end**: a small synthetic violations corpus flows through
``build_congestion_artifact`` (read -> prepare -> aggregate -> corpus maxima ->
``score_zone`` -> write JSON) and the *written artifact* is asserted against the
design's contract and shape. It follows the design's "Integration Testing
Approach": build the artifact from a small fixture violations set, then assert
it is H3-keyed, carries an ``all_day`` rollup per zone, and every entry validates
against the typed :class:`~backend.app.models.CongestionBreakdown` contract.

What this fixture exercises (per task 5.5):

* **2-3 H3 cells.** Two of the fixture points are ~30 m apart and collapse into a
  single H3 res-9 cell (the "measured" zone A); two further points give zones B
  and C — three distinct top-level artifact keys.
* **Multiple data-rich buckets.** Rows land in ``night`` / ``morning_peak`` /
  ``midday`` / ``afternoon`` across the zones, plus the per-zone ``all_day``
  rollup.
* **A mix of violation and vehicle types**, and **at least one named junction**
  (Trinity Circle / Silk Board Junction / Indiranagar 100ft) alongside the
  sentinels the builder treats as "no junction".
* **A post-16:00 IST row that must be dropped** (the temporal-cliff guard): zone
  A carries an 18:20 IST row that must contribute to *neither* a time bucket nor
  the ``all_day`` rollup.
* **A deterministic MapMyIndia join.** A tiny ``traffic_context.json`` is keyed
  by the *actual* H3 id zone A resolves to (via ``h3_id_for``) with a measured
  ``travel_time_ratio``, so zone A exercises the *measured* branch
  (``is_traffic_degradation_defaulted`` False) while the unmatched zones B/C
  exercise the deterministic ``0.5`` *defaulted* branch (flag True).

Both input shapes Requirement 11.1 admits are covered: the primary path passes an
in-memory :class:`pandas.DataFrame`, and a companion test feeds the same rows
from a ``.json`` columnar source on disk and asserts an identical artifact (no
SQLite/database anywhere).

Every artifact and input file this module writes lives under pytest's per-test
``tmp_path``; the committed ``data/processed/zone_congestion_impact.json`` is
never created or overwritten (asserted explicitly).

**Validates: Requirements 8.1, 11.1, 12.1**

Framework: pytest (per design "Dependencies: ... ``hypothesis`` + ``pytest``").
This is an example-based integration test, so it uses plain pytest fixtures and
asserts rather than Hypothesis.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import h3
import pandas as pd
import pytest

from ml.congestion.build_artifact import (
    ALL_DAY,
    JUNCTION_NAME_COL,
    LAT_COL,
    LON_COL,
    STATION_COL,
    TIMESTAMP_COL,
    TIME_BUCKET_BINS,
    UPDATED_VEHICLE_TYPE_COL,
    VEHICLE_TYPE_COL,
    VIOLATION_TYPE_COL,
    build_congestion_artifact,
    h3_centroid,
    h3_id_for,
)
from ml.congestion.impact_score import (
    DEFAULT_TRAFFIC_DEGRADATION,
    impact_band,
)
from backend.app.models import CongestionBreakdown

# ─── Fixture geography ───────────────────────────────────────────────────────

# Bengaluru points. CELL_A and CELL_A2 are ~30 m apart and resolve to the SAME
# H3 res-9 cell (verified: 8960145b483ffff), so rows there combine into one zone
# across two buckets and its all_day rollup; CELL_B and CELL_C are distinct cells.
CELL_A: tuple[float, float] = (12.9716, 77.5946)   # measured zone (in traffic ctx)
CELL_A2: tuple[float, float] = (12.9719, 77.5948)  # collides into CELL_A
CELL_B: tuple[float, float] = (12.9352, 77.6245)   # defaulted zone (unmatched)
CELL_C: tuple[float, float] = (12.9698, 77.7500)   # defaulted zone (unmatched)

# MapMyIndia travel-time ratio written into the fixture enrichment for zone A.
# The scorer maps it to traffic_degradation = clamp((ratio - 1) / 2, 0, 1).
MEASURED_RATIO = 1.8
EXPECTED_MEASURED_DEGRADATION = (MEASURED_RATIO - 1.0) / 2.0  # = 0.4

# The four data-rich buckets (00:00-16:00 IST), derived from the builder's own
# bin table so this stays in lock-step with the source of truth (Requirement 12.1).
DATA_RICH_BUCKETS: frozenset[str] = frozenset(name for _, _, name in TIME_BUCKET_BINS)
ALLOWED_BUCKETS: frozenset[str] = DATA_RICH_BUCKETS | {ALL_DAY}

# Repo-root-anchored path to the committed artifact this test must never touch.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_PATH = REPO_ROOT / "data" / "processed" / "zone_congestion_impact.json"


# ─── Fixture corpus ──────────────────────────────────────────────────────────

def _row(
    lat: float,
    lon: float,
    ist_timestamp: str,
    violations: list[str],
    vehicle: str,
    junction: object,
    station: str,
) -> dict:
    """One builder-shaped cleaned-violation row.

    ``ist_timestamp`` carries an explicit ``+05:30`` offset so the builder's
    UTC-parse/IST-convert round-trip recovers exactly the intended IST hour (and
    therefore the intended time bucket). ``updated_vehicle_type`` is left absent
    (None) so ``vehicle_type`` is used as-is.
    """
    return {
        LAT_COL: lat,
        LON_COL: lon,
        TIMESTAMP_COL: ist_timestamp,
        VIOLATION_TYPE_COL: violations,
        VEHICLE_TYPE_COL: vehicle,
        UPDATED_VEHICLE_TYPE_COL: None,
        JUNCTION_NAME_COL: junction,
        STATION_COL: station,
    }


def _fixture_rows() -> list[dict]:
    """A small synthetic violations corpus spanning 3 H3 cells and 4 buckets.

    Zone A (measured): morning_peak x2 + midday, plus one POST-CLIFF (18:20 IST)
    row that must be dropped. Zone B (defaulted): night + afternoon. Zone C
    (defaulted): morning_peak. Mixed violation strings (main road / double parking
    / junction / access / uncategorized) and vehicle types (car / scooter / bus /
    lorry / van / motorcycle), with named junctions and "no junction" sentinels.
    """
    return [
        # ── Zone A — measured zone ──────────────────────────────────────────
        _row(*CELL_A, "2024-03-15T08:15:00+05:30",
             ["PARKING IN A MAIN ROAD", "DOUBLE PARKING"], "CAR",
             "Trinity Circle", "Upparpet"),                    # morning_peak
        _row(*CELL_A2, "2024-03-15T09:30:00+05:30",
             ["PARKING IN A MAIN ROAD"], "SCOOTER",
             "NO JUNCTION", "Upparpet"),                       # morning_peak (same cell)
        _row(*CELL_A, "2024-03-15T12:05:00+05:30",
             ["PARKING ON FOOTPATH"], "BUS",
             "", "Upparpet"),                                  # midday
        _row(*CELL_A, "2024-03-15T18:20:00+05:30",
             ["NO PARKING"], "BUS",
             "Trinity Circle", "Upparpet"),                    # POST-CLIFF -> DROPPED
        # ── Zone B — defaulted zone (unmatched in traffic context) ──────────
        _row(*CELL_B, "2024-03-15T02:30:00+05:30",
             ["DOUBLE PARKING", "PARKING NEAR ROAD CROSSING"], "LORRY",
             "Silk Board Junction", "Cubbon Park"),            # night
        _row(*CELL_B, "2024-03-15T14:30:00+05:30",
             ["PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC"], "VAN",
             "NULL", "Cubbon Park"),                           # afternoon
        # ── Zone C — defaulted zone (unmatched in traffic context) ──────────
        _row(*CELL_C, "2024-03-15T07:45:00+05:30",
             ["PARKING NEAR ROAD CROSSING"], "MOTOR CYCLE",
             "Indiranagar 100ft", "Halasuru"),                 # morning_peak
    ]


def _fixture_df() -> pd.DataFrame:
    return pd.DataFrame(_fixture_rows())


@pytest.fixture
def built(tmp_path) -> SimpleNamespace:
    """Build the artifact from the in-memory fixture into ``tmp_path`` and return it.

    Writes a tiny ``traffic_context.json`` keyed by the *actual* H3 id zone A
    resolves to (so the MapMyIndia join is deterministic and the measured branch
    is exercised) and the artifact JSON — both under ``tmp_path`` so no committed
    file is touched.
    """
    zone_a = h3_id_for(*CELL_A)
    zone_b = h3_id_for(*CELL_B)
    zone_c = h3_id_for(*CELL_C)

    ctx_path = tmp_path / "traffic_context.json"
    ctx_path.write_text(
        json.dumps({zone_a: {"zone_id": zone_a, "travel_time_ratio": MEASURED_RATIO}}),
        encoding="utf-8",
    )
    out_path = tmp_path / "zone_congestion_impact.json"

    artifact = build_congestion_artifact(
        _fixture_df(),
        traffic_context_path=str(ctx_path),
        out_path=str(out_path),
    )
    return SimpleNamespace(
        artifact=artifact,
        out_path=out_path,
        zone_a=zone_a,
        zone_b=zone_b,
        zone_c=zone_c,
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _all_breakdowns(artifact: dict):
    """Yield ``(zone_id, time_bucket, breakdown_dict)`` for every artifact entry."""
    for zone_id, buckets in artifact.items():
        for time_bucket, breakdown in buckets.items():
            yield zone_id, time_bucket, breakdown


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_artifact_written_to_out_path_equals_returned_dict(built):
    """The artifact is written to ``out_path`` and the on-disk JSON equals the
    returned in-memory dict (the function both returns and persists the artifact).

    Validates: Requirements 8.1.
    """
    assert built.out_path.exists(), "build_congestion_artifact did not write out_path"

    on_disk = json.loads(built.out_path.read_text(encoding="utf-8"))
    assert on_disk == built.artifact, "on-disk artifact differs from the returned dict"


def test_artifact_is_h3_keyed_with_all_day_rollup(built):
    """Top-level keys are valid H3 ids; each maps to a dict of
    ``time_bucket -> breakdown`` and every zone carries an ``all_day`` rollup.

    Validates: Requirements 8.1.
    """
    artifact = built.artifact

    # Exactly the three observed zones, each a valid H3 cell id.
    assert set(artifact) == {built.zone_a, built.zone_b, built.zone_c}
    for zone_id in artifact:
        assert h3.is_valid_cell(zone_id), f"top-level key {zone_id!r} is not an H3 id"

    # Each zone maps to a non-empty dict of buckets and includes an all_day entry.
    for zone_id, buckets in artifact.items():
        assert isinstance(buckets, dict) and buckets, f"zone {zone_id!r} has no buckets"
        assert ALL_DAY in buckets, f"zone {zone_id!r} is missing the all_day rollup"
        for breakdown in buckets.values():
            assert isinstance(breakdown, dict)


def test_only_data_rich_in_window_buckets_appear(built):
    """Only the four 00:00-16:00 IST buckets (plus ``all_day``) appear, and the
    post-16:00 row is dropped from both buckets and the rollup.

    Zone A's only buckets are ``morning_peak`` + ``midday`` (+ ``all_day``): its
    18:20 IST row contributes no bucket, and its ``all_day`` total_records is 3,
    not 4 — proving the temporal-cliff guard ran.

    Validates: Requirements 12.1.
    """
    artifact = built.artifact

    # No bucket anywhere outside the allowed 00:00-16:00 windows / all_day.
    for zone_id, buckets in artifact.items():
        unexpected = set(buckets) - ALLOWED_BUCKETS
        assert not unexpected, f"zone {zone_id!r} has out-of-window buckets {unexpected}"

    # The corpus is genuinely multi-bucket (not a single-cell triviality).
    observed_data_rich = {
        bucket for _, buckets in artifact.items() for bucket in buckets
    } & DATA_RICH_BUCKETS
    assert {"night", "morning_peak", "midday", "afternoon"} <= observed_data_rich, (
        f"expected all four data-rich buckets across the corpus, got {observed_data_rich}"
    )

    # Zone A: the post-cliff (18:20) row produced no bucket and is absent from all_day.
    assert set(artifact[built.zone_a]) == {"morning_peak", "midday", ALL_DAY}
    assert artifact[built.zone_a][ALL_DAY]["total_records"] == 3, (
        "post-16:00 row was not dropped from zone A's all_day rollup"
    )


def test_every_breakdown_validates_against_the_contract(built):
    """Every artifact entry validates against the ``CongestionBreakdown`` contract:
    score in [0, 100], band consistent with score, lat/lon populated from the H3
    centroid, ``zone_id == h3_id == outer key``, and the weights echo sums to 1.0.

    Validates: Requirements 8.1.
    """
    centroids: dict[str, tuple[float, float]] = {}

    for zone_id, time_bucket, breakdown in _all_breakdowns(built.artifact):
        # The serialized boundary contract round-trips and validates (Req 8.1).
        model = CongestionBreakdown.model_validate(breakdown)

        assert 0.0 <= model.congestion_impact <= 100.0
        assert model.impact_band == impact_band(model.congestion_impact), (
            f"band {model.impact_band!r} inconsistent with score "
            f"{model.congestion_impact!r} at {(zone_id, time_bucket)!r}"
        )

        # Spatial identity: zone_id == h3_id == the outer artifact key.
        assert model.zone_id == model.h3_id == zone_id
        assert model.time_bucket == time_bucket

        # lat/lon are populated from the H3 centroid (the scorer leaves them None;
        # the artifact builder attaches them).
        clat, clon = centroids.setdefault(zone_id, h3_centroid(zone_id))
        assert model.lat is not None and model.lon is not None
        assert model.lat == pytest.approx(clat)
        assert model.lon == pytest.approx(clon)

        # The echoed weights are a partition of unity (Req 6.3, surfaced here).
        assert sum(model.weights.values()) == pytest.approx(1.0, abs=1e-9)
        # estimated lane-hours are non-negative and total_records is consistent.
        assert model.estimated_lane_hours_blocked >= 0.0
        assert model.total_records >= 1


def test_measured_zone_vs_defaulted_zones_traffic_degradation(built):
    """The matched zone shows the *measured* MapMyIndia degradation
    (``is_traffic_degradation_defaulted`` False); the unmatched zones show the
    deterministic 0.5 default with the flag True.

    Validates: Requirements 8.1, 11.1.
    """
    artifact = built.artifact

    # Zone A is in the traffic context -> measured branch for ALL its buckets.
    for time_bucket, breakdown in artifact[built.zone_a].items():
        model = CongestionBreakdown.model_validate(breakdown)
        assert model.is_traffic_degradation_defaulted is False, (
            f"zone A / {time_bucket} should use the measured ratio"
        )
        assert model.mappls_travel_time_ratio == pytest.approx(MEASURED_RATIO)
        assert model.components.traffic_degradation == pytest.approx(
            EXPECTED_MEASURED_DEGRADATION
        )

    # Zones B and C are absent from the traffic context -> deterministic default.
    for zone_id in (built.zone_b, built.zone_c):
        for time_bucket, breakdown in artifact[zone_id].items():
            model = CongestionBreakdown.model_validate(breakdown)
            assert model.is_traffic_degradation_defaulted is True, (
                f"zone {zone_id} / {time_bucket} should fall back to the default"
            )
            assert model.mappls_travel_time_ratio is None
            assert model.components.traffic_degradation == pytest.approx(
                DEFAULT_TRAFFIC_DEGRADATION
            )


def test_json_file_source_yields_identical_artifact(tmp_path):
    """Requirement 11.1's other admitted input shape: a ``.json`` columnar source
    on disk produces the exact same artifact as the in-memory DataFrame path
    (no SQLite/database involved).

    Validates: Requirements 11.1, 8.1.
    """
    zone_a = h3_id_for(*CELL_A)
    ctx_path = tmp_path / "traffic_context.json"
    ctx_path.write_text(
        json.dumps({zone_a: {"zone_id": zone_a, "travel_time_ratio": MEASURED_RATIO}}),
        encoding="utf-8",
    )

    # In-memory build.
    mem_artifact = build_congestion_artifact(
        _fixture_df(),
        traffic_context_path=str(ctx_path),
        out_path=str(tmp_path / "artifact_mem.json"),
    )

    # On-disk JSON columnar source build (same rows).
    violations_json = tmp_path / "violations_clean.json"
    _fixture_df().to_json(violations_json, orient="records")
    file_artifact = build_congestion_artifact(
        str(violations_json),
        traffic_context_path=str(ctx_path),
        out_path=str(tmp_path / "artifact_file.json"),
    )

    assert set(file_artifact) == {zone_a, h3_id_for(*CELL_B), h3_id_for(*CELL_C)}
    assert file_artifact == mem_artifact, (
        "JSON file source produced a different artifact than the in-memory source"
    )
    for zone_id, buckets in file_artifact.items():
        assert ALL_DAY in buckets


def test_build_does_not_touch_committed_default_artifact(tmp_path):
    """Building to a ``tmp_path`` destination never creates or overwrites the
    committed ``data/processed/zone_congestion_impact.json``.

    The default artifact path is snapshotted before the build and asserted
    unchanged afterwards, guaranteeing the test's I/O is confined to ``tmp_path``.
    """
    before_exists = DEFAULT_ARTIFACT_PATH.exists()
    before_bytes = DEFAULT_ARTIFACT_PATH.read_bytes() if before_exists else None

    zone_a = h3_id_for(*CELL_A)
    ctx_path = tmp_path / "traffic_context.json"
    ctx_path.write_text(
        json.dumps({zone_a: {"zone_id": zone_a, "travel_time_ratio": MEASURED_RATIO}}),
        encoding="utf-8",
    )
    build_congestion_artifact(
        _fixture_df(),
        traffic_context_path=str(ctx_path),
        out_path=str(tmp_path / "zone_congestion_impact.json"),
    )

    after_exists = DEFAULT_ARTIFACT_PATH.exists()
    assert after_exists == before_exists, (
        "the committed default artifact path was created/removed by the build"
    )
    if before_exists:
        assert DEFAULT_ARTIFACT_PATH.read_bytes() == before_bytes, (
            "the committed default artifact was overwritten by the build"
        )
