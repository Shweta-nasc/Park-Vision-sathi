"""
ParkVision-Saathi — LLM Prompt Templates
==========================================

Three grounded prompt templates for Gemini API:
  1. zone_explain   — Why is this zone a congestion risk hotspot?
  2. patrol_recommend — Where should patrol teams go and why?
  3. impact_explain  — What is the traffic impact of violations here?

DESIGN RULES (from Master Plan):
  - Every prompt injects EXACT numeric values — never let the LLM infer facts.
  - All facts are pre-computed and passed as template variables.
  - System instruction locks the LLM into "traffic enforcement analyst" persona.
  - Output length is constrained to keep UI panels compact.
  - Fallback: if Gemini fails, gemini_client.py serves from explanations_cache.json.

MVP Tier: Silver (LLM panel is Gold differentiator, but templates are Silver-level work).
"""

from __future__ import annotations
from typing import Optional

# ─── SHARED SYSTEM INSTRUCTION ──────────────────────────────────────────────
# Sent as the system/developer message with every Gemini call.
# Keeps the model grounded and prevents hallucination.

SYSTEM_INSTRUCTION = (
    "You are a traffic enforcement analyst for Bengaluru Traffic Police. "
    "You explain parking violation patterns and their congestion impact "
    "using ONLY the verified facts provided. "
    "Never invent statistics, road names, or landmarks not given in the prompt. "
    "Be concise, data-driven, and actionable. "
    "Use Indian English conventions (e.g., 'lakh', 'crore', 'auto-rickshaw')."
)


# ─── TEMPLATE 1: ZONE EXPLAIN ───────────────────────────────────────────────
# Used by: POST /api/explain  →  ExplainResponse.explanation
# Audience: Police control room officer viewing the zone detail panel.
# Injected data: zone_id, station, congestion_impact score, impact_band,
#   top violations, total records, peak hour, lane-hours blocked,
#   nearby landmarks (from Mappls Nearby API), traffic degradation ratio.

ZONE_EXPLAIN_TEMPLATE = """\
Based ONLY on the following verified facts, explain why this zone \
needs enforcement attention and how it impacts traffic flow.

VERIFIED FACTS (do not invent additional information):
- Zone ID: {zone_id}
- Police Station: {station}
- Congestion Impact Score: {congestion_impact}/100 ({impact_band})
- Top Violation Types: {top_violations}
- Total Violation Records (last 30 days): {total_records}
- Peak Violation Hour: {peak_hour}:00 IST
- Estimated Lane-Hours Blocked Daily: {lane_hours_blocked}
- Lane Blockage Component: {lane_blockage_pct}%
- Intersection Impact Component: {intersection_impact_pct}%
- Nearby Landmarks: {nearby_landmarks}
- MapMyIndia Traffic Context: Travel times are {travel_time_ratio}x \
the city average during peak hours

INSTRUCTIONS:
1. Start with the congestion impact score and band — this is the headline.
2. Explain WHY violations here choke traffic (use the component scores).
3. Mention the peak hour and what that means operationally.
4. If travel_time_ratio > 1.3, highlight it as external validation.
5. End with one actionable recommendation for enforcement.

Respond in exactly 3-4 sentences. No bullet points. No headers.\
"""


# ─── TEMPLATE 2: PATROL RECOMMEND ───────────────────────────────────────────
# Used by: Simulation panel / patrol allocation explanation.
# Audience: Police shift commander deciding team deployment.
# Injected data: list of allocated zones with scores, total teams,
#   covered/uncovered impact percentages, spillover zones.

