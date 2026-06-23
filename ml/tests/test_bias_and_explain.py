"""
Tests for Task 9 — ε-greedy patrol exploration + forecast SHAP explainability.
==============================================================================

* exploration: allocation sums to 1.0 ± 1e-9, exploration mass == ε, under-
  observed zones get more explore mass, ε=0 -> pure exploit, deterministic;
* SHAP: native TreeSHAP runs offline, contributions are finite and satisfy the
  additivity invariant (contrib + base == raw margin); per-zone top-k export.

Fixtures are CIS-independent. SHAP uses a small LightGBM booster trained in-test.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from ml.game.exploration import (
    EPSILON,
    epsilon_greedy_allocation,
    exploit_distribution,
    exploration_distribution,
)


# ─── ε-greedy exploration ────────────────────────────────────────────────────

def test_allocation_sums_to_one():
    risk = [90.0, 60.0, 30.0, 10.0, 5.0]
    counts = [500, 300, 120, 40, 8]
    alloc = epsilon_greedy_allocation(risk, counts, epsilon=0.10)
    assert sum(alloc) == pytest.approx(1.0, abs=1e-9)
    assert all(p >= 0 for p in alloc)


def test_exploration_mass_is_exactly_epsilon():
    risk = [90.0, 60.0, 30.0, 10.0]
    counts = [500, 300, 120, 40]
    eps = 0.10
    exploit = exploit_distribution(risk)
    alloc = epsilon_greedy_allocation(risk, counts, epsilon=eps)
    # The mass beyond (1-eps)*exploit is exactly eps (the explore contribution).
    explore_mass = sum(a - (1 - eps) * e for a, e in zip(alloc, exploit))
    assert explore_mass == pytest.approx(eps, abs=1e-9)
    assert EPSILON == 0.10


def test_under_observed_zone_gets_more_exploration():
    # Lowest observed count -> highest exploration weight.
    counts = [1000, 500, 50, 5]
    explore = exploration_distribution(counts)
    assert explore[-1] == max(explore)   # least-observed gets the most
    assert explore[0] == min(explore)    # most-observed gets the least
    assert sum(explore) == pytest.approx(1.0, abs=1e-9)


def test_epsilon_zero_is_pure_exploit():
    risk = [90.0, 60.0, 30.0, 10.0]
    counts = [5, 5, 5, 5]
    alloc = epsilon_greedy_allocation(risk, counts, epsilon=0.0)
    exploit = exploit_distribution(risk)
    assert alloc == pytest.approx(exploit)


def test_all_zero_risk_still_sums_to_one():
    # Exploit degenerates to uniform; allocation still sums to 1.0.
    alloc = epsilon_greedy_allocation([0.0, 0.0, 0.0], [10, 20, 30], epsilon=0.10)
    assert sum(alloc) == pytest.approx(1.0, abs=1e-9)


def test_empty_and_mismatched_inputs():
    assert epsilon_greedy_allocation([], []) == []
    with pytest.raises(ValueError):
        epsilon_greedy_allocation([1.0, 2.0], [1.0])


def test_allocation_is_deterministic():
    risk = [90.0, 60.0, 30.0, 10.0]
    counts = [500, 300, 120, 40]
    a = epsilon_greedy_allocation(risk, counts, epsilon=0.10)
    b = epsilon_greedy_allocation(risk, counts, epsilon=0.10)
    assert a == b


def test_datastore_patrol_allocation_endpoint():
    from fastapi.testclient import TestClient
    from backend.app.main import app

    with TestClient(app) as client:
        r = client.get("/game/patrol_allocation?epsilon=0.10")
        assert r.status_code == 200
        body = r.json()
        assert body["exploration_pct"] == pytest.approx(10.0)
        assert "honest_limitation" in body
        if body["zones"]:
            total = sum(z["patrol_probability_explore"] for z in body["zones"])
            assert total == pytest.approx(1.0, abs=1e-9)
            # exploit-only field is still present and unchanged in shape.
            assert "patrol_probability" in body["zones"][0]


# ─── forecast SHAP explainability ────────────────────────────────────────────

def _tiny_booster(n_features=6, seed=0):
    import lightgbm as lgb

    rng = np.random.default_rng(seed)
    X = rng.random((300, n_features))
    # target depends on a couple of features (CIS-independent, arbitrary).
    y = (3 * X[:, 0] + 2 * X[:, 2] + rng.normal(0, 0.1, size=300)).clip(0, None)
    params = dict(objective="poisson", num_leaves=15, min_data_in_leaf=10,
                  learning_rate=0.1, seed=seed, num_threads=1, deterministic=True, verbose=-1)
    booster = lgb.train(params, lgb.Dataset(X, label=y), num_boost_round=30)
    return booster, X


def test_shap_contributions_finite_and_additive():
    from ml.forecast.forecast_explain import shap_contributions

    booster, X = _tiny_booster()
    contrib = shap_contributions(booster, X[:20])
    assert contrib.shape == (20, X.shape[1] + 1)
    assert np.all(np.isfinite(contrib))
    # TreeSHAP additivity: contributions + base == raw margin.
    raw = booster.predict(X[:20], raw_score=True)
    assert np.allclose(contrib.sum(axis=1), raw, atol=1e-5)


def test_build_explanations_top_k_and_finite():
    import pandas as pd
    from ml.forecast.forecast_explain import build_explanations

    booster, X = _tiny_booster()
    feats = [f"f{i}" for i in range(X.shape[1])]
    future = pd.DataFrame(X[:10], columns=feats)
    future["h3_id"] = [f"z{i:02d}" for i in range(10)]
    future["pred"] = np.clip(booster.predict(X[:10]), 0, None)

    report = build_explanations(booster, future, feats, top_k=3)
    assert report["n_zones"] == 10
    assert report["method"] == "native_pred_contrib"
    for zid, rec in report["zones"].items():
        assert len(rec["top_contributors"]) <= 3
        assert np.isfinite(rec["base_value"])
        for c in rec["top_contributors"]:
            assert np.isfinite(c["contribution"])
            assert c["feature"] in feats
        # top contributors are ordered by descending |contribution|.
        contribs = [abs(c["contribution"]) for c in rec["top_contributors"]]
        assert contribs == sorted(contribs, reverse=True)


def test_forecast_v2_exports_shap_sidecar(tmp_path):
    import h3
    import pandas as pd
    from ml.forecast.build_h3_forecast_v2 import build_h3_forecast_v2

    # Valid-H3 synthetic daily counts spanning the split window.
    rng = np.random.default_rng(3)
    cells = [h3.latlng_to_cell(12.95 + i * 0.01, 77.55 + i * 0.01, 9) for i in range(14)]
    dates = pd.date_range("2024-01-01", "2024-04-15", freq="D")
    rows = [{"h3_id": c, "date": d, "violation_count": int(rng.poisson(2 + zi % 4))}
            for zi, c in enumerate(cells) for d in dates]
    daily = pd.DataFrame(rows)

    out = tmp_path / "forecasts_v2.json"
    explain_out = tmp_path / "forecast_explanations.json"
    build_h3_forecast_v2(daily=daily, adjacency={}, observations={},
                         out_path=out, explain_out=explain_out)

    assert explain_out.exists()
    expl = json.loads(explain_out.read_text(encoding="utf-8"))
    assert expl["n_zones"] == 14
    assert "neighbor_spatial_lag" in expl["feature_names"]
    assert "road_size_proxy" in expl["feature_names"]
    for rec in expl["zones"].values():
        assert np.isfinite(rec["base_value"])
        assert all(np.isfinite(c["contribution"]) for c in rec["top_contributors"])
