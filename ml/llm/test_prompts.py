"""
Verification script for ml/llm/prompts.py — Stage 1
Run: python -m ml.llm.test_prompts  (from project root)
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from ml.llm.prompts import (
    SYSTEM_INSTRUCTION,
    ZONE_EXPLAIN_TEMPLATE,
    PATROL_RECOMMEND_TEMPLATE,
    IMPACT_EXPLAIN_TEMPLATE,
    build_zone_explain_prompt,
    build_patrol_recommend_prompt,
    build_impact_explain_prompt,
    format_team_assignments,
    format_uncovered_zones,
    format_spillover,
)

# ─── Test Data ───────────────────────────────────────────────────────────────

SAMPLE_ZONE = dict(
    zone_id="8928308280fffff",
    station="Koramangala Traffic PS",
    congestion_impact=78.3,
    impact_band="CRITICAL",
    top_violations=["DOUBLE PARKING", "PARKING IN A MAIN ROAD", "WRONG PARKING"],
    total_records=142,
    peak_hour=9,
    lane_hours_blocked=18.5,
    lane_blockage_pct=82,
    intersection_impact_pct=45,
    nearby_landmarks="Forum Mall, Koramangala Bus Stop, Sony World Junction",
    travel_time_ratio=1.7,
)

SAMPLE_ALLOCATIONS = [
    {"team_id": 1, "zone_id": "8928308280fffff", "lat": 12.93, "lon": 77.62,
     "priority_rank": 1, "patrol_probability": 0.35, "congestion_impact": 78.3},
    {"team_id": 2, "zone_id": "892830828ffffff", "lat": 12.97, "lon": 77.59,
     "priority_rank": 2, "patrol_probability": 0.28, "congestion_impact": 65.1},
]

SAMPLE_UNCOVERED = [
    {"zone_id": "892830829ffffff", "congestion_impact": 71.2, "impact_band": "SEVERE", "station": "HSR Layout PS"},
]

SAMPLE_SPILLOVER = [
    {"zone_id": "892830830ffffff", "original_impact": 32.5, "adjusted_impact": 41.8, "change_pct": 28.6},
]

# ─── Unit Verification ──────────────────────────────────────────────────────

def test_system_instruction():
    assert len(SYSTEM_INSTRUCTION) > 50, "System instruction too short"
    assert "ONLY" in SYSTEM_INSTRUCTION or "only" in SYSTEM_INSTRUCTION, \
        "System instruction must constrain the LLM to provided facts"
    assert "Bengaluru" in SYSTEM_INSTRUCTION, "Must mention Bengaluru context"
    print("✅ SYSTEM_INSTRUCTION: valid, grounding constraint present")

def test_templates_have_placeholders():
    """All three templates must have {zone_id} or similar placeholders."""
    assert "{zone_id}" in ZONE_EXPLAIN_TEMPLATE, "zone_explain missing {zone_id}"
    assert "{congestion_impact}" in ZONE_EXPLAIN_TEMPLATE, "zone_explain missing {congestion_impact}"
    assert "{num_teams}" in PATROL_RECOMMEND_TEMPLATE, "patrol_recommend missing {num_teams}"
    assert "{congestion_impact}" in IMPACT_EXPLAIN_TEMPLATE, "impact_explain missing {congestion_impact}"
    print("✅ All 3 templates have required placeholders")

def test_zone_explain_prompt():
    prompt = build_zone_explain_prompt(**SAMPLE_ZONE)
    # Must contain injected values
    assert "78.3" in prompt, "Congestion impact score not injected"
    assert "CRITICAL" in prompt, "Impact band not injected"
    assert "DOUBLE PARKING" in prompt, "Top violations not injected"
    assert "142" in prompt, "Total records not injected"
    assert "9" in prompt, "Peak hour not injected"
    assert "18.5" in prompt, "Lane hours blocked not injected"
    assert "1.7" in prompt, "Travel time ratio not injected"
    assert "Koramangala" in prompt, "Station name not injected"
    assert "Forum Mall" in prompt, "Landmarks not injected"
    # Anti-hallucination guardrails
    assert "do not invent" in prompt.lower(), "Missing anti-hallucination instruction"
    print("✅ build_zone_explain_prompt: all values injected, anti-hallucination present")
    print(f"   → Prompt length: {len(prompt)} chars")

def test_patrol_recommend_prompt():
    prompt = build_patrol_recommend_prompt(
        num_teams=2,
        time_bucket="morning_peak",
        total_zones=150,
        covered_impact_pct=48.5,
        uncovered_impact_pct=51.5,
        allocations=SAMPLE_ALLOCATIONS,
        uncovered_zones=SAMPLE_UNCOVERED,
        spillover_zones=SAMPLE_SPILLOVER,
    )
    assert "2" in prompt, "num_teams not injected"
    assert "morning_peak" in prompt, "time_bucket not injected"
    assert "48.5" in prompt, "covered_impact_pct not injected"
    assert "Team 1" in prompt, "Team assignments not formatted"
    assert "HSR Layout" in prompt, "Uncovered zones not formatted"
    assert "28.6" in prompt, "Spillover change_pct not formatted"
    assert "do not invent" in prompt.lower(), "Missing anti-hallucination instruction"
    print("✅ build_patrol_recommend_prompt: all values injected, spillover present")
    print(f"   → Prompt length: {len(prompt)} chars")

def test_impact_explain_prompt():
    prompt = build_impact_explain_prompt(
        zone_id="8928308280fffff",
        station="Koramangala Traffic PS",
        congestion_impact=78.3,
        impact_band="CRITICAL",
        lane_blockage_component=0.82,
        intersection_impact_component=0.45,
        traffic_degradation_component=0.60,
        access_blockage_component=0.30,
        vehicle_size_component=0.25,
        top_violations=["DOUBLE PARKING", "PARKING IN A MAIN ROAD"],
        lane_hours_blocked=18.5,
        junction="Sony World Junction",
        total_records=142,
    )
    assert "78.3" in prompt, "Congestion impact not injected"
    assert "82%" in prompt, "Lane blockage component not formatted as %"
    assert "45%" in prompt, "Intersection impact not formatted as %"
    assert "Sony World Junction" in prompt, "Junction not injected"
    assert "do not invent" in prompt.lower(), "Missing anti-hallucination instruction"
    print("✅ build_impact_explain_prompt: all components injected as percentages")
    print(f"   → Prompt length: {len(prompt)} chars")

def test_helpers_edge_cases():
    # Empty inputs
    assert "(no teams allocated)" in format_team_assignments([])
    assert "(all high-risk zones covered)" in format_uncovered_zones([])
    assert "(no significant spillover predicted)" in format_spillover([])
    print("✅ Helper formatters handle empty inputs gracefully")

def test_no_hallucination_risk():
    """Verify templates never ask the LLM to 'imagine', 'assume', or 'guess'."""
    all_templates = ZONE_EXPLAIN_TEMPLATE + PATROL_RECOMMEND_TEMPLATE + IMPACT_EXPLAIN_TEMPLATE
    danger_words = ["imagine", "assume", "guess", "suppose", "make up", "create a story"]
    for word in danger_words:
        assert word not in all_templates.lower(), \
            f"Template contains hallucination-risk word: '{word}'"
    print("✅ No hallucination-risk language in any template")


# ─── Run All ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🧪 Stage 1 Verification: ml/llm/prompts.py\n" + "=" * 50)
    test_system_instruction()
    test_templates_have_placeholders()
    test_zone_explain_prompt()
    test_patrol_recommend_prompt()
    test_impact_explain_prompt()
    test_helpers_edge_cases()
    test_no_hallucination_risk()
    print("\n" + "=" * 50)
    print("🎉 ALL TESTS PASSED — Stage 1 complete")
    print("=" * 50)
