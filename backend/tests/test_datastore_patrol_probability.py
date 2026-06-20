"""
Example-based unit tests for Stackelberg patrol-probability normalization.
==========================================================================

Task 6.4 — unit test for ``DataStore.congestion_patrol_probabilities``
(``backend.app.data_loader``), the accessor added in task 6.2 that derives a
per-zone patrol probability proportional to ``CIS ** PATROL_ALPHA`` (the
Stackelberg emphasis exponent, ``PATROL_ALPHA == 1.5``) normalized across zones.

**Validates: Requirement 8.7** — "THE Backend SHALL derive Stackelberg patrol
probability proportional to CIS raised to the power 1.5, normalized across Zones."

These are deterministic, example-based unit tests (not property tests): each
builds a small synthetic CIS artifact with known, distinct ``congestion_impact``
values under an ``all_day`` bucket, installs it directly on a ``DataStore``
(``store.congestion = artifact``; ``store.loaded = True`` so the accessor's
``ensure()`` guard does not reload and clobber the committed ``data/`` artifact —
mirroring the task 6.3 test approach), and asserts the documented behavior:

  * Probabilities sum to 1.0 for a normal (non-zero) artifact.
  * Each probability equals ``cis_i ** 1.5 / Σ(cis ** 1.5)`` (proportionality).
  * Probabilities are non-decreasing in CIS (higher CIS -> higher-or-equal prob).
  * Edge cases — all-zero CIS (no division by zero -> all 0.0), empty artifact
    (-> empty list), and a single non-zero zone (-> probability 1.0).
"""

from __future__ import annotations

import pytest

from backend.app.data_loader import PATROL_ALPHA, DataStore

ALL_DAY = "all_day"


# ─── Synthetic artifact assembly (mirrors the 6.3 test approach) ─────────────

def _breakdown(h3_id: str, cis: float) -> dict:
    """One zone's artifact breakdown carrying the fields the accessor reads.

    ``congestion_patrol_probabilities`` consumes ``zone_id`` / ``h3_id`` / ``lat`` /
    ``lon`` / ``congestion_impact``; the rest of the contract is irrelevant here, so
    the breakdown is intentionally minimal.
    """
    return {
        "zone_id": h3_id,
        "h3_id": h3_id,
        "time_bucket": ALL_DAY,
        "lat": 12.97,
        "lon": 77.59,
        "congestion_impact": cis,
    }


def _artifact(cis_by_zone: dict[str, float]) -> dict[str, dict[str, dict]]:
    """Assemble ``{h3_id: {"all_day": breakdown}}`` from ``{h3_id: cis}``."""
    return {zid: {ALL_DAY: _breakdown(zid, cis)} for zid, cis in cis_by_zone.items()}


def _store_with_artifact(artifact: dict) -> DataStore:
    """A ``DataStore`` serving ``artifact`` directly from memory.

    ``loaded`` is forced True so the accessor's ``ensure()`` does NOT call
    ``load()`` (which would read the committed on-disk artifact and overwrite the
    synthetic one). The accessor reads only ``self.congestion``.
    """
    store = DataStore()
    store.congestion = artifact
    store.loaded = True
    return store


def _expected_probabilities(cis_by_zone: dict[str, float]) -> dict[str, float]:
    """Independently recompute the expected normalized probabilities.

    ``p_i = w_i / Σ w`` where ``w_i = max(cis_i, 0) ** PATROL_ALPHA``. When the
    weight sum is 0 (all-zero / empty), every probability is 0.0 — matching the
    accessor's guarded ``wsum > 0`` branch.
    """
    weights = {zid: max(cis, 0.0) ** PATROL_ALPHA for zid, cis in cis_by_zone.items()}
    wsum = sum(weights.values())
    if wsum <= 0:
        return {zid: 0.0 for zid in cis_by_zone}
    return {zid: w / wsum for zid, w in weights.items()}


# ─── Sum-to-one ──────────────────────────────────────────────────────────────

def test_patrol_probabilities_sum_to_one_for_nonzero_artifact():
    """For a normal (non-zero) artifact, the probabilities sum to 1.0.

    Validates: Requirement 8.7 (normalized across zones).
    """
    cis_by_zone = {"z1": 10.0, "z2": 40.0, "z3": 90.0, "z4": 65.0}
    store = _store_with_artifact(_artifact(cis_by_zone))

    rows = store.congestion_patrol_probabilities(ALL_DAY)

    assert len(rows) == len(cis_by_zone)
    total = sum(r["patrol_probability"] for r in rows)
    assert total == pytest.approx(1.0, abs=1e-9)
    # Each probability is itself a valid weight in [0, 1].
    for r in rows:
        assert 0.0 <= r["patrol_probability"] <= 1.0


