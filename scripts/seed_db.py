"""
seed_db.py – Generate a realistic synthetic parkvision.db for testing.

Run FIRST before any other script:
    python scripts/seed_db.py

Creates ~300k violation rows covering Nov 2023 – May 2024 for Bengaluru.
Temporal bias is intentional: 96% of data falls in hours 0–15 (matches
the real dataset's enforcement shift pattern).
"""

import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import date, timedelta

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

RNG = np.random.default_rng(42)

# ── Bengaluru bounding box ──────────────────────────────────────────────
LAT_MIN, LAT_MAX = 12.87, 13.07
LON_MIN, LON_MAX = 77.47, 77.72

# ── Known junctions (realistic Bengaluru locations) ──────────────────────
JUNCTIONS = [
    "Silk Board Junction", "Marathahalli Bridge", "Hebbal Flyover",
    "KR Puram Junction", "Electronic City Flyover", "Tin Factory",
    "Banashankari", "Jayanagar 4th Block", "Koramangala 5th Block",
    "Whitefield Main Road", "Indiranagar 100ft Road", "MG Road",
    "Brigade Road", "Ulsoor Lake Road", "Nagawara Junction",
    "Yeshwantpur Junction", "Rajajinagar", "Malleshwaram",
    "Vijayanagar", "Bannerghatta Road", "No Junction",
]

# ── Grid cell centres (500m grid) ──────────────────────────────────────
N_CELLS = 120
GRID_LATS = RNG.uniform(LAT_MIN, LAT_MAX, N_CELLS)
GRID_LONS = RNG.uniform(LON_MIN, LON_MAX, N_CELLS)
CELL_IDS = [f"CELL_{i:04d}" for i in range(N_CELLS)]

N_ROWS = 300_000
print(f"Generating {N_ROWS:,} synthetic violations …")

# ── Date range ──────────────────────────────────────────────────────────
start = date(2023, 11, 1)
end   = date(2024, 5, 31)
days  = (end - start).days + 1
date_pool = [str(start + timedelta(d)) for d in range(days)]

# ── Temporal bias: 96% of violations in hours 0–15 ──────────────────────
hour_weights = np.array([
    3, 2, 1, 1, 1, 2,   # 0–5   (night)
    8, 15, 20, 20, 18, 15,  # 6–11  (morning peak)
    14, 12, 10, 8,       # 12–15 (midday)
    1, 1, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5,  # 16–23 (very sparse)
])
hour_weights /= hour_weights.sum()

cell_idx   = RNG.integers(0, N_CELLS, N_ROWS)
hours      = RNG.choice(24, N_ROWS, p=hour_weights)
dates      = RNG.choice(date_pool, N_ROWS)

lats = GRID_LATS[cell_idx] + RNG.normal(0, 0.001, N_ROWS)
lons = GRID_LONS[cell_idx] + RNG.normal(0, 0.001, N_ROWS)

# day_of_week / month from date
date_series = pd.to_datetime(dates)
day_of_week = date_series.dayofweek.values   # 0=Mon
month       = date_series.month.values
is_weekend  = (day_of_week >= 5).astype(int)
is_peak     = np.isin(hours, [8,9,10,17,18,19]).astype(int)

# 21 junctions: first 20 get equal share of 70%, last ("No Junction") gets 30%
j_probs = [0.035] * 20 + [0.30]
j_probs = [p / sum(j_probs) for p in j_probs]   # normalise to exactly 1
junction_idx = RNG.choice(len(JUNCTIONS), N_ROWS, p=j_probs)
junction_names = np.array(JUNCTIONS)[junction_idx]
junction_names_out = np.where(junction_names == "No Junction", None, junction_names)

vehicle_severity  = RNG.uniform(0.1, 1.0, N_ROWS).round(4)
validation_trust  = RNG.uniform(0.3, 1.0, N_ROWS).round(4)

df = pd.DataFrame({
    "latitude":         lats.round(6),
    "longitude":        lons.round(6),
    "grid_lat":         GRID_LATS[cell_idx].round(6),
    "grid_lon":         GRID_LONS[cell_idx].round(6),
    "grid_cell_id":     np.array(CELL_IDS)[cell_idx],
    "date":             dates,
    "hour":             hours,
    "day_of_week":      day_of_week,
    "month":            month,
    "is_weekend":       is_weekend,
    "is_peak":          is_peak,
    "junction_name":    junction_names_out,
    "vehicle_severity": vehicle_severity,
    "validation_trust": validation_trust,
})

conn = sqlite3.connect(str(DB_PATH))
df.to_sql("violations", conn, if_exists="replace", index=False)
conn.execute("CREATE INDEX IF NOT EXISTS idx_v_cell ON violations(grid_cell_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_v_hour ON violations(hour)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_v_date ON violations(date)")
conn.commit()
conn.close()

print(f"✅  DB written → {DB_PATH}")
print(f"    Rows: {len(df):,}  |  Cells: {N_CELLS}  |  Date range: {sorted(dates)[0]} – {sorted(dates)[-1]}")
print(f"    Hour distribution (h16+): {(hours >= 16).sum():,} rows ({(hours>=16).mean()*100:.1f}%)")
