"""
ParkVisionSaathi – Data Loading & Cleaning Pipeline
Loads the raw 298k-row CSV, cleans it, engineers base features,
and writes to SQLite for downstream ML modules.
"""

import os
import re
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_FILENAME = "jan to may police violation_anonymized791b166.csv"

# Candidate locations, in order of preference. The real anonymized dataset
# (298,450 rows, Bengaluru Nov-2023 to Apr-2024) lives in the repo's Dataset/
# folder, so that is tried first. A repo-local data/ copy and the user's
# ~/Downloads are kept as fallbacks for older setups.
CSV_CANDIDATES = [
    PROJECT_ROOT / "Dataset" / CSV_FILENAME,
    PROJECT_ROOT / "data" / CSV_FILENAME,
    Path.home() / "Downloads" / CSV_FILENAME,
]


def _resolve_csv_path() -> Path:
    """Return the first existing dataset CSV from the candidate locations."""
    for candidate in CSV_CANDIDATES:
        if candidate.exists():
            return candidate
    # Nothing found: surface a clear error listing every place we looked.
    searched = "\n  ".join(str(c) for c in CSV_CANDIDATES)
    raise FileNotFoundError(
        f"Could not find '{CSV_FILENAME}'. Looked in:\n  {searched}"
    )


CSV_PATH = _resolve_csv_path()
DB_PATH = PROJECT_ROOT / "data" / "parkvision.db"

# ── Column configuration ──────────────────────────────────────────────────────
COLS_TO_DROP = [
    "id", "description", "closed_datetime", "device_id", "created_by_id",
    "modified_datetime", "action_taken_timestamp",
    "data_sent_to_scita_timestamp", "updated_vehicle_number",
    "validation_timestamp", "vehicle_number", "offence_code",
    "data_sent_to_scita",
]

# Vehicle type → severity weight (heavier = more congestion impact)
VEHICLE_SEVERITY = {
    "TRUCK": 1.0, "HEAVY VEHICLE": 1.0,
    "BUS": 0.9, "MINI-BUS": 0.8, "MAXI-CAB": 0.8,
    "CAR": 0.6, "JEEP": 0.6, "VAN": 0.6,
    "AUTO": 0.5, "THREE WHEELER": 0.5, "E-RICKSHAW": 0.5,
    "SCOOTER": 0.3, "MOTORCYCLE": 0.3, "MOPED": 0.3,
    "CYCLE": 0.1, "BICYCLE": 0.1,
}

# Validation status → trust weight
VALIDATION_TRUST = {
    "approved": 1.0,
    "pending": 0.5,
    "rejected": 0.1,
}
DEFAULT_TRUST = 0.3  # for NaN / unknown

# Grid cell resolution (~500m at Bengaluru's latitude)
GRID_RESOLUTION = 0.005  # degrees


def extract_pincode(location: str) -> str:
    """Extract 6-digit pincode from location string."""
    if pd.isna(location):
        return None
    match = re.search(r"Pin[- ]?(\d{5,6})", location, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"(\d{6})", location)
    return match.group(1) if match else None


def make_grid_cell_id(lat: float, lon: float) -> str:
    """Create a grid cell identifier from lat/lon at ~500m resolution."""
    lat_cell = int(np.floor(lat / GRID_RESOLUTION))
    lon_cell = int(np.floor(lon / GRID_RESOLUTION))
    return f"{lat_cell}_{lon_cell}"


def get_time_bucket(hour: int) -> str:
    """Map hour to time bucket for DBSCAN."""
    if hour < 6:
        return "night_0_6"
    elif hour < 10:
        return "morning_6_10"
    elif hour < 16:
        return "midday_10_16"
    elif hour < 22:
        return "evening_16_22"
    else:
        return "night_22_24"