# ─── Proportionality to CIS ** 1.5 ──────────────────────────────────────────

def test_patrol_probabilities_proportional_to_cis_pow_alpha():
    """Each probability equals ``cis ** 1.5 / Σ(cis ** 1.5)`` (the Stackelberg
    emphasis), recomputed independently and matched within tolerance.

    Validates: Requirement 8.7 (proportional to CIS ** 1.5).
    """
    # Pin the design exponent so a change to PATROL_ALPHA is caught here too.
    assert PATROL_ALPHA == 1.5

    cis_by_zone = {"z1": 12.0, "z2": 33.0, "z3": 58.0, "z4": 81.0, "z5": 99.0}
    store = _store_with_artifact(_artifact(cis_by_zone))

    rows = store.congestion_patrol_probabilities(ALL_DAY)
    got = {r["h3_id"]: r["patrol_probability"] for r in rows}
    expected = _expected_probabilities(cis_by_zone)

    assert got.keys() == expected.keys()
    for zid, exp in expected.items():
        assert got[zid] == pytest.approx(exp, rel=1e-9, abs=1e-12)


# ─── Monotonicity: probability is non-decreasing in CIS ──────────────────────

def test_patrol_probabilities_non_decreasing_in_cis():
    """A zone with higher CIS has a probability >= a zone with lower CIS.

    Validates: Requirement 8.7 (probability tracks CIS monotonically).
    """
    cis_by_zone = {"low": 5.0, "mid": 25.0, "high": 70.0, "top": 95.0}
    store = _store_with_artifact(_artifact(cis_by_zone))

    rows = store.congestion_patrol_probabilities(ALL_DAY)
    prob = {r["h3_id"]: r["patrol_probability"] for r in rows}

    # Walk zones in ascending CIS order; probabilities must never decrease.
    ascending = sorted(cis_by_zone, key=lambda z: cis_by_zone[z])
    probs_in_cis_order = [prob[z] for z in ascending]
    assert probs_in_cis_order == sorted(probs_in_cis_order)
    # And strictly: the top-CIS zone has the largest probability.
    assert prob["top"] == max(prob.values())
    assert prob["low"] == min(prob.values())

    # The accessor returns rows sorted by descending probability, which (since
    # probability is monotonic in CIS) is also descending CIS order.
    assert [r["h3_id"] for r in rows] == ["top", "high", "mid", "low"]


# ─── Edge case: all-zero CIS -> no division by zero ──────────────────────────

def test_patrol_probabilities_all_zero_cis_no_division_by_zero():
    """When every CIS is 0 the weight sum is 0, so the accessor sets every
    probability to 0.0 (its documented guard) instead of dividing by zero.

    Validates: Requirement 8.7 (robust normalization edge).
    """
    cis_by_zone = {"z1": 0.0, "z2": 0.0, "z3": 0.0}
    store = _store_with_artifact(_artifact(cis_by_zone))

    rows = store.congestion_patrol_probabilities(ALL_DAY)

    assert len(rows) == len(cis_by_zone)
    assert all(r["patrol_probability"] == 0.0 for r in rows)
    # No probability is NaN/inf (which a 0/0 division would produce).
    assert sum(r["patrol_probability"] for r in rows) == 0.0


# ─── Edge case: empty artifact -> empty list ─────────────────────────────────

def test_patrol_probabilities_empty_artifact_returns_empty_list():
    """An empty CIS artifact yields an empty probability list (no zones to rank).

    Validates: Requirement 8.7 (degrades gracefully on an empty universe).
    """
    store = _store_with_artifact({})

    assert store.congestion_patrol_probabilities(ALL_DAY) == []


# ─── Edge case: a single non-zero zone -> probability 1.0 ────────────────────

def test_patrol_probabilities_single_zone_probability_one():
    """A single zone with CIS > 0 receives the entire patrol probability (1.0).

    Validates: Requirement 8.7 (normalization sums to 1.0 in the degenerate case).
    """
    store = _store_with_artifact(_artifact({"only": 50.0}))

    rows = store.congestion_patrol_probabilities(ALL_DAY)

    assert len(rows) == 1
    assert rows[0]["h3_id"] == "only"
    assert rows[0]["patrol_probability"] == pytest.approx(1.0, abs=1e-9)


def test_patrol_probabilities_single_zero_zone_probability_zero():
    """A single zone with CIS == 0 gets probability 0.0 (guarded zero-weight sum),
    confirming the single-zone path also avoids a 0/0 division.

    Validates: Requirement 8.7 (robust normalization edge).
    """
    store = _store_with_artifact(_artifact({"only": 0.0}))

    rows = store.congestion_patrol_probabilities(ALL_DAY)

    assert len(rows) == 1
    assert rows[0]["patrol_probability"] == 0.0
