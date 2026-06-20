"""
ParkVision-Saathi — Gemini API Client
======================================

Serves LLM explanations for the /api/explain endpoint.

Priority chain (fast → slow → safe):
  1. CHECK CACHE  → data/processed/explanations_cache.json (instant, zero cost)
  2. CALL GEMINI  → gemini-1.5-flash with structured prompt from prompts.py
  3. FALLBACK     → deterministic rule-based text (never fails)

Returns:
  ExplainResponse: {zone_id, explanation, is_cached, source}

Usage:
  from ml.llm.gemini_client import GeminiClient

  client = GeminiClient()
  response = client.explain_zone(zone_data, traffic_data)

  # Or direct call:
  response = client.get_explanation(zone_id="8928308280fffff", hour=9, ...)
"""

from __future__ import annotations

import os
import json
import time
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────

PROJECT_ROOT   = Path(__file__).resolve().parent.parent.parent
CACHE_PATH     = PROJECT_ROOT / "data" / "processed" / "explanations_cache.json"
TRAFFIC_PATH   = PROJECT_ROOT / "data" / "enriched" / "traffic_context.json"
HOTSPOTS_PATH  = PROJECT_ROOT / "data" / "mock" / "hotspots.json"


# ─── Gemini Setup ────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL   = "gemini-2.5-flash"   # fast, cheap, sufficient for 3-4 sentence output

_gemini_client = None  # lazy-initialised (google.genai.Client)


def _get_gemini():
    """Lazy-init the Gemini client (google.genai). Returns None if SDK unavailable."""
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set — LLM calls will use fallback only")
        return None

    try:
        from google import genai  # type: ignore  (pip install google-genai)
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini client initialised with model: %s", GEMINI_MODEL)
        return _gemini_client
    except ImportError:
        logger.warning("google-genai not installed — run: pip install google-genai")
        return None
    except Exception as e:
        logger.warning("Gemini init failed: %s", e)
        return None


# ─── Cache ───────────────────────────────────────────────────────────────────

_cache: dict = {}
_cache_loaded: bool = False


def _load_cache() -> dict:
    """Load explanations_cache.json once into memory."""
    global _cache, _cache_loaded
    if _cache_loaded:
        return _cache

    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH) as f:
                _cache = json.load(f)
            logger.info("Loaded %d cached explanations from %s", len(_cache), CACHE_PATH)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Could not load explanations cache: %s", e)
            _cache = {}
    else:
        logger.info("No explanations cache found at %s", CACHE_PATH)
        _cache = {}

    _cache_loaded = True
    return _cache


