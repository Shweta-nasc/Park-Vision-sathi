"""Temporary verification for Task 6.1 (deleted after running)."""
import io
import json
import logging
import tempfile
from pathlib import Path

# Capture WARNING logs to confirm the missing-artifact warning fires.
buf = io.StringIO()
handler = logging.StreamHandler(buf)
handler.setLevel(logging.WARNING)
log = logging.getLogger("backend.app.data_loader")
log.addHandler(handler)
log.setLevel(logging.WARNING)

import backend.app.data_loader as dl
from backend.app.main import app  # noqa: F401  (exercises full app import/startup wiring)

# ── Verification 1: clean import + empty-universe fallback when artifact absent ──
dl.store.load()
assert isinstance(dl.store.congestion, dict)
assert len(dl.store.congestion) == 0, "expected empty congestion universe (no artifact)"
print("V1 import ok; zones =", len(dl.store.zones), "| congestion universe =", len(dl.store.congestion))
print("V1 sources =", dl.store.sources)

z0 = dl.store.zones[0]
print("V1 zone0 risk_score =", z0["risk_score"], "| congestion_impact =", z0["congestion_impact"])
assert z0["congestion_impact"] is None, "congestion_impact must be None (not aliased) when artifact absent"

warnings = buf.getvalue()
assert "zone_congestion_impact.json not found" in warnings, "expected missing-artifact warning (Req 14.3)"
print("V1 missing-artifact WARNING fired:", True)

# ── Verification 2: load a tiny fixture artifact via a custom data_dir ──
with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)
    (data_dir / "processed").mkdir(parents=True)
    (data_dir / "mock").mkdir(parents=True)
    # Minimal hotspots so a zone universe exists and the CIS join can be checked.
    (data_dir / "mock" / "hotspots.json").write_text(json.dumps([
        {"rank": 1, "zone_id": "8928308280fffff", "lat": 12.97, "lon": 77.57,
         "congestion_impact": 88.7, "impact_band": "CRITICAL", "violation_count": 100,
         "station": "Upparpet", "top_violation": "WRONG PARKING",
         "estimated_lane_hours_blocked": 34.2},
    ]))
    # Minimal CIS artifact keyed {h3_id: {time_bucket: breakdown}}.
    (data_dir / "processed" / "zone_congestion_impact.json").write_text(json.dumps({
        "8928308280fffff": {
            "all_day": {"zone_id": "8928308280fffff", "h3_id": "8928308280fffff",
                         "time_bucket": "all_day", "congestion_impact": 42.5,
                         "impact_band": "MODERATE"},
            "morning_peak": {"zone_id": "8928308280fffff", "h3_id": "8928308280fffff",
                              "time_bucket": "morning_peak", "congestion_impact": 55.0,
                              "impact_band": "SEVERE"},
        }
    }))
    fixture_store = dl.DataStore(data_dir=data_dir).load()
    assert "8928308280fffff" in fixture_store.congestion, "artifact zone not loaded"
    assert set(fixture_store.congestion["8928308280fffff"]) == {"all_day", "morning_peak"}
    z = fixture_store.zones_by_id["8928308280fffff"]
    print("V2 loaded congestion zones =", len(fixture_store.congestion),
          "| zone risk_score =", z["risk_score"], "| congestion_impact =", z["congestion_impact"])
    # CIS served from artifact's all_day rollup, distinct from the legacy risk_score (88.7).
    assert z["congestion_impact"] == 42.5, "congestion_impact must come from the artifact all_day rollup"
    assert z["risk_score"] != z["congestion_impact"], "congestion_impact must be distinct from risk_score"
    print("V2 congestion_impact sourced from artifact (42.5) is distinct from risk_score (88.7): True")

print("ALL VERIFICATIONS PASSED")
