"""
Tests for the v1↔v2 top-zone diff (Task 14).
==============================================================================

Pins the pure ranking + set arithmetic that makes the calibration's effect on
the headline top-N legible: which zones the calibration ADDED to the critical
list, which it DROPPED, and how zones that stayed MOVED in rank. All fixtures are
hand-built ``{h3_id: {bucket: {congestion_impact}}}`` artifacts — no CIS scoring
involved, so the diff logic is tested in isolation and deterministically.
"""

from __future__ import annotations

from ml.congestion.diff_top_zones import diff_top_zones, rank_zones


def _artifact(cis_by_zone: dict[str, float], *, bucket: str = "all_day") -> dict:
    return {z: {bucket: {"congestion_impact": c}} for z, c in cis_by_zone.items()}


def test_rank_zones_orders_desc_and_breaks_ties_by_id():
    art = _artifact({"zb": 50.0, "za": 50.0, "zc": 90.0})
    ranked = rank_zones(art, top_n=3)
    assert [r["h3_id"] for r in ranked] == ["zc", "za", "zb"]  # 90 first; tie -> id asc
    assert [r["rank"] for r in ranked] == [1, 2, 3]


def test_rank_zones_skips_reserved_keys_and_missing_cis():
    art = _artifact({"z1": 10.0, "z2": 20.0})
    art["_calibration"] = {"cis_version": "v2"}  # reserved -> ignored
    art["z3"] = {"all_day": {"congestion_impact": None}}  # unusable -> skipped
    ranked = rank_zones(art, top_n=10)
    assert [r["h3_id"] for r in ranked] == ["z2", "z1"]


def test_rank_zones_respects_top_n():
    art = _artifact({f"z{i}": float(i) for i in range(20)})
    ranked = rank_zones(art, top_n=5)
    assert len(ranked) == 5
    assert ranked[0]["h3_id"] == "z19"  # highest CIS


def test_diff_added_dropped_and_rank_moves():
    # v1 top-3: a(90) > b(80) > c(70); d=10 is out.
    v1 = _artifact({"a": 90.0, "b": 80.0, "c": 70.0, "d": 10.0})
    # v2: calibration lifts d above c -> c drops out, d enters; a/b swap.
    v2 = _artifact({"a": 80.0, "b": 85.0, "c": 40.0, "d": 75.0})

    diff = diff_top_zones(v1, v2, top_n=3)
    assert [z["h3_id"] for z in diff["v1_top"]] == ["a", "b", "c"]
    assert [z["h3_id"] for z in diff["v2_top"]] == ["b", "a", "d"]

    assert diff["added"] == [{"h3_id": "d", "v2_rank": 3}]
    assert diff["dropped"] == [{"h3_id": "c", "v1_rank": 3}]
    assert diff["n_added"] == 1 and diff["n_dropped"] == 1
    assert diff["n_unchanged_membership"] == 2  # a, b stayed

    moves = {m["h3_id"]: m for m in diff["rank_moves"]}
    # a: rank 1 -> 2 (delta = 1 - 2 = -1, moved down); b: 2 -> 1 (delta +1, up).
    assert moves["a"]["delta"] == -1
    assert moves["b"]["delta"] == 1


def test_diff_identical_artifacts_no_changes():
    art = _artifact({"a": 90.0, "b": 50.0, "c": 30.0})
    diff = diff_top_zones(art, art, top_n=3)
    assert diff["n_added"] == 0
    assert diff["n_dropped"] == 0
    assert all(m["delta"] == 0 for m in diff["rank_moves"])


def test_diff_is_deterministic():
    v1 = _artifact({"a": 90.0, "b": 80.0, "c": 70.0})
    v2 = _artifact({"a": 70.0, "b": 90.0, "c": 80.0})
    # Pin generated_at so the comparison isolates the diff logic (the only
    # non-deterministic field is the wall-clock timestamp).
    kw = {"top_n": 3, "generated_at": "fixed"}
    assert diff_top_zones(v1, v2, **kw) == diff_top_zones(v1, v2, **kw)