def _save_to_cache(zone_id: str, entry: dict) -> None:
    """Persist a new explanation to the cache file."""
    global _cache
    _cache[zone_id] = entry
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump(_cache, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.warning("Could not save to explanations cache: %s", e)


# ─── Fallback Explanation ────────────────────────────────────────────────────

def _build_fallback(
    zone_id: str,
    station: str,
    congestion_impact: float,
    impact_band: str,
    top_violations: list[str],
    lane_hours_blocked: float,
    travel_time_ratio: float,
) -> str:
    """
    Rule-based fallback explanation when Gemini is unavailable.
    Uses no external data — always succeeds.
    """
    violation_str = ", ".join(top_violations[:2]) if top_violations else "illegal parking"
    ratio_text = (
        f" MapMyIndia traffic data confirms {travel_time_ratio:.1f}x travel time degradation."
        if travel_time_ratio > 1.2
        else ""
    )
    band_action = {
        "CRITICAL": "Immediate enforcement is required during morning peak hours.",
        "SEVERE":   "This zone should be prioritised in the next patrol cycle.",
        "MODERATE": "Schedule for routine patrol coverage.",
        "MINIMAL":  "Monitor and review if violation counts increase.",
    }.get(impact_band, "Enforce per standard protocol.")

    return (
        f"Zone {zone_id} ({station} PS) scores {congestion_impact:.1f}/100 on the "
        f"Congestion Impact Index — {impact_band} band. "
        f"Primary violations are {violation_str}, blocking an estimated "
        f"{lane_hours_blocked:.1f} lane-hours per day.{ratio_text} "
        f"{band_action}"
    )


# ─── Core Client ─────────────────────────────────────────────────────────────

class GeminiClient:
    """
    LLM explanation client for ParkVision-Saathi.

    Priority chain:
      cache → Gemini API → fallback

    Public methods:
      get_explanation(zone_id, hour, zone_data, traffic_data) → ExplainResponse dict
      explain_zone(zone_data, traffic_data, hour)             → ExplainResponse dict
      warm_cache(hotspot_list)                                → pre-generates explanations
    """

    def __init__(self):
        _load_cache()
        self._gemini = _get_gemini()

    # ── Cache check ──────────────────────────────────────────────────────────

    def _cache_hit(self, zone_id: str) -> dict | None:
        """Return cached entry if present, else None."""
        cache = _load_cache()
        if zone_id in cache:
            entry = cache[zone_id]
            return {
                "zone_id":     zone_id,
                "explanation": entry["explanation"],
                "is_cached":   True,
                "source":      "cache",
            }
        return None

    # ── Gemini call ──────────────────────────────────────────────────────────

    def _call_gemini(self, prompt: str, zone_id: str) -> str | None:
        """
        Call Gemini API with the structured prompt (google.genai SDK).
        Returns explanation text or None on failure.
        """
        client = _get_gemini()
        if client is None:
            return None

        try:
            from google.genai import types  # type: ignore
            t0 = time.monotonic()
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "You are a traffic enforcement analyst for Bengaluru Traffic Police. "
                        "Explain parking violation patterns and congestion impact using ONLY "
                        "the verified facts provided. Never invent statistics. "
                        "Be concise, data-driven, and actionable. "
                        "Use Indian English (e.g., 'lakh', 'auto-rickshaw')."
                    ),
                    temperature=0.2,         # factual, not creative
                    max_output_tokens=1024,  # gemini-2.5-flash uses thinking tokens; needs headroom
                    top_p=0.8,
                ),
            )
            elapsed = time.monotonic() - t0
            text = response.text.strip() if response.text else ""
            logger.info(
                "Gemini response for %s: %d chars in %.2fs",
                zone_id, len(text), elapsed
            )
            return text if text else None

        except Exception as e:
            logger.warning("Gemini call failed for zone %s: %s", zone_id, e)
            return None

    # ── Build prompt from zone data ──────────────────────────────────────────

    def _build_prompt(
        self,
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
        nearby_landmarks: str,
        travel_time_ratio: float,
    ) -> str:
        """Build the zone_explain prompt (imports from prompts.py)."""
        try:
            from ml.llm.prompts import build_zone_explain_prompt
            return build_zone_explain_prompt(
                zone_id=zone_id,
                station=station,
                congestion_impact=congestion_impact,
                impact_band=impact_band,
                top_violations=top_violations,
                total_records=total_records,
                peak_hour=peak_hour,
                lane_hours_blocked=lane_hours_blocked,
                lane_blockage_pct=lane_blockage_pct,
                intersection_impact_pct=intersection_impact_pct,
                nearby_landmarks=nearby_landmarks,
                travel_time_ratio=travel_time_ratio,
            )
        except ImportError:
            # Inline minimal prompt if prompts.py not on path
            return (
                f"Explain in 3-4 sentences why zone {zone_id} ({station} PS) with a "
                f"congestion impact score of {congestion_impact:.1f}/100 ({impact_band}) "
                f"needs enforcement attention. Top violations: {', '.join(top_violations[:2])}. "
                f"Lane-hours blocked: {lane_hours_blocked:.1f}. "
                f"Travel time ratio: {travel_time_ratio:.1f}x. "
                f"Be concise and actionable. No bullet points."
            )

    # ── Public API ───────────────────────────────────────────────────────────

    def get_explanation(
        self,
        zone_id: str,
        hour: int,
        station: str = "Unknown PS",
        congestion_impact: float = 50.0,
        impact_band: str = "MODERATE",
        top_violations: Optional[list[str]] = None,
        total_records: int = 0,
        peak_hour: int = 9,
        lane_hours_blocked: float = 0.0,
        lane_blockage_pct: float = 50.0,
        intersection_impact_pct: float = 30.0,
        nearby_landmarks: str = "not available",
        travel_time_ratio: float = 1.0,
    ) -> dict:
        """
        Main entry point: returns ExplainResponse dict.

        Priority: cache → Gemini → fallback
        Always returns a valid dict — never raises.
        """
        if top_violations is None:
            top_violations = ["WRONG PARKING"]

        # 1. Cache hit
        cached = self._cache_hit(zone_id)
        if cached:
            logger.debug("Cache hit for zone %s", zone_id)
            return cached

        # 2. Build prompt + call Gemini
        prompt = self._build_prompt(
            zone_id=zone_id,
            station=station,
            congestion_impact=congestion_impact,
            impact_band=impact_band,
            top_violations=top_violations,
            total_records=total_records,
            peak_hour=peak_hour,
            lane_hours_blocked=lane_hours_blocked,
            lane_blockage_pct=lane_blockage_pct,
            intersection_impact_pct=intersection_impact_pct,
            nearby_landmarks=nearby_landmarks,
            travel_time_ratio=travel_time_ratio,
        )

        gemini_text = self._call_gemini(prompt, zone_id)

        if gemini_text:
            # Save to cache so future calls are instant
            entry = {
                "zone_id":     zone_id,
                "hour":        hour,
                "explanation": gemini_text,
                "source":      "gemini",
                "is_cached":   False,
            }
            _save_to_cache(zone_id, entry)
            return {
                "zone_id":     zone_id,
                "explanation": gemini_text,
                "is_cached":   False,
                "source":      "gemini",
            }

        # 3. Fallback — always succeeds
        logger.info("Using fallback explanation for zone %s", zone_id)
        fallback_text = _build_fallback(
            zone_id=zone_id,
            station=station,
            congestion_impact=congestion_impact,
            impact_band=impact_band,
            top_violations=top_violations,
            lane_hours_blocked=lane_hours_blocked,
            travel_time_ratio=travel_time_ratio,
        )
        return {
            "zone_id":     zone_id,
            "explanation": fallback_text,
            "is_cached":   False,
            "source":      "fallback",
        }

    def explain_zone(
        self,
        zone_data: dict,
        traffic_data: Optional[dict] = None,
        hour: int = 9,
    ) -> dict:
        """
        Convenience wrapper: accepts dicts matching hotspot/traffic_context schema.

        zone_data keys (from HotspotItem):
            zone_id, station, congestion_impact, impact_band,
            violation_count, top_violation, estimated_lane_hours_blocked

        traffic_data keys (from TrafficContext / traffic_context.json):
            travel_time_ratio, nearby_pois, road_name
        """
        td = traffic_data or {}
        pois = td.get("nearby_pois", [])
        nearby_str = ", ".join(pois[:3]) if pois else "not available"

        return self.get_explanation(
            zone_id=zone_data.get("zone_id", "unknown"),
            hour=hour,
            station=zone_data.get("station", "Unknown PS"),
            congestion_impact=float(zone_data.get("congestion_impact", 50.0)),
            impact_band=zone_data.get("impact_band", "MODERATE"),
            top_violations=[zone_data.get("top_violation", "WRONG PARKING")],
            total_records=int(zone_data.get("violation_count", 0)),
            peak_hour=hour,
            lane_hours_blocked=float(zone_data.get("estimated_lane_hours_blocked", 0.0)),
            lane_blockage_pct=60.0,          # planner default until real components arrive
            intersection_impact_pct=30.0,    # planner default
            nearby_landmarks=nearby_str,
            travel_time_ratio=float(td.get("travel_time_ratio", 1.0)),
        )

    def warm_cache(self, hotspot_list: list[dict], traffic_ctx: dict, hour: int = 9) -> dict:
        """
        Pre-generate explanations for a list of hotspots.
        Used by generate_explanations.py for batch pre-warming.

        Returns: {zone_id: ExplainResponse}
        """
        results = {}
        total = len(hotspot_list)

        for i, spot in enumerate(hotspot_list, 1):
            zone_id = spot.get("zone_id", "unknown")
            tc = traffic_ctx.get(zone_id, {})
            print(f"  [{i:2d}/{total}] {zone_id} ({spot.get('station', '?')})... ", end="", flush=True)

            result = self.explain_zone(spot, tc, hour=hour)
            results[zone_id] = result
            print(f"{result['source']}")

            # Rate limit: avoid Gemini quota issues (15 RPM on free tier)
            if result["source"] == "gemini":
                time.sleep(4.5)

        return results