PATROL_RECOMMEND_TEMPLATE = """\
Based ONLY on the following patrol allocation data, explain this \
deployment plan to a shift commander.

DEPLOYMENT FACTS (do not invent additional information):
- Available Patrol Teams: {num_teams}
- Time Bucket: {time_bucket}
- Total Zones Assessed: {total_zones}
- Congestion Impact Covered: {covered_impact_pct}%
- Congestion Impact Uncovered: {uncovered_impact_pct}%

TEAM ASSIGNMENTS:
{team_assignments_block}

UNCOVERED HIGH-RISK ZONES (top 3):
{uncovered_zones_block}

PREDICTED SPILLOVER:
{spillover_block}

INSTRUCTIONS:
1. Summarise the deployment: how many teams, covering what percentage \
of congestion impact.
2. Flag the most critical uncovered zone and why it matters.
3. Warn about the predicted spillover — where violations may migrate.
4. If covered_impact_pct < 60%, recommend requesting more teams.

Respond in 4-5 sentences. Plain language a field officer understands.\
"""


# ─── TEMPLATE 3: IMPACT EXPLAIN ─────────────────────────────────────────────
# Used by: Zone detail panel / congestion breakdown tooltip.
# Audience: Judges or city planners who want to understand the score.
# Injected data: full CongestionBreakdown schema fields.

IMPACT_EXPLAIN_TEMPLATE = """\
Based ONLY on the following congestion impact breakdown, explain \
how parking violations at this location affect traffic flow.

CONGESTION IMPACT BREAKDOWN (do not invent additional information):
- Zone: {zone_id} (Station: {station})
- Overall Congestion Impact Score: {congestion_impact}/100 ({impact_band})
- Lane Blockage Component: {lane_blockage_component:.0%} \
(road capacity lost due to parked vehicles)
- Intersection Impact Component: {intersection_impact_component:.0%} \
(junction throughput disruption)
- Traffic Degradation Component: {traffic_degradation_component:.0%} \
(MapMyIndia travel time ratio)
- Transit/Emergency Access Blockage: {access_blockage_component:.0%} \
(bus stops, hospitals, schools affected)
- Vehicle Size Impact: {vehicle_size_component:.0%} \
(heavy vehicle obstruction factor)
- Top Violation Types: {top_violations}
- Estimated Lane-Hours Blocked Daily: {lane_hours_blocked}
- Junction: {junction}
- Total Records: {total_records}

INSTRUCTIONS:
1. Lead with the overall score and what band it falls in.
2. Identify the TOP contributing component and explain its real-world effect.
3. If intersection_impact_component > 0.3, explain how junction \
throughput is reduced.
4. Mention estimated lane-hours blocked — translate to "X hours of \
one lane completely unusable per day."
5. Compare to city context if travel_time_ratio is available.

Respond in 3-4 sentences. Use concrete numbers from the facts above.\
"""


# ─── HELPER: FORMAT TEAM ASSIGNMENTS BLOCK ──────────────────────────────────

def format_team_assignments(allocations: list[dict]) -> str:
    """Format a list of PatrolAllocation dicts into a readable text block.

    Each allocation dict should have:
        team_id, zone_id, lat, lon, priority_rank,
        patrol_probability, congestion_impact
    """
    if not allocations:
        return "  (no teams allocated)"

    lines = []
    for a in allocations:
        lines.append(
            f"  Team {a['team_id']}: Zone {a['zone_id']} "
            f"(Impact: {a['congestion_impact']:.1f}, "
            f"Priority #{a['priority_rank']}, "
            f"Patrol Prob: {a['patrol_probability']:.0%})"
        )
    return "\n".join(lines)


def format_uncovered_zones(zones: list[dict], limit: int = 3) -> str:
    """Format top uncovered zones into a readable text block.

    Each zone dict should have:
        zone_id, congestion_impact, impact_band, station
    """
    if not zones:
        return "  (all high-risk zones covered)"

    lines = []
    for z in zones[:limit]:
        lines.append(
            f"  - {z['zone_id']} (Impact: {z['congestion_impact']:.1f} "
            f"[{z.get('impact_band', 'N/A')}], "
            f"Station: {z.get('station', 'unknown')})"
        )
    return "\n".join(lines)


