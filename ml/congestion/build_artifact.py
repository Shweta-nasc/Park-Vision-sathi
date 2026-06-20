"""
ParkVision-Saathi — Congestion Impact Score (CIS): offline artifact builder
===========================================================================

The "QUANTIFY" pillar's **offline batch**. This module turns cleaned parking
violation records into the typed inputs the pure scoring core
(:mod:`ml.congestion.impact_score`) consumes: one :class:`ZoneAggregate` per
``(h3_id, time_bucket)`` cell plus the :class:`CorpusMaxima` taken across every
scored entry.

Scope (task 5.1): **aggregation + corpus maxima only.** The functions here read
cleaned violations, derive the H3 res-9 zone of each row, bucket rows into the
data-rich time windows, and reduce each ``(h3_id, time_bucket)`` group into a
``ZoneAggregate``. Scoring and writing the JSON artifact are deliberately left to
task 5.4, which composes this module's :func:`build_aggregates` seam with
:func:`ml.congestion.impact_score.score_zone`::

    from ml.congestion.impact_score import score_zone
    from ml.congestion.build_artifact import build_aggregates, h3_centroid

    aggregates, maxima = build_aggregates(violations_path, traffic_context_path)
    artifact: dict = {}
    for (h3_id, bucket), agg in aggregates.items():
        breakdown = score_zone(agg, maxima)
        lat, lon = h3_centroid(h3_id)
        ...  # attach lat/lon, serialize, nest under {h3_id: {bucket: ...}}

Hard architectural constraints honored here (Requirements 11.1, 11.2):

* Input is read from a **columnar (parquet) or JSON** file, or accepted directly
  as an in-memory :class:`pandas.DataFrame`. There is **no SQLite, no database
  connection**, and no dependency on the legacy ``data/load_and_clean.py`` ETL
  (whose ~500m custom lat/lon grid, 0.1-1.0 severity scale, and single
  ``primary_violation`` are incompatible with the H3 / per-category / 0.5-2.0
  obstruction design used here).
* The canonical spatial identifier is **H3 resolution 9** derived from
  latitude/longitude via the ``h3`` library; ``zone_id == h3_id`` and any legacy
  ``grid_cell_id`` carries the same H3 value (Requirements 9.2, 9.3).

Determinism (Requirement 14.5): every group reduction below is computed with
order-independent operations (counts, sums, means, ``any``) and every tie
(top-violation ranking, representative station) is broken deterministically by
value, so the resulting aggregates — and therefore the scores — are invariant
under any permutation of the input rows.
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from datetime import timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Union

import pandas as pd

try:  # h3 v4 (latlng_to_cell / cell_to_latlng); a hard project dependency.
    import h3
except ImportError as exc:  # pragma: no cover - surfaced as a clear setup error
    raise ImportError(
        "The 'h3' package is required by ml.congestion.build_artifact "
        "(H3 resolution-9 zoning). Install it with `pip install h3`."
    ) from exc

from ml.congestion.impact_score import CorpusMaxima, ZoneAggregate, score_zone

logger = logging.getLogger(__name__)

# ─── Spatial / temporal constants ────────────────────────────────────────────

# Canonical zone resolution. H3 res-9 cells are ~0.1 km² (~174 m edge), the
# granularity the design fixes for every consumer (Requirement 9.1).
H3_RESOLUTION = 9

# India Standard Time as a fixed +05:30 offset. The dataset's timestamps are
# UTC ("...+00"); they are parsed to UTC then converted to IST so the hour-of-day
# (and therefore the time bucket) reflects local Bengaluru time (Requirement 12.2).
IST = timezone(timedelta(hours=5, minutes=30))

# Temporal-cliff guard: the violation corpus is recorded on enforcement shifts and
# falls off a cliff after ~16:00 IST. Rows at/after this hour are EXCLUDED from
# both the time buckets and the all_day rollup so the demo never surfaces an
# empty-evening heatmap that misrepresents the data (design Non-Goals; Req 12.2).
TEMPORAL_CLIFF_HOUR_IST = 16

# Time buckets covering 00:00-16:00 IST as half-open [start, end) hour ranges.
# Anything outside these ranges (hour >= 16) maps to None and is dropped.
# (Requirements 12.1, 12.2)
TIME_BUCKET_BINS: tuple[tuple[int, int, str], ...] = (
    (0, 6, "night"),          # 00:00-05:59
    (6, 10, "morning_peak"),  # 06:00-09:59
    (10, 14, "midday"),       # 10:00-13:59
    (14, 16, "afternoon"),    # 14:00-15:59
)

# The day-level rollup label, aggregated across the four data-rich buckets above.
ALL_DAY = "all_day"

# ─── Violation-category vocabulary ───────────────────────────────────────────
#
# Raw violation strings (uppercase, as they appear in the dataset's
# ``violation_type`` list) mapped onto the design's count buckets. A single row
# can carry several violation strings; it contributes to a count bucket when ANY
# of its strings fall in that bucket (membership, not multiplicity).

MAIN_ROAD_VIOLATION = "PARKING IN A MAIN ROAD"
DOUBLE_PARK_VIOLATION = "DOUBLE PARKING"

JUNCTION_VIOLATIONS: frozenset[str] = frozenset(
    {
        "PARKING NEAR ROAD CROSSING",
        "PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS",
    }
)
ACCESS_VIOLATIONS: frozenset[str] = frozenset(
    {
        "PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC",
        "PARKING ON FOOTPATH",
    }
)

# A row's ``junction_name`` is a *named* junction unless it is one of these
# sentinels (matched case-insensitively after stripping).
NON_JUNCTION_SENTINELS: frozenset[str] = frozenset(
    {"", "NO JUNCTION", "NULL", "NAN", "NONE"}
)

# How many of the most frequent violation strings to retain per zone-bucket.
TOP_VIOLATIONS_LIMIT = 5

# ─── Vehicle obstruction weights (design's 0.5-2.0 scale) ────────────────────
#
# Vehicle type -> obstruction weight, the mean of which feeds the `vehicle_size`
# component. This is the master plan's VEHICLE_OBSTRUCTION map and is DISTINCT
# from ``data/load_and_clean.py``'s 0.1-1.0 ``vehicle_severity`` (a different
# scale for a different score). Two-wheelers ~0.5, car/van ~1.0, light/heavy
# goods ~1.5-1.8, buses ~2.0. Keys are uppercase; lookup is case-insensitive.
VEHICLE_OBSTRUCTION: dict[str, float] = {
    # Two-wheelers
    "SCOOTER": 0.50, "MOTOR CYCLE": 0.50, "MOTORCYCLE": 0.50, "MOPED": 0.50,
    "BIKE": 0.50, "TWO WHEELER": 0.50,
    # Cars / light passenger
    "CAR": 1.00, "JEEP": 1.00, "VAN": 1.00,
    "PASSENGER AUTO": 1.10, "AUTO": 1.10, "MAXI-CAB": 1.10, "MAXICAB": 1.10,
    # Light / heavy goods
    "LGV": 1.50, "TEMPO": 1.50, "SCHOOL VEHICLE": 1.50,
    "HGV": 1.80, "LORRY/GOODS VEHICLE": 1.80, "LORRY": 1.80,
    "GOODS VEHICLE": 1.80, "TANKER": 1.80, "TRUCK": 1.80,
    # Buses
    "BUS (BMTC/KSRTC)": 2.00, "PRIVATE BUS": 2.00, "BUS": 2.00,
}

# Neutral fallback for an unrecognised / missing vehicle type. Chosen as the
# car-class weight so unknown vehicles are treated as an ordinary car and the
# per-zone mean stays inside the design's [0.5, 2.0] band.
DEFAULT_VEHICLE_OBSTRUCTION = 1.00

# ─── Expected input column names (cleaned-violations schema) ─────────────────
#
# The cleaned columnar/JSON source is expected to carry these columns. Defaults
# match the raw dataset's headers so a lightly-cleaned export (or the raw CSV
# itself, once timestamps are UTC-parseable) can be fed in directly. The two
# vehicle columns mirror the dataset: ``updated_vehicle_type`` (a validator's
# correction) is preferred over ``vehicle_type`` when present.
LAT_COL = "latitude"
LON_COL = "longitude"
TIMESTAMP_COL = "created_datetime"
VIOLATION_TYPE_COL = "violation_type"
VEHICLE_TYPE_COL = "vehicle_type"
UPDATED_VEHICLE_TYPE_COL = "updated_vehicle_type"
JUNCTION_NAME_COL = "junction_name"
STATION_COL = "police_station"

# ─── Default on-disk locations (columnar/JSON only — never SQLite) ───────────
DEFAULT_VIOLATIONS_PATH = "data/processed/violations_clean.parquet"
DEFAULT_TRAFFIC_CONTEXT_PATH = "data/enriched/traffic_context.json"
DEFAULT_ARTIFACT_PATH = "data/processed/zone_congestion_impact.json"


# ─── H3 helpers ──────────────────────────────────────────────────────────────

def h3_id_for(lat: float, lon: float, resolution: int = H3_RESOLUTION) -> str:
    """Return the H3 cell id (default resolution 9) containing ``(lat, lon)``.

    Thin wrapper over the h3 v4 ``latlng_to_cell`` so the resolution and library
    call live in one place. ``zone_id``/``grid_cell_id`` are this same value
    elsewhere in the pipeline (Requirements 9.1, 9.2, 9.3).
    """
    return h3.latlng_to_cell(float(lat), float(lon), resolution)


def h3_centroid(h3_id: str) -> tuple[float, float]:
    """Return the ``(lat, lon)`` centroid of an H3 cell.

    Provided for the artifact-writing step (task 5.4): :class:`ZoneAggregate`
    carries no coordinates, so the centroid is recovered from the H3 id when the
    artifact's per-zone ``lat``/``lon`` are materialized.
    """
    lat, lon = h3.cell_to_latlng(h3_id)
    return float(lat), float(lon)


# ─── Time bucketing ──────────────────────────────────────────────────────────

def time_bucket_for_hour(hour: int) -> Optional[str]:
    """Map an IST hour-of-day to its time bucket, or ``None`` if outside 00:00-16:00.

    Returns one of ``night`` / ``morning_peak`` / ``midday`` / ``afternoon`` for
    hours in [0, 16), and ``None`` for hours >= 16 (the temporal-cliff guard) or
    any out-of-range hour. ``None`` rows are dropped before aggregation so they
    contribute to neither a bucket nor the ``all_day`` rollup. (Requirements
    12.1, 12.2)
    """
    if hour is None:
        return None
    for start, end, name in TIME_BUCKET_BINS:
        if start <= hour < end:
            return name
    return None


def _ist_hours(timestamps: pd.Series) -> pd.Series:
    """Parse a timestamp column to the IST hour-of-day (NaN where unparseable).

    Timestamps are parsed as UTC-aware (naive inputs are treated as UTC, matching
    the dataset's ``...+00`` convention) and converted to IST before the hour is
    read, so bucketing reflects local Bengaluru time (Requirement 12.2).
    """
    parsed = pd.to_datetime(timestamps, errors="coerce", utc=True)
    return parsed.dt.tz_convert(IST).dt.hour


# ─── Field parsers ───────────────────────────────────────────────────────────

def parse_violation_list(value: object) -> tuple[str, ...]:
    """Normalize a raw ``violation_type`` cell into an uppercase string tuple.

    Accepts the shapes the cleaned/raw source may carry and returns a tuple of
    de-duplicated-per-row-order uppercase violation strings:

    * an actual ``list``/``tuple`` (a columnar source may store a real array);
    * a JSON-encoded list string, e.g. ``'["WRONG PARKING","NO PARKING"]'``;
    * a loose bracketed/comma string as a last-resort fallback;
    * ``None`` / NaN / empty -> ``()``.

    Tokens are upper-cased and stripped so they line up with the category
    constants. Order within the tuple is irrelevant to every downstream count
    (membership tests and frequency counts are order-independent).
    """
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        items = value
    elif isinstance(value, float) and math.isnan(value):
        return ()
    else:
        text = str(value).strip()
        if not text or text.upper() in {"NULL", "NAN", "NONE", "[]"}:
            return ()
        try:
            parsed = json.loads(text)
            items = parsed if isinstance(parsed, (list, tuple)) else [parsed]
        except (ValueError, TypeError):
            # Fallback: strip brackets/quotes and split on commas.
            stripped = text.strip("[]")
            items = [tok.strip().strip('"').strip("'") for tok in stripped.split(",")]

    cleaned: list[str] = []
    for item in items:
        token = str(item).strip().strip('"').strip("'").upper()
        if token:
            cleaned.append(token)
    return tuple(cleaned)


def vehicle_obstruction_weight(vehicle_type: object) -> float:
    """Map a vehicle-type string to its obstruction weight on the 0.5-2.0 scale.

    Case-insensitive lookup in :data:`VEHICLE_OBSTRUCTION`; unknown, missing, or
    ``NULL``-like values fall back to :data:`DEFAULT_VEHICLE_OBSTRUCTION`.
    """
    if vehicle_type is None:
        return DEFAULT_VEHICLE_OBSTRUCTION
    if isinstance(vehicle_type, float) and math.isnan(vehicle_type):
        return DEFAULT_VEHICLE_OBSTRUCTION
    key = str(vehicle_type).strip().upper()
    if not key or key in {"NULL", "NAN", "NONE"}:
        return DEFAULT_VEHICLE_OBSTRUCTION
    return VEHICLE_OBSTRUCTION.get(key, DEFAULT_VEHICLE_OBSTRUCTION)


def _is_named_junction(value: object) -> bool:
    """True when ``junction_name`` denotes a real named junction (not a sentinel)."""
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return str(value).strip().upper() not in NON_JUNCTION_SENTINELS


# ─── Enrichment join (MapMyIndia travel-time ratio) ──────────────────────────

def load_travel_time_ratios(
    traffic_context_path: Union[str, Path] = DEFAULT_TRAFFIC_CONTEXT_PATH,
) -> dict[str, float]:
    """Load ``{h3_id: travel_time_ratio}`` from the MapMyIndia enrichment JSON.

    ``data/enriched/traffic_context.json`` is an object keyed by zone id, each
    value carrying a top-level ``travel_time_ratio`` (and a matching ``zone_id``
    field). This returns the flat ``h3_id -> ratio`` mapping the aggregator joins
    on. Only finite, strictly-positive ratios are kept; everything else is omitted
    so the lookup yields ``None`` and the scorer applies its deterministic 0.5
    fallback (Requirements 3.2, 3.3).

    A missing file is non-fatal: a warning is logged and an empty mapping is
    returned (every zone then defaults its traffic-degradation component).

    NOTE (data mismatch to surface): the enrichment file is currently keyed by
    canonical/sequential H3 *example* ids (e.g. ``8928308280fffff``) that do NOT
    correspond to the Bengaluru coordinates they store — real H3 res-9 cells
    derived from the violation lat/lon (e.g. ``8960145b553ffff`` for Upparpet) do
    not match these placeholder keys, so the join currently resolves to ``None``
    for live-derived zones. The join is keyed by ``h3_id`` per design; it will
    resolve once the enrichment is regenerated against true H3 res-9 ids (or the
    violations are zoned to the same scheme).
    """
    path = Path(traffic_context_path)
    if not path.exists():
        logger.warning(
            "Traffic-context enrichment not found at %s; "
            "travel_time_ratio will be unavailable for every zone.",
            path,
        )
        return {}

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    ratios: dict[str, float] = {}
    for zone_id, payload in raw.items():
        if not isinstance(payload, Mapping):
            continue
        ratio = payload.get("travel_time_ratio")
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
            continue
        if not math.isfinite(float(ratio)) or ratio <= 0:
            continue
        ratios[str(zone_id)] = float(ratio)
    return ratios


# ─── Reading the cleaned violations source ───────────────────────────────────

def read_violations(source: Union[str, Path, pd.DataFrame]) -> pd.DataFrame:
    """Load cleaned violations from a columnar/JSON path or pass through a DataFrame.

    ``source`` may be an in-memory :class:`pandas.DataFrame` (returned as a copy,
    the testable path) or a filesystem path to a ``.parquet``/``.json`` file. A
    SQLite/database source is intentionally **not** supported — the request and
    batch paths are database-free by design (Requirements 11.1, 11.2).
    """
    if isinstance(source, pd.DataFrame):
        return source.copy()

    path = Path(source)
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(path, lines=suffix == ".jsonl")
    raise ValueError(
        f"Unsupported violations source '{path}'. Expected a .parquet or .json "
        "columnar file, or an in-memory pandas DataFrame (no SQLite/database)."
    )


def prepare_violations(df: pd.DataFrame) -> pd.DataFrame:
    """Derive the per-row fields the aggregator groups on.

    Adds ``h3_id``, ``time_bucket``, parsed ``violation_tuple``, the four boolean
    category flags, ``obstruction_weight``, ``is_named_junction``, and a
    normalized ``station`` column, and **drops** rows that cannot be placed:
    missing/invalid coordinates, unparseable timestamps, and rows at/after the
    16:00 IST temporal cliff (their ``time_bucket`` is ``None``).

    The returned frame is the clean input to :func:`aggregate_zone_buckets`. Row
    order is preserved but irrelevant — all downstream reductions are
    order-independent (Requirement 14.5).
    """
    if df.empty:
        return df.copy()

    out = df.copy()

    # Coordinates -> H3 res-9 zone (drop rows without usable coordinates).
    out[LAT_COL] = pd.to_numeric(out.get(LAT_COL), errors="coerce")
    out[LON_COL] = pd.to_numeric(out.get(LON_COL), errors="coerce")
    out = out.dropna(subset=[LAT_COL, LON_COL])
    if out.empty:
        return out

    # IST hour -> time bucket (drop unparseable times and the post-cliff window).
    out["__ist_hour"] = _ist_hours(out[TIMESTAMP_COL])
    out = out.dropna(subset=["__ist_hour"])
    if out.empty:
        return out
    out["__ist_hour"] = out["__ist_hour"].astype(int)
    out["time_bucket"] = out["__ist_hour"].map(time_bucket_for_hour)
    out = out[out["time_bucket"].notna()].copy()
    if out.empty:
        return out

    out["h3_id"] = [
        h3_id_for(lat, lon) for lat, lon in zip(out[LAT_COL], out[LON_COL])
    ]

    # Violation strings -> category membership flags.
    out["violation_tuple"] = out[VIOLATION_TYPE_COL].map(parse_violation_list)
    out["is_main_road"] = out["violation_tuple"].map(
        lambda t: MAIN_ROAD_VIOLATION in t
    )
    out["is_double_park"] = out["violation_tuple"].map(
        lambda t: DOUBLE_PARK_VIOLATION in t
    )
    out["is_junction"] = out["violation_tuple"].map(
        lambda t: any(v in JUNCTION_VIOLATIONS for v in t)
    )
    out["is_access"] = out["violation_tuple"].map(
        lambda t: any(v in ACCESS_VIOLATIONS for v in t)
    )

    # Vehicle type -> obstruction weight (prefer the validator-corrected column).
    if UPDATED_VEHICLE_TYPE_COL in out.columns:
        updated = out[UPDATED_VEHICLE_TYPE_COL]
        base = out[VEHICLE_TYPE_COL] if VEHICLE_TYPE_COL in out.columns else updated
        chosen = updated.where(
            updated.notna()
            & (updated.astype(str).str.strip().str.upper() != "NULL"),
            base,
        )
    elif VEHICLE_TYPE_COL in out.columns:
        chosen = out[VEHICLE_TYPE_COL]
    else:
        chosen = pd.Series([None] * len(out), index=out.index)
    out["obstruction_weight"] = chosen.map(vehicle_obstruction_weight)

    # Named-junction flag.
    if JUNCTION_NAME_COL in out.columns:
        out["is_named_junction"] = out[JUNCTION_NAME_COL].map(_is_named_junction)
    else:
        out["is_named_junction"] = False

    # Representative station column (normalized to str/None).
    if STATION_COL in out.columns:
        out["station"] = out[STATION_COL]
    else:
        out["station"] = None

    return out


# ─── Group reduction ─────────────────────────────────────────────────────────

def _representative_station(stations: pd.Series) -> Optional[str]:
    """Most frequent non-null station in a group, ties broken by name (deterministic)."""
    values = [
        str(s).strip()
        for s in stations.dropna().tolist()
        if str(s).strip() and str(s).strip().upper() not in {"NULL", "NAN", "NONE"}
    ]
    if not values:
        return None
    counts = Counter(values)
    # Sort by descending frequency, then ascending name so the result never
    # depends on row order (Requirement 14.5).
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _top_violations(violation_tuples: Iterable[tuple[str, ...]]) -> tuple[str, ...]:
    """Most frequent violation strings in a group (deterministic, top-N).

    Frequencies are counted across every row's violation tuple, then ranked by
    descending count with name as the tie-break, so the ordering is invariant to
    input row order (Requirement 14.5).
    """
    counts: Counter[str] = Counter()
    for tup in violation_tuples:
        counts.update(tup)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return tuple(name for name, _ in ranked[:TOP_VIOLATIONS_LIMIT])


def _aggregate_slice(
    h3_id: str,
    time_bucket: str,
    group: pd.DataFrame,
    travel_time_ratio: Optional[float],
) -> ZoneAggregate:
    """Reduce one ``(h3_id, time_bucket)`` group of prepared rows to a ZoneAggregate.

    Every field is computed with an order-independent reduction (count / sum /
    mean / ``any`` / deterministic-tie ranking), so the aggregate is identical for
    any permutation of ``group`` (Requirement 14.5). Counts are membership counts:
    a row contributes at most 1 to each category regardless of how many matching
    strings it carries.
    """
    total_records = int(len(group))
    return ZoneAggregate(
        h3_id=h3_id,
        time_bucket=time_bucket,
        total_records=total_records,
        main_road_count=int(group["is_main_road"].sum()),
        double_park_count=int(group["is_double_park"].sum()),
        junction_violation_count=int(group["is_junction"].sum()),
        access_violation_count=int(group["is_access"].sum()),
        mean_vehicle_obstruction=float(group["obstruction_weight"].mean()),
        has_named_junction=bool(group["is_named_junction"].any()),
        travel_time_ratio=travel_time_ratio,
        station=_representative_station(group["station"]),
        top_violations=_top_violations(group["violation_tuple"]),
    )


def aggregate_zone_buckets(
    prepared: pd.DataFrame,
    travel_time_ratios: Optional[Mapping[str, float]] = None,
) -> dict[tuple[str, str], ZoneAggregate]:
    """Aggregate prepared rows into ``{(h3_id, time_bucket): ZoneAggregate}``.

    Produces one entry per observed ``(h3_id, time_bucket)`` plus one ``all_day``
    entry per ``h3_id`` rolled up across the four data-rich buckets. Because every
    entry is built from a non-empty group, ``(zone, time_bucket)`` cells with zero
    records are never emitted (Requirement 14.1) — there is no phantom zero-record
    aggregate to omit. ``travel_time_ratios`` is the ``h3_id -> ratio`` join from
    :func:`load_travel_time_ratios`; a missing key yields ``None`` (the scorer then
    defaults that component).

    Grouping is inherently order-independent and each reduction is too, so the
    output is invariant under row permutation (Requirement 14.5).
    """
    ratios = travel_time_ratios or {}
    aggregates: dict[tuple[str, str], ZoneAggregate] = {}
    if prepared.empty:
        return aggregates

    # Per (h3_id, time_bucket) aggregates.
    for (h3_id, bucket), group in prepared.groupby(["h3_id", "time_bucket"], sort=True):
        aggregates[(h3_id, bucket)] = _aggregate_slice(
            h3_id, bucket, group, ratios.get(h3_id)
        )

    # Per-zone all_day rollup over the same (already cliff-filtered) rows.
    for h3_id, group in prepared.groupby("h3_id", sort=True):
        aggregates[(h3_id, ALL_DAY)] = _aggregate_slice(
            h3_id, ALL_DAY, group, ratios.get(h3_id)
        )

    return aggregates


# ─── Corpus maxima ───────────────────────────────────────────────────────────

def compute_corpus_maxima(aggregates: Iterable[ZoneAggregate]) -> CorpusMaxima:
    """Compute the per-corpus maxima used to normalize the count-based components.

    Taken across **every** scored aggregate (the four time buckets and the
    ``all_day`` rollups), so dividing a zone's raw value by the corresponding
    maximum maps the corpus maximum to 1.0 in the scorer:

    * ``max_lane_load``       = max of (main_road * 1.0 + double_park * 2.0)
    * ``max_junction_load``   = max junction_violation_count
    * ``max_access_count``    = max access_violation_count
    * ``max_mean_obstruction``= max mean_vehicle_obstruction

    An empty corpus yields all-zero maxima; the scorer guards every denominator so
    a zero maximum still produces a finite component (Requirement 14.2).

    NOTE: the maxima intentionally include the ``all_day`` rollups, which are
    themselves scored/emitted entries, so an all_day total can set the maximum
    (its summed lane load typically exceeds any single bucket's). This matches
    "maxima across all scored ``(zone, bucket)`` aggregates".
    """
    aggregates = list(aggregates)
    if not aggregates:
        return CorpusMaxima(
            max_lane_load=0.0,
            max_junction_load=0.0,
            max_access_count=0.0,
            max_mean_obstruction=0.0,
        )

    return CorpusMaxima(
        max_lane_load=float(
            max(z.main_road_count * 1.0 + z.double_park_count * 2.0 for z in aggregates)
        ),
        max_junction_load=float(max(z.junction_violation_count for z in aggregates)),
        max_access_count=float(max(z.access_violation_count for z in aggregates)),
        max_mean_obstruction=float(max(z.mean_vehicle_obstruction for z in aggregates)),
    )


# ─── Public seam for the artifact writer (task 5.4) ──────────────────────────

def build_aggregates(
    violations: Union[str, Path, pd.DataFrame] = DEFAULT_VIOLATIONS_PATH,
    traffic_context_path: Union[str, Path] = DEFAULT_TRAFFIC_CONTEXT_PATH,
    *,
    travel_time_ratios: Optional[Mapping[str, float]] = None,
) -> tuple[dict[tuple[str, str], ZoneAggregate], CorpusMaxima]:
    """Read, prepare, aggregate, and compute corpus maxima in one call.

    This is the seam task 5.4 builds on: it returns the ``(h3_id, time_bucket) ->
    ZoneAggregate`` mapping (including ``all_day`` rollups, zero-record cells
    omitted) and the :class:`CorpusMaxima` over them, ready to feed
    :func:`ml.congestion.impact_score.score_zone`.

    ``violations`` is an in-memory DataFrame or a columnar/JSON path (no SQLite).
    The MapMyIndia ratios are taken from ``travel_time_ratios`` when supplied,
    otherwise loaded from ``traffic_context_path`` (a missing file -> empty join).
    """
    frame = read_violations(violations)
    prepared = prepare_violations(frame)

    ratios = (
        dict(travel_time_ratios)
        if travel_time_ratios is not None
        else load_travel_time_ratios(traffic_context_path)
    )

    aggregates = aggregate_zone_buckets(prepared, ratios)
    maxima = compute_corpus_maxima(aggregates.values())
    return aggregates, maxima


# ─── Artifact writer (task 5.4) ──────────────────────────────────────────────

def build_congestion_artifact(
    violations_path: Union[str, Path, pd.DataFrame] = DEFAULT_VIOLATIONS_PATH,
    traffic_context_path: Union[str, Path] = DEFAULT_TRAFFIC_CONTEXT_PATH,
    out_path: Union[str, Path] = DEFAULT_ARTIFACT_PATH,
) -> dict:
    """Score every aggregated zone-bucket and write the canonical CIS artifact.

    This is the offline batch's public entry point. It composes the
    :func:`build_aggregates` seam with the pure scorer
    (:func:`ml.congestion.impact_score.score_zone`) and writes the single
    artifact every backend consumer reads (Requirement 8.1):

    1. ``build_aggregates(...)`` -> ``{(h3_id, time_bucket): ZoneAggregate}`` plus
       the :class:`CorpusMaxima` over them (``all_day`` rollups included,
       zero-record cells already omitted upstream).
    2. ``score_zone(agg, maxima)`` -> :class:`CongestionBreakdown` per entry, then
       the zone's ``lat``/``lon`` are attached from :func:`h3_centroid` (the
       breakdown leaves them ``None`` because :class:`ZoneAggregate` carries no
       coordinates). The centroid is computed once per ``h3_id`` and reused across
       that zone's buckets.
    3. Each breakdown is serialized with Pydantic v2 ``model_dump()`` and nested as
       ``{h3_id: {time_bucket: <breakdown dict>}}`` — keyed first by ``h3_id`` then
       by ``time_bucket``, with an ``all_day`` entry per zone (Requirement 8.1).
    4. The nested structure is written as pretty-printed JSON to ``out_path``
       (parent directories created as needed) **and** returned in memory.

    Offline / deterministic / database-free (Requirements 7.x, 11.x): all inputs
    flow through :func:`build_aggregates`, which reads a columnar/JSON file or an
    in-memory DataFrame (never SQLite). Entries are written in sorted
    ``(h3_id, time_bucket)`` order so the file is byte-stable across runs on
    identical inputs. An empty input yields an empty artifact ``{}``
    (Requirement 14.1) — no phantom zones are written.

    :param violations_path: cleaned-violations ``.parquet``/``.json`` path, or an
        in-memory :class:`pandas.DataFrame` (the test-friendly path).
    :param traffic_context_path: MapMyIndia enrichment JSON
        (``h3_id -> travel_time_ratio``); a missing file defaults every zone's
        traffic-degradation component.
    :param out_path: destination for the JSON artifact; parent dirs are created.
    :returns: the in-memory ``{h3_id: {time_bucket: breakdown-dict}}`` artifact,
        identical to what was written to ``out_path``.
    """
    aggregates, maxima = build_aggregates(violations_path, traffic_context_path)

    artifact: dict[str, dict[str, dict]] = {}
    centroids: dict[str, tuple[float, float]] = {}

    # Sorted iteration gives deterministic, byte-stable key ordering (h3_id then
    # time_bucket) without relying on the upstream groupby insertion order.
    for (h3_id, time_bucket), agg in sorted(aggregates.items()):
        breakdown = score_zone(agg, maxima)

        # H3-centroid lat/lon (the scorer leaves these None); compute once per zone.
        if h3_id not in centroids:
            centroids[h3_id] = h3_centroid(h3_id)
        lat, lon = centroids[h3_id]
        located = breakdown.model_copy(update={"lat": lat, "lon": lon})

        artifact.setdefault(h3_id, {})[time_bucket] = located.model_dump()

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        json.dump(artifact, handle, indent=2, ensure_ascii=False)

    logger.info(
        "Wrote CIS artifact to %s: %d zone(s), %d (zone, bucket) entr(ies).",
        out,
        len(artifact),
        sum(len(buckets) for buckets in artifact.values()),
    )
    return artifact