def load_and_clean():
    """Main ETL pipeline."""
    print(f"📂 Loading CSV from: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH, low_memory=False)
    print(f"   Raw shape: {df.shape}")

    # ── 1. Drop irrelevant columns ────────────────────────────────────────
    existing_drops = [c for c in COLS_TO_DROP if c in df.columns]
    df = df.drop(columns=existing_drops)
    print(f"   After column drop: {df.shape}")

    # ── 2. Parse datetime & extract time features ─────────────────────────
    df["created_datetime"] = pd.to_datetime(df["created_datetime"], utc=True, errors="coerce")
    df = df.dropna(subset=["created_datetime"])

    df["hour"] = df["created_datetime"].dt.hour
    df["day_of_week"] = df["created_datetime"].dt.dayofweek  # Mon=0
    df["month"] = df["created_datetime"].dt.month
    df["date"] = df["created_datetime"].dt.date
    df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
    df["is_peak"] = df["hour"].apply(lambda h: 1 if (8 <= h <= 10) or (17 <= h <= 19) else 0)
    df["time_bucket"] = df["hour"].apply(get_time_bucket)

    # ── 3. Extract pincode from location ──────────────────────────────────
    df["pincode"] = df["location"].apply(extract_pincode)

    # ── 4. Create grid cell IDs ───────────────────────────────────────────
    df["grid_cell_id"] = df.apply(lambda r: make_grid_cell_id(r["latitude"], r["longitude"]), axis=1)
    df["grid_lat"] = (np.floor(df["latitude"] / GRID_RESOLUTION) * GRID_RESOLUTION + GRID_RESOLUTION / 2)
    df["grid_lon"] = (np.floor(df["longitude"] / GRID_RESOLUTION) * GRID_RESOLUTION + GRID_RESOLUTION / 2)

    # ── 5. Map vehicle type → severity ────────────────────────────────────
    # Use updated_vehicle_type if available, else original vehicle_type
    df["vehicle_type_final"] = df["updated_vehicle_type"].fillna(df["vehicle_type"])
    df["vehicle_type_final"] = df["vehicle_type_final"].str.upper().str.strip()
    df["vehicle_severity"] = df["vehicle_type_final"].map(VEHICLE_SEVERITY).fillna(0.4)

    # ── 6. Map validation_status → trust weight ──────────────────────────
    df["validation_status_clean"] = df["validation_status"].str.lower().str.strip()
    df["validation_trust"] = df["validation_status_clean"].map(VALIDATION_TRUST).fillna(DEFAULT_TRUST)

    # ── 7. Clean violation_type ───────────────────────────────────────────
    # violation_type is a JSON-like list string; extract primary type
    def extract_primary_violation(vt):
        if pd.isna(vt):
            return "UNKNOWN"
        cleaned = re.sub(r'[\[\]""]', '', str(vt))
        types = [t.strip() for t in cleaned.split(",") if t.strip()]
        return types[0] if types else "UNKNOWN"

    df["primary_violation"] = df["violation_type"].apply(extract_primary_violation)

    # ── 8. Count columns for summary ──────────────────────────────────────
    print(f"\n✅ Cleaned DataFrame shape: {df.shape}")
    print(f"   Columns: {list(df.columns)}")
    print(f"   Date range: {df['created_datetime'].min()} → {df['created_datetime'].max()}")
    print(f"   Unique grid cells: {df['grid_cell_id'].nunique()}")
    print(f"   Unique pincodes: {df['pincode'].nunique()}")
    print(f"   Unique police stations: {df['police_station'].nunique()}")

    # ── 9. Write to SQLite ────────────────────────────────────────────────
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))

    # Convert datetime columns to string for SQLite
    df_save = df.copy()
    df_save["created_datetime"] = df_save["created_datetime"].astype(str)
    df_save["date"] = df_save["date"].astype(str)

    df_save.to_sql("violations", conn, if_exists="replace", index=False)
    print(f"\n💾 Saved {len(df_save)} rows to {DB_PATH} → 'violations' table")

    # Create useful indices
    conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_grid ON violations(grid_cell_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_hour ON violations(hour)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_date ON violations(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_grid_hour ON violations(grid_cell_id, hour)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_station ON violations(police_station)")
    conn.commit()
    print("   ✅ Indices created")

    conn.close()
    return df


if __name__ == "__main__":
    df = load_and_clean()
    print("\n🎉 Data ingestion complete!")
    print(f"   Sample grid_cell_ids: {df['grid_cell_id'].value_counts().head(5).to_dict()}")
    print(f"   Vehicle severity distribution:\n{df['vehicle_severity'].describe()}")
    print(f"   Validation trust distribution:\n{df['validation_trust'].value_counts()}")