def format_spillover(spillover_zones: list[dict], limit: int = 3) -> str:
    """Format predicted spillover zones into a readable text block.

    Each spillover dict should have:
        zone_id, original_impact, adjusted_impact, change_pct
    """
    if not spillover_zones:
        return "  (no significant spillover predicted)"

    lines = []
    for s in spillover_zones[:limit]:
        lines.append(
            f"  - {s['zone_id']}: Impact {s['original_impact']:.1f} → "
            f"{s['adjusted_impact']:.1f} "
            f"(+{s['change_pct']:.1f}% increase)"
        )
    return "\n".join(lines)


# ─── PUBLIC API: BUILD FINAL PROMPTS ─────────────────────────────────────────

def build_zone_explain_prompt(
    zone_id: str,
    station: str,
    congestion_impact: float,
    impact_band: str,
    top_violations: list[str],
    total_records: int,
    peak_hour: int,
    lane_hours_blocked: float,
    lane_blockage_pct: float,
    intersection_impact_pct: float,
    nearby_landmarks: str = "not available",
    travel_time_ratio: float = 1.0,
) -> str:
    """Build a grounded zone explanation prompt ready for Gemini.

    Returns the user-message string. Pair with SYSTEM_INSTRUCTION.
    """
    return ZONE_EXPLAIN_TEMPLATE.format(
        zone_id=zone_id,
        station=station,
        congestion_impact=f"{congestion_impact:.1f}",
        impact_band=impact_band,
        top_violations=", ".join(top_violations) if isinstance(top_violations, list) else top_violations,
        total_records=total_records,
        peak_hour=peak_hour,
        lane_hours_blocked=f"{lane_hours_blocked:.1f}",
        lane_blockage_pct=f"{lane_blockage_pct:.0f}",
        intersection_impact_pct=f"{intersection_impact_pct:.0f}",
        nearby_landmarks=nearby_landmarks,
        travel_time_ratio=f"{travel_time_ratio:.1f}",
    )


def build_patrol_recommend_prompt(
    num_teams: int,
    time_bucket: str,
    total_zones: int,
    covered_impact_pct: float,
    uncovered_impact_pct: float,
    allocations: list[dict],
    uncovered_zones: list[dict],
    spillover_zones: list[dict],
) -> str:
    """Build a grounded patrol recommendation prompt ready for Gemini.

    Returns the user-message string. Pair with SYSTEM_INSTRUCTION.
    """
    return PATROL_RECOMMEND_TEMPLATE.format(
        num_teams=num_teams,
        time_bucket=time_bucket,
        total_zones=total_zones,
        covered_impact_pct=f"{covered_impact_pct:.1f}",
        uncovered_impact_pct=f"{uncovered_impact_pct:.1f}",
        team_assignments_block=format_team_assignments(allocations),
        uncovered_zones_block=format_uncovered_zones(uncovered_zones),
        spillover_block=format_spillover(spillover_zones),
    )


def build_impact_explain_prompt(
    zone_id: str,
    station: str,
    congestion_impact: float,
    impact_band: str,
    lane_blockage_component: float,
    intersection_impact_component: float,
    traffic_degradation_component: float,
    access_blockage_component: float,
    vehicle_size_component: float,
    top_violations: list[str],
    lane_hours_blocked: float,
    junction: Optional[str],
    total_records: int,
) -> str:
    """Build a grounded congestion impact explanation prompt for Gemini.

    Returns the user-message string. Pair with SYSTEM_INSTRUCTION.
    """
    return IMPACT_EXPLAIN_TEMPLATE.format(
        zone_id=zone_id,
        station=station,
        congestion_impact=f"{congestion_impact:.1f}",
        impact_band=impact_band,
        lane_blockage_component=lane_blockage_component,
        intersection_impact_component=intersection_impact_component,
        traffic_degradation_component=traffic_degradation_component,
        access_blockage_component=access_blockage_component,
        vehicle_size_component=vehicle_size_component,
        top_violations=", ".join(top_violations) if isinstance(top_violations, list) else top_violations,
        lane_hours_blocked=f"{lane_hours_blocked:.1f}",
        junction=junction or "No named junction",
        total_records=total_records,
    )
