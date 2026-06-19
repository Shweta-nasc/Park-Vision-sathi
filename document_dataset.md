# ParkVisionSaathi AI - Dataset Deep Dive and Hackathon Blueprint

This document explains the local parking-violation CSV in enough detail to design, pitch, and build a hackathon project around the theme:

**Theme:** Poor Visibility on Parking-Induced Congestion

**Problem direction:** How can AI-driven parking intelligence detect illegal parking hotspots and quantify their likely impact on traffic flow to enable targeted enforcement?

The dataset is strong for illegal-parking visibility, hotspot ranking, temporal demand forecasting, officer/station workload analysis, and enforcement-priority simulation. It does **not** directly contain traffic speed, queue length, road capacity, legal parking supply, fine payment outcomes, or patrol route history, so any "congestion impact" must be presented as a defensible proxy unless external traffic or road-network data is added.

---

## 1. Dataset Identity

| Item | Value |
|---|---:|
| File | `jan to may police violation_anonymized791b166.csv` |
| File size | 105 MB |
| Rows | 298,450 |
| Columns | 24 |
| Duplicate full rows | 0 |
| Duplicate `id` values | 0 |
| Geographic area | Bengaluru region, Karnataka, India |
| Coordinate validity | 298,450 / 298,450 rows have valid latitude and longitude |
| Event time coverage, UTC | 2023-11-09 19:11:46 to 2024-04-08 17:30:46 |
| Event time coverage, Bengaluru local time | 2023-11-10 00:41:46 IST to 2024-04-08 23:00:46 IST |
| Unique local dates | 151 |
| Important filename caveat | The filename says "jan to may", but the actual `created_datetime` range is Nov 2023 to Apr 2024. |

### Row Granularity

Each row is one recorded traffic/parking violation event. A row may contain multiple violation labels because `violation_type` and `offence_code` are list-like strings. Example:

```text
violation_type = ["WRONG PARKING","PARKING NEAR ROAD CROSSING"]
offence_code   = [112,104]
```

The first violation aligns with the first offence code, the second violation aligns with the second offence code, and so on.

### What The Dataset Represents

The dataset is an anonymized operational record of police/camera/device captured violations. It includes:

- Location: latitude, longitude, text address, pincode, junction name, police station.
- Time: created, modified, validation, and SCITA-transfer timestamps.
- Violation detail: multi-label violation names and offence codes.
- Vehicle detail: anonymized vehicle number and vehicle type.
- Workflow detail: validation status, updated vehicle fields, data-sent flags, device/user identifiers.

---

## 2. Executive Findings

1. **Illegal parking is highly spatially concentrated.** Top hotspots cluster around Upparpet/Gandhi Nagar, City Market/KR Market, Shivajinagar/Safina Plaza, HAL Old Airport/Kadubisanahalli, Rajajinagar, Vijayanagara, Malleshwaram, and KR Puram.

2. **The data is almost entirely parking-relevant.** The dominant labels are `WRONG PARKING` and `NO PARKING`. Several labels directly indicate congestion risk, such as parking in a main road, footpath parking, double parking, parking near crossings, and parking near traffic lights.

3. **The strongest demo angle is a "Parking Congestion Risk Index."** Since there is no direct speed/traffic-flow column, the project should estimate congestion impact through a proxy score combining violation density, violation severity, junction/main-road context, repeat vehicles, vehicle type, time of day, and validation confidence.

4. **Validation status is useful but delayed/incomplete.** 173,196 rows have validation status. Among those, 66.63% are approved and 28.73% rejected. Recent months have much more missing validation, so models must treat validation as workflow-censored data.

5. **The dataset is strong enough for a judge-facing map demo.** Latitude/longitude is complete, pincode extraction works for 98.98% of rows, and named junctions exist for about half the dataset.

6. **Temporal patterns are operationally biased.** In IST, most rows are created from midnight to early afternoon, especially 08:00-11:00. That may reflect enforcement shifts or system creation time, not necessarily true congestion time. Present this carefully.

---

## 3. Column Dictionary

| Column | Observed Type | Missing | Meaning | Modeling / Product Use |
|---|---:|---:|---|---|
| `id` | string | 0 | Unique anonymized violation id. | Primary key for deduping and joins. |
| `latitude` | numeric string | 0 | Event latitude. | Map points, grids, clustering, nearest road segment. |
| `longitude` | numeric string | 0 | Event longitude. | Map points, grids, clustering, nearest road segment. |
| `location` | string | 3,041 | Human-readable reverse-geocoded address. | Pincode extraction, locality labels, judge-friendly explanations. |
| `vehicle_number` | string | 0 | Anonymized vehicle identifier. | Repeat-vehicle features. Do not claim real identity. |
| `vehicle_type` | string | 0 | Original vehicle class. | Obstruction severity, vehicle mix, segment risk. |
| `description` | string | 298,450 | Empty in this dataset. | Drop from MVP. |
| `violation_type` | list-like string | 0 | One or more violation names. | Core label, severity scoring, multi-hot features. |
| `offence_code` | list-like string | 0 | One or more offence codes aligned with `violation_type`. | Stable numeric taxonomy. |
| `created_datetime` | timestamp string | 0 | Event/system creation timestamp, UTC. | Time features, forecasting, trend analysis. |
| `closed_datetime` | timestamp string | 298,450 | Empty in this dataset. | Drop from MVP. |
| `modified_datetime` | timestamp string | 0 | Last modified timestamp, UTC. | Workflow latency, data correction detection. |
| `device_id` | string | 0 | Anonymized capture device id. | Device coverage, device bias, QA. |
| `created_by_id` | string | 5 | Anonymized creator/user id. | Officer/user workload, capture bias. |
| `center_code` | numeric string | 11,260 | Traffic/police center code. | Station joining key where present. |
| `police_station` | string | 5 | Police station name. | Operational ownership, station dashboards. |
| `data_sent_to_scita` | boolean string | 0 | Whether record was sent to SCITA. | Workflow state, integration health. |
| `junction_name` | string | 5 | Junction label or `No Junction`. | Junction-level hotspot ranking. |
| `action_taken_timestamp` | timestamp string | 298,450 | Empty in this dataset. | Cannot infer enforcement action timing. |
| `data_sent_to_scita_timestamp` | timestamp string | 256,289 | Timestamp for SCITA transfer where available. | Limited integration-lag analysis only. |
| `updated_vehicle_number` | string | 125,254 | Vehicle number after validation/update. | Validation corrections, repeat vehicle if present. |
| `updated_vehicle_type` | string | 125,254 | Vehicle type after validation/update. | More trusted vehicle type for validated rows. |
| `validation_status` | string | 125,254 | Validation outcome/status. | Label confidence, approval/rejection model. |
| `validation_timestamp` | timestamp string | 125,254 | Validation time, UTC. | Validation latency, workflow freshness. |

### Timestamp Parsing Note

Timestamp columns mix whole-second and fractional-second strings. Parse with mixed-format timestamp logic. In pandas, for example, use `pd.to_datetime(..., utc=True, format="mixed")` where available.

---

## 4. Data Quality Profile

| Column | Missing Count | Missing % | Non-null Unique Values | Notes |
|---|---:|---:|---:|---|
| `id` | 0 | 0.000% | 298,450 | Perfect primary key. |
| `latitude` | 0 | 0.000% | 177,983 | Complete; high precision. |
| `longitude` | 0 | 0.000% | 177,378 | Complete; high precision. |
| `location` | 3,041 | 1.019% | 10,942 | Mostly usable; extract pincodes. |
| `vehicle_number` | 0 | 0.000% | 231,890 | Anonymized but repeatable. |
| `vehicle_type` | 0 | 0.000% | 22 | Good categorical feature. |
| `description` | 298,450 | 100.000% | 0 | Empty; ignore. |
| `violation_type` | 0 | 0.000% | 991 combos | Multi-label; parse to list. |
| `offence_code` | 0 | 0.000% | 991 combos | Multi-label; parse to list. |
| `created_datetime` | 0 | 0.000% | 94,417 | Parseable event/system timestamp. |
| `closed_datetime` | 298,450 | 100.000% | 0 | Empty; ignore. |
| `modified_datetime` | 0 | 0.000% | 298,450 | Complete. |
| `device_id` | 0 | 0.000% | 3,070 | Useful for bias/workload. |
| `created_by_id` | 5 | 0.002% | 2,666 | Nearly complete. |
| `center_code` | 11,260 | 3.773% | 52 | Missing mostly for Kodigehalli and No Police Station. |
| `police_station` | 5 | 0.002% | 54 | Nearly complete. |
| `data_sent_to_scita` | 0 | 0.000% | 2 | Boolean-like. |
| `junction_name` | 5 | 0.002% | 169 | About half named, half `No Junction`. |
| `action_taken_timestamp` | 298,450 | 100.000% | 0 | Empty; cannot model action time. |
| `data_sent_to_scita_timestamp` | 256,289 | 85.873% | 42,161 | Present only for a minority. |
| `updated_vehicle_number` | 125,254 | 41.968% | 143,133 | Present when validated/updated. |
| `updated_vehicle_type` | 125,254 | 41.968% | 22 | Use over original type when present. |
| `validation_status` | 125,254 | 41.968% | 5 | Important but censored/incomplete. |
| `validation_timestamp` | 125,254 | 41.968% | 170,115 | Validation workflow timestamp. |

### Recommended Cleaning Rules

1. Treat the strings `NULL`, empty string, and blank-like values as missing.
2. Parse `violation_type` and `offence_code` using a safe list parser.
3. Convert all timestamps from UTC to `Asia/Kolkata` for traffic analysis.
4. Drop `description`, `closed_datetime`, and `action_taken_timestamp` from the MVP because they are 100% missing.
5. Use `updated_vehicle_type` when present; otherwise fall back to `vehicle_type`.
6. Use `approved` rows as high-confidence events; keep all rows for visibility/heatmap if the goal is detection coverage.
7. Do not use validation status naively across time because Feb-Apr rows are much less validated.
8. Keep `device_id` and `created_by_id` for QA/bias analysis, not as first-order congestion causes.

---

## 5. Geographic Coverage

| Metric | Value |
|---|---:|
| Latitude min | 12.8026667 |
| Latitude median | 12.9772841 |
| Latitude max | 13.2936844 |
| Longitude min | 77.4425530 |
| Longitude median | 77.5841145 |
| Longitude max | 77.7717350 |
| Valid lat/lon rows | 298,450 |
| Rows inside approximate Bengaluru bounding box | 298,450 |
| Rows outside approximate Bengaluru bounding box | 0 |

The coordinates are clean enough for:

- Heatmaps.
- Grid/H3 indexing.
- DBSCAN hotspot detection.
- Nearest road-segment matching with OpenStreetMap.
- Distance-to-junction features.
- Station-level and pincode-level aggregation.

### Pincode Extraction

Pincodes can be extracted from `location` using a regex. Extraction works for 295,409 rows, or 98.98% of the dataset.

| Metric | Value |
|---|---:|
| Pincode extracted rows | 295,409 |
| Missing pincode/location rows | 3,041 |
| Unique pincodes | 115 |

Top pincodes:

| Pincode | Count | % of Rows |
|---|---:|---:|
| 560009 | 33,206 | 11.126% |
| 560001 | 25,995 | 8.710% |
| 560010 | 20,445 | 6.850% |
| 560002 | 18,980 | 6.360% |
| 560103 | 15,944 | 5.342% |
| 560042 | 10,393 | 3.482% |
| 560040 | 9,298 | 3.115% |
| 560037 | 7,515 | 2.518% |
| 560092 | 7,423 | 2.487% |
| 560023 | 6,910 | 2.315% |
| 560055 | 6,304 | 2.112% |
| 560003 | 5,620 | 1.883% |
| 560016 | 5,618 | 1.882% |
| 560053 | 5,610 | 1.880% |
| 560008 | 5,485 | 1.838% |
| 560004 | 5,035 | 1.687% |
| 562149 | 4,590 | 1.538% |
| 560068 | 4,581 | 1.535% |
| 560024 | 4,402 | 1.475% |
| 560036 | 4,313 | 1.445% |
| 560051 | 3,922 | 1.314% |
| 560102 | 3,851 | 1.290% |
| 560011 | 3,628 | 1.216% |
| 560100 | 3,522 | 1.180% |
| 560022 | 3,489 | 1.169% |

### Approximate 250 m Grid Hotspots

These are rough hotspots from rounding latitude/longitude into about 250 m cells. Use them as initial demo candidates; production modeling should use H3/S2 grids or road segments.

| Rank | Records | Approx Lat | Approx Lon | Station | Junction / Area |
|---:|---:|---:|---:|---|---|
| 1 | 5,838 | 12.977343 | 77.575702 | Upparpet | Elite Junction / Gandhi Nagar |
| 2 | 5,280 | 12.964238 | 77.577087 | City Market | KR Market |
| 3 | 5,166 | 12.933596 | 77.690991 | HAL Old Airport | New Horizon College Road / Kadubisanahalli |
| 4 | 4,842 | 12.981066 | 77.610147 | Shivajinagar | Safina Plaza / Kamaraj Road |
| 5 | 4,408 | 12.976143 | 77.577490 | Upparpet | Kempe Gowda Circle / Gandhi Nagar |
| 6 | 3,994 | 12.975534 | 77.575868 | Upparpet | Kempegowda Road |
| 7 | 3,871 | 12.964614 | 77.576230 | City Market | Mysore Road / KR Market |
| 8 | 3,798 | 12.977631 | 77.577580 | Upparpet | Subbanna Junction |
| 9 | 3,485 | 12.978101 | 77.579573 | Upparpet | Gandhi Nagar |
| 10 | 3,413 | 12.981649 | 77.608963 | Shivajinagar | Dispensary Road / Safina area |
| 11 | 3,309 | 12.973351 | 77.579240 | Upparpet | Sagar Theatre Junction |
| 12 | 3,198 | 12.982147 | 77.606763 | Shivajinagar | Tasker Town |
| 13 | 2,963 | 12.982485 | 77.610725 | Shivajinagar | Kamaraj Road |
| 14 | 2,796 | 12.979910 | 77.607261 | Shivajinagar | Main Guard Cross Road |
| 15 | 2,670 | 12.997656 | 77.548731 | Rajajinagar | Modi Bridge Junction |

---

## 6. Time Coverage And Temporal Patterns

All timestamps are stored in UTC. For a Bengaluru traffic product, convert `created_datetime` to IST.

### Monthly Record Counts, IST

| Month | Count |
|---|---:|
| 2023-11 | 43,506 |
| 2023-12 | 63,918 |
| 2024-01 | 65,479 |
| 2024-02 | 54,660 |
| 2024-03 | 55,455 |
| 2024-04 | 15,432 |

April is partial: the last event creation date is 2024-04-08 IST.

### Daily Count Distribution, IST

| Metric | Count |
|---|---:|
| Number of local dates | 151 |
| Minimum daily count | 1,003 |
| 10th percentile daily count | 1,460 |
| Median daily count | 2,022 |
| Mean daily count | 1,976.49 |
| 90th percentile daily count | 2,437 |
| Maximum daily count | 2,991 |

Top local dates by event count:

| Date | Count |
|---|---:|
| 2024-01-07 | 2,991 |
| 2023-11-18 | 2,974 |
| 2024-01-21 | 2,924 |
| 2023-12-31 | 2,775 |
| 2023-11-17 | 2,719 |
| 2023-12-24 | 2,711 |
| 2024-01-16 | 2,690 |
| 2024-01-14 | 2,662 |
| 2024-03-31 | 2,576 |
| 2023-11-19 | 2,554 |

### Day Of Week Counts, IST

| Day | Count |
|---|---:|
| Monday | 34,680 |
| Tuesday | 42,697 |
| Wednesday | 41,977 |
| Thursday | 43,547 |
| Friday | 40,864 |
| Saturday | 44,523 |
| Sunday | 50,162 |

Sunday has the highest recorded count. For a hackathon demo, this can support a "weekend commercial-area pressure" narrative, but validate by location because enforcement activity may also vary by day.

### Hour Of Day Counts, IST

| Hour | Count | % of Rows |
|---:|---:|---:|
| 00 | 5,815 | 1.95% |
| 01 | 11,098 | 3.72% |
| 02 | 16,261 | 5.45% |
| 03 | 21,565 | 7.23% |
| 04 | 23,513 | 7.88% |
| 05 | 22,193 | 7.44% |
| 06 | 19,838 | 6.65% |
| 07 | 19,445 | 6.52% |
| 08 | 25,790 | 8.64% |
| 09 | 26,996 | 9.05% |
| 10 | 32,580 | 10.92% |
| 11 | 32,176 | 10.78% |
| 12 | 19,689 | 6.60% |
| 13 | 11,546 | 3.87% |
| 14 | 5,634 | 1.89% |
| 15 | 1,224 | 0.41% |
| 16 | 583 | 0.20% |
| 17 | 377 | 0.13% |
| 18 | 150 | 0.05% |
| 19 | 27 | 0.01% |
| 20 | 42 | 0.01% |
| 21 | 148 | 0.05% |
| 22 | 725 | 0.24% |
| 23 | 1,035 | 0.35% |

Time bucket summary:

| Bucket | Count | Interpretation |
|---|---:|---|
| 00:00-05:59 | 100,445 | High, possibly night/early morning enforcement or system entry pattern. |
| 06:00-09:59 | 92,069 | Strong morning pressure window. |
| 10:00-15:59 | 102,849 | Strong midday/commercial-area pressure window. |
| 16:00-20:59 | 1,179 | Very low; likely operational data bias. |
| 21:00-23:59 | 1,908 | Very low. |

### Temporal Caveat

Do not claim that violations only happen in the morning. The timestamp may reflect creation in the enforcement system, not always the exact moment the vehicle blocked traffic. For forecasting and demo purposes, call it "recorded violation creation time" unless the data provider confirms otherwise.

---

## 7. Violation Taxonomy

There are 27 distinct violation items after parsing the list-like `violation_type` column. Counts below are item counts, so percentages can sum to more than 100% because one row can have multiple violations.

| Violation Item | Offence Code | Records With Item | % of Rows |
|---|---:|---:|---:|
| WRONG PARKING | 112 | 164,977 | 55.278% |
| NO PARKING | 113 | 139,050 | 46.591% |
| PARKING IN A MAIN ROAD | 107 | 23,943 | 8.022% |
| DEFECTIVE NUMBER PLATE | 116 | 7,848 | 2.630% |
| PARKING ON FOOTPATH | 105 | 3,757 | 1.259% |
| PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC | 111 | 2,403 | 0.805% |
| DOUBLE PARKING | 109 | 2,037 | 0.683% |
| PARKING NEAR ROAD CROSSING | 104 | 1,687 | 0.565% |
| REFUSE TO GO FOR HIRE | 124 | 887 | 0.297% |
| PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS | 106 | 525 | 0.176% |
| PARKING OPPOSITE TO ANOTHER PARKED VEHICLE | 108 | 486 | 0.163% |
| USING BLACK FILM/OTHER MATERIALS | 133 | 248 | 0.083% |
| PARKING OTHER THAN BUS STOP | 139 | 242 | 0.081% |
| DEMANDING EXCESS FARE | 125 | 240 | 0.080% |
| WITHOUT SIDE MIRROR | 144 | 47 | 0.016% |
| H T V PROHIBITED | 147 | 31 | 0.010% |
| OBSTRUCTING DRIVER | 136 | 16 | 0.005% |
| AGAINST ONE WAY/NO ENTRY | 135 | 9 | 0.003% |
| FAIL TO USE SAFETY BELTS | 110 | 8 | 0.003% |
| VIOLATING LANE DISIPLINE | 130 | 5 | 0.002% |
| RIDER NOT WEARING HELMET | 140 | 2 | 0.001% |
| 2W/3W - USING MOBILE PHONE | 237 | 2 | 0.001% |
| OTHER - USING MOBILE PHONE | 437 | 1 | 0.000% |
| CARRYING LENGHTY MATERIAL | 123 | 1 | 0.000% |
| JUMPING TRAFFIC SIGNAL | 115 | 1 | 0.000% |
| U TURN PROHIBITED | 134 | 1 | 0.000% |
| STOPING ON WHITE/STOP LINE | 146 | 1 | 0.000% |

### Violations Per Record

| Number Of Violation Items In Row | Row Count |
|---:|---:|
| 1 | 258,340 |
| 2 | 32,951 |
| 3 | 5,404 |
| 4 | 1,192 |
| 5 | 294 |
| 6 | 180 |
| 7 | 51 |
| 8 | 21 |
| 9 | 15 |
| 11 | 1 |
| 12 | 1 |

Most rows have a single violation label, but 40,110 rows have two or more labels. Those multi-label rows are valuable for severity scoring.

### Top Violation Combinations

| Combination | Count |
|---|---:|
| `WRONG PARKING` only | 138,764 |
| `NO PARKING` only | 119,576 |
| `PARKING IN A MAIN ROAD` + `WRONG PARKING` | 9,472 |
| `PARKING IN A MAIN ROAD` + `NO PARKING` | 4,818 |
| `WRONG PARKING` + `DEFECTIVE NUMBER PLATE` | 3,317 |
| `NO PARKING` + `PARKING IN A MAIN ROAD` | 2,449 |
| `NO PARKING` + `DEFECTIVE NUMBER PLATE` | 2,380 |
| `WRONG PARKING` + `PARKING IN A MAIN ROAD` | 1,955 |
| `PARKING ON FOOTPATH` + `WRONG PARKING` | 1,190 |
| `NO PARKING` + `WRONG PARKING` | 891 |

### Congestion-Relevant Violation Weights

For a hackathon risk score, use different severity weights instead of treating every violation equally.

| Violation Signal | Suggested Weight | Reason |
|---|---:|---|
| Double parking | 1.40 | Directly blocks lane capacity. |
| Parking near traffic light / zebra crossing | 1.35 | Reduces intersection throughput and pedestrian safety. |
| Parking near road crossing | 1.35 | Impacts turning and merging. |
| Parking in a main road | 1.30 | Likely affects high-volume links. |
| Parking near bus stop / school / hospital | 1.25 | Creates pickup/drop-off conflict and local queueing. |
| Footpath parking | 1.15 | Pushes pedestrians into road, indirect traffic/safety risk. |
| Wrong parking / no parking | 1.00 | Base illegal parking signal. |
| Defective number plate only | 0.40 | Enforcement issue, weaker congestion signal unless co-occurs with parking. |

---

## 8. Vehicle Signals

### Original Vehicle Type Counts

| Vehicle Type | Count | % of Rows |
|---|---:|---:|
| SCOOTER | 94,856 | 31.783% |
| CAR | 88,870 | 29.777% |
| MOTOR CYCLE | 40,811 | 13.674% |
| PASSENGER AUTO | 37,813 | 12.670% |
| MAXI-CAB | 11,372 | 3.810% |
| LGV | 8,255 | 2.766% |
| GOODS AUTO | 2,934 | 0.983% |
| MOPED | 2,199 | 0.737% |
| PRIVATE BUS | 1,633 | 0.547% |
| VAN | 1,466 | 0.491% |
| TEMPO | 1,368 | 0.458% |
| BUS (BMTC/KSRTC) | 1,281 | 0.429% |
| HGV | 1,144 | 0.383% |
| LORRY/GOODS VEHICLE | 1,122 | 0.376% |
| JEEP | 913 | 0.306% |
| OTHERS | 895 | 0.300% |
| TOURIST BUS | 379 | 0.127% |
| SCHOOL VEHICLE | 378 | 0.127% |
| TANKER | 260 | 0.087% |
| FACTORY BUS | 238 | 0.080% |
| MINI LORRY | 199 | 0.067% |
| TRACTOR | 64 | 0.021% |

Two-wheelers (`SCOOTER`, `MOTOR CYCLE`, `MOPED`) account for 137,866 records, about 46.19% of all rows. Cars account for 29.78%.

### Updated Vehicle Type

`updated_vehicle_type` exists for 173,196 rows. Among those, 6,169 rows changed vehicle type after update/validation, equal to 3.56% of updated rows.

Top vehicle-type corrections:

| Original -> Updated | Count |
|---|---:|
| CAR -> MAXI-CAB | 899 |
| CAR -> SCOOTER | 679 |
| SCOOTER -> MOTOR CYCLE | 646 |
| MOTOR CYCLE -> SCOOTER | 466 |
| MAXI-CAB -> CAR | 299 |
| CAR -> MOTOR CYCLE | 290 |
| SCOOTER -> CAR | 273 |
| PASSENGER AUTO -> SCOOTER | 250 |

### Repeat Vehicle Signal

| Metric | Value |
|---|---:|
| Unique anonymized vehicle numbers | 231,890 |
| Vehicles with one record | 196,303 |
| Vehicles with 2 records | 23,733 |
| Vehicles with 3-5 records | 9,502 |
| Vehicles with 6-10 records | 1,800 |
| Vehicles with more than 10 records | 552 |
| Maximum records for one anonymized vehicle | 55 |

Use this for:

- Repeat-offender heat.
- Prior offense count in last 7/30/90 days.
- Risk of recurrence at a station or pincode.
- Demonstrating targeted warnings for repeated illegal parking behavior.

Do not claim real vehicle identity because the numbers are anonymized.

---

## 9. Police Station, Junction, And Operational Coverage

### Police Station Counts

There are 54 non-null police station names plus a small `No Police Station` category. Top stations are heavily concentrated.

| Police Station | Count | % of Rows |
|---|---:|---:|
| Upparpet | 34,468 | 11.549% |
| Shivajinagar | 28,044 | 9.397% |
| Malleshwaram | 22,200 | 7.438% |
| HAL Old Airport | 20,819 | 6.976% |
| City Market | 17,646 | 5.913% |
| Vijayanagara | 14,652 | 4.909% |
| Rajajinagar | 10,998 | 3.685% |
| Kodigehalli | 10,916 | 3.658% |
| Magadi Road | 8,558 | 2.867% |
| Jeevanbheemanagar | 6,736 | 2.257% |
| K.R. Pura | 6,546 | 2.193% |
| Halasuru Gate | 6,294 | 2.109% |
| Mahadevapura | 6,187 | 2.073% |
| Chikkajala | 5,834 | 1.955% |
| HSR Layout | 5,018 | 1.681% |
| Bellandur | 4,964 | 1.663% |
| High ground | 4,951 | 1.659% |
| Byatarayanapura | 4,555 | 1.526% |
| Electronic City | 4,333 | 1.452% |
| Pulikeshinagar(F.Town) | 4,136 | 1.386% |
| Halasur | 4,011 | 1.344% |
| Jayanagara | 3,813 | 1.278% |
| Chamarajpet | 3,795 | 1.272% |
| Banaswadi | 3,759 | 1.260% |
| Basavanagudi | 3,604 | 1.208% |
| Ashok Nagar | 3,524 | 1.181% |
| Adugodi | 3,332 | 1.116% |
| Cubbon Park | 3,255 | 1.091% |
| Hebbala | 3,209 | 1.075% |
| Wilson Garden | 3,108 | 1.041% |
| Sheshadripuram | 3,090 | 1.035% |
| Mico Layout | 2,588 | 0.867% |
| Yeshwanthpura | 2,587 | 0.867% |
| Yelahanka | 2,440 | 0.818% |
| Hulimavu | 2,395 | 0.802% |
| Whitefield | 2,303 | 0.772% |
| R.T. Nagar | 1,736 | 0.582% |
| J.P. Nagar | 1,637 | 0.549% |
| Madiwala | 1,563 | 0.524% |
| V.V.Puram (C.Pet) | 1,556 | 0.521% |
| Sadashivanagar | 1,445 | 0.484% |
| Kamakshipalya | 1,431 | 0.479% |
| Banashankari | 1,202 | 0.403% |
| Jalahalli | 1,160 | 0.389% |
| Jnanabharathi | 1,063 | 0.356% |
| Peenya | 974 | 0.326% |
| Devanahalli Airport | 940 | 0.315% |
| Hennuru | 892 | 0.299% |
| K.G. Halli | 892 | 0.299% |
| Thalagattapura | 870 | 0.292% |
| K.S. Layout | 828 | 0.277% |
| Chikkabanavara | 785 | 0.263% |
| Kengeri | 464 | 0.155% |
| No Police Station | 339 | 0.114% |

### Junction Coverage

| Metric | Count |
|---|---:|
| Non-null `junction_name` rows | 298,445 |
| Unique non-null junction values | 169 |
| `No Junction` rows | 147,880 |
| Named junction rows | 150,565 |

Top named junctions:

| Junction | Count | % of Rows |
|---|---:|---:|
| BTP051 - Safina Plaza Junction | 15,449 | 5.176% |
| BTP082 - KR Market Junction | 11,538 | 3.866% |
| BTP040 - Elite Junction | 10,718 | 3.591% |
| BTP044 - Sagar Theatre Junction | 10,549 | 3.535% |
| BTP211 - Central Street Junction | 5,388 | 1.805% |
| BTP058 - Subbanna Junction | 5,189 | 1.739% |
| BTP027 - Modi Bridge Junction | 4,584 | 1.536% |
| BTP020 - Hosahalli Metro Station | 4,101 | 1.374% |
| BTP057 - Anand Rao Junction | 3,935 | 1.318% |
| BTP080 - NR Road, SP Road Junction | 3,681 | 1.233% |
| BTP045 - Danvanthri Road | 3,181 | 1.066% |
| BTP001 - 10th Cross, Dr. Rajkumar Road | 2,812 | 0.942% |
| BTP083 - AS Char Street, Mysore Road | 2,778 | 0.931% |
| BTP032 - Windsor Circle | 2,749 | 0.921% |
| BTP016 - 5th Main Road, RPC Layout | 2,474 | 0.829% |

### Center Code Missingness

`center_code` is missing in 11,260 rows. Missingness is not random:

| Police Station / Category | Missing `center_code` Rows |
|---|---:|
| Kodigehalli | 10,916 |
| No Police Station | 339 |
| Missing police station | 5 |

This means Kodigehalli should not be dropped just because `center_code` is missing.

---

## 10. Validation And Workflow Fields

### Validation Status

| Status | Count | % of All Rows | % of Non-null Status Rows |
|---|---:|---:|---:|
| approved | 115,400 | 38.67% | 66.63% |
| rejected | 49,754 | 16.67% | 28.73% |
| created1 | 7,044 | 2.36% | 4.07% |
| processing | 678 | 0.23% | 0.39% |
| duplicate | 320 | 0.11% | 0.18% |
| missing | 125,254 | 41.97% | N/A |

### Validation By Month, IST

| Month | Missing | Approved | Rejected | Created1 | Processing | Duplicate |
|---|---:|---:|---:|---:|---:|---:|
| 2023-11 | 4,441 | 28,220 | 10,843 | 0 | 0 | 0 |
| 2023-12 | 6,191 | 40,998 | 16,540 | 188 | 0 | 0 |
| 2024-01 | 6,669 | 37,425 | 13,534 | 6,856 | 678 | 317 |
| 2024-02 | 46,427 | 1,719 | 6,511 | 0 | 0 | 3 |
| 2024-03 | 46,089 | 7,038 | 2,326 | 0 | 0 | 0 |
| 2024-04 | 15,432 | 0 | 0 | 0 | 0 | 0 |

This is a major modeling caveat. Validation is far less complete in recent months. For a fair model:

- Use time-aware splits.
- Avoid using `validation_status` as a target across all months without censoring adjustment.
- For hotspot visibility, show both "all recorded events" and "approved-only confidence view."

### Workflow Latency

| Metric | Count | Median | 90th Percentile | Notes |
|---|---:|---:|---:|---|
| `modified_datetime - created_datetime` | 298,450 | 0.265 hours | 18.481 hours | Most records are modified quickly. |
| `validation_timestamp - created_datetime` | 173,196 | 31.04 hours | 164.915 hours | Validation can take days. |
| `data_sent_to_scita_timestamp - created_datetime` | 42,161 | 428.42 hours | 454.789 hours | Likely batch/integration process, not event action time. |

There are 314 negative modified-time deltas and 2 negative validation-time deltas. Treat them as data corrections or timestamp inconsistencies.

### SCITA Integration

| Field | Count |
|---|---:|
| `data_sent_to_scita = TRUE` | 255,893 |
| `data_sent_to_scita = FALSE` | 42,557 |
| Rows with `data_sent_to_scita_timestamp` | 42,161 |

The boolean flag is much more complete than the timestamp. Do not assume missing SCITA timestamp means not sent.

---

## 11. What Is Possible With This Dataset

### A. Hotspot Intelligence

Possible:

- Citywide illegal-parking heatmap.
- Pincode, station, junction, grid, and road-segment rankings.
- Time-aware hotspot changes by hour/day/month.
- Named high-risk corridor detection around markets, metro-adjacent areas, commercial streets, hospitals/schools, bus stops, and junctions.

Recommended methods:

- Fast MVP: grid or H3 cell aggregation.
- Better model: DBSCAN/HDBSCAN on latitude/longitude within time windows.
- Best demo: road-segment matching using OpenStreetMap, then line-based risk overlays.

### B. Parking Congestion Risk Index

Possible:

- A proxy 0-100 score for parking-induced congestion risk.
- Explainable components: density, severity, junction impact, road context, vehicle obstruction, repeat behavior, time of day, validation confidence.

Not directly possible:

- True traffic delay in minutes unless external speed/flow data is added.
- Actual queue length or capacity loss without road geometry and traffic volume.

### C. Forecasting

Possible targets:

- Next-hour or next-day violation count by grid/station/junction.
- Probability that a zone will be in the top-k hotspots.
- Expected risk score by hour.
- Weekend/weekday hotspot ranking.

Useful models:

- Baseline: seasonal naive and rolling average.
- Strong hackathon model: LightGBM/XGBoost on lagged time-series features.
- Spatial model: graph-neighbor lag features after road/grid construction.

### D. Enforcement Prioritization

Possible:

- Rank patrol zones by risk, confidence, and severity.
- Allocate limited enforcement teams to high-risk zones.
- Show uncovered high-risk zones when manpower is insufficient.
- Simulate spillover/waterbed effect: enforcement in one hotspot may move violations to nearby roads.

Not directly possible:

- Measuring actual patrol effectiveness because there is no patrol schedule or action timestamp.

### E. Validation Quality Model

Possible:

- Predict approval probability from violation type, vehicle type, station, device/user, and location.
- Flag zones/devices with high rejection rates.
- Build a "confidence layer" on the map.

Use carefully because recent rows are validation-incomplete.

### F. Repeat-Offender Analysis

Possible:

- Repeat vehicle count over rolling windows.
- Repeated violations by pincode/station.
- Repeat-offender contribution to hotspot persistence.

Use carefully because vehicle numbers are anonymized. Treat them as stable pseudonymous ids only inside this dataset.

---

## 12. Recommended Product Concept

### Product Name

**ParkVisionSaathi AI**

### One-Line Pitch

An AI command center that converts raw parking violations into live congestion-risk hotspots, predicts where illegal parking will reappear, and recommends targeted patrol deployment with explainable risk reasoning.

### Core User

Traffic police control room, station-level enforcement officers, and city mobility planners.

### Judge-Facing Story

"Today, enforcement is reactive and patrol-based. This system turns past violation records into a predictive map. It tells officers where illegal parking is most likely to choke roads, why that zone matters, and how to deploy limited teams for maximum coverage."

### Core Screens

1. **City Hotspot Map**
   - Heatmap of parking violation density/risk.
   - Filters: time, violation type, station, validation confidence.

2. **Risk Breakdown Panel**
   - Zone selected on map.
   - Shows density, severity, junction impact, repeat vehicle pressure, validation trust, top violation types.

3. **Forecast View**
   - Next 24 hours or next 7 days risk.
   - Shows emerging hotspots, not just historical hotspots.

4. **Patrol Simulation**
   - Slider for number of enforcement teams.
   - Recommends zones and estimated coverage.
   - Shows uncovered risk and possible spillover.

5. **LLM Explanation**
   - "Why is this zone risky?"
   - "What should an officer do here?"
   - "What nearby zones may see spillover?"

---

## 13. Parking Congestion Risk Index

Because direct congestion ground truth is absent, define an honest proxy. A judge will trust the project more if the score is transparent.

### Suggested Formula

For each zone `z` and time bucket `t`:

```text
risk_raw(z,t) =
  0.30 * normalized_violation_density(z,t)
+ 0.20 * severity_weighted_violation_density(z,t)
+ 0.15 * junction_or_main_road_exposure(z)
+ 0.10 * repeat_vehicle_pressure(z,t)
+ 0.10 * heavy_vehicle_obstruction_mix(z,t)
+ 0.10 * temporal_peak_weight(t)
+ 0.05 * validation_confidence(z,t)

risk_score(z,t) = min_max_scale_to_0_100(risk_raw)
```

### Component Definitions

| Component | Source Columns | Definition |
|---|---|---|
| Violation density | `latitude`, `longitude`, `created_datetime` | Count per grid/road segment/time bucket. |
| Severity-weighted density | `violation_type`, `offence_code` | Count weighted by congestion severity. |
| Junction/main-road exposure | `junction_name`, `violation_type`, optional OSM | Named junction or main-road violation boost. |
| Repeat vehicle pressure | `vehicle_number`, `created_datetime` | Rolling count of repeat vehicles in the zone. |
| Heavy vehicle obstruction mix | `vehicle_type` / `updated_vehicle_type` | Larger vehicles get higher obstruction weight. |
| Temporal peak weight | `created_datetime` | Morning/midday/weekend weighting; tune carefully. |
| Validation confidence | `validation_status` | Approved share, missingness-adjusted. |

### Suggested Vehicle Obstruction Weights

| Vehicle Group | Examples | Suggested Weight |
|---|---|---:|
| Two-wheeler | Scooter, motorcycle, moped | 0.70 |
| Car/jeep/van | Car, jeep, van | 1.00 |
| Auto/cab | Passenger auto, maxi-cab | 1.10 |
| Goods vehicle | LGV, HGV, lorry, tanker, tempo | 1.35 |
| Bus/school/factory vehicle | BMTC/KSRTC, private bus, school vehicle | 1.50 |

### Risk Bands

| Score | Band | Meaning |
|---:|---|---|
| 0-30 | Low | Monitor only. |
| 31-60 | Medium | Candidate for patrol if nearby. |
| 61-80 | High | Prioritize for patrol. |
| 81-100 | Critical | High-density or high-severity hotspot near sensitive road/junction. |

---

## 14. Feature Engineering Plan

### Spatial Features

- `grid_id`: H3/S2/geohash/grid cell.
- `road_segment_id`: nearest OSM road segment.
- `station_id`: normalized police station.
- `pincode`: extracted from `location`.
- `is_named_junction`: `junction_name != "No Junction"`.
- `junction_id`: parsed from BTP code when available.
- `distance_to_top_junction`: optional from junction centroids.
- `hotspot_rank_station`: zone rank within station.

### Temporal Features

- `hour_ist`, `day_of_week`, `month`, `is_weekend`.
- `time_bucket`: night, morning peak, midday, evening, late evening.
- Rolling counts by grid/station: 1 day, 7 days, 30 days.
- Lag features: previous hour/day/week counts.
- Recency feature: days since last violation in zone.

### Violation Features

- Multi-hot vector for all 27 violation types.
- `violation_count_in_row`.
- `severity_sum`, `severity_max`, `has_main_road`, `has_double_parking`, `has_crossing_or_signal`, `has_footpath`.

### Vehicle Features

- `trusted_vehicle_type`: `updated_vehicle_type` if present, else `vehicle_type`.
- `vehicle_obstruction_weight`.
- `vehicle_repeat_count_all_time`.
- `vehicle_repeat_count_last_30d`.
- `vehicle_type_mix_zone`.

### Workflow And Confidence Features

- `is_approved`, `is_rejected`, `is_pending`.
- `validation_coverage_zone`.
- `approval_rate_zone`.
- `device_count_zone`.
- `top_device_share_zone`.
- `data_sent_to_scita`.

---

## 15. Modeling Roadmap

### Model 1: Hotspot Detection

Goal: identify illegal-parking hotspot zones.

MVP:

- Aggregate by H3/grid cell and time bucket.
- Rank by risk score.

Advanced:

- Run DBSCAN or HDBSCAN on lat/lon separately for time buckets.
- Use cluster persistence across weeks to classify stable vs emerging hotspots.

Evaluation:

- Backtest: train on older dates, see if top-k hotspots remain high in later dates.
- Metrics: precision@k, recall of top decile zones, rank stability.

### Model 2: Forecasting

Goal: predict future violation count or risk per zone.

Recommended target:

```text
target = count of violations in zone z during future time bucket t
```

Models:

- Baseline: previous same weekday/hour mean.
- Strong: LightGBM/XGBoost with lag and rolling features.
- Alternative: Poisson/Negative Binomial regression for count data.

Time split:

- Train: 2023-11 to 2024-02.
- Validation: 2024-03.
- Test/demo holdout: 2024-04 partial.

Metrics:

- MAE by zone/day.
- Weighted MAE giving more importance to top-risk zones.
- Precision@10 for predicting tomorrow's top hotspots.

### Model 3: Validation Confidence

Goal: estimate whether a row is likely to be approved.

Target:

```text
approved vs rejected
```

Use only rows with final validation status `approved` or `rejected`. Exclude `created1`, `processing`, `duplicate`, and missing status for this model.

Important: Use a time-aware split because recent months are validation-incomplete.

### Model 4: Patrol Allocation

Goal: allocate limited teams to zones.

Simple algorithm:

1. Compute risk score for each zone.
2. Sort zones by risk and confidence.
3. Merge nearby high-risk zones into patrol clusters.
4. Assign teams to clusters until capacity is exhausted.
5. Show uncovered risk.

Game-theory extension:

- Treat police as leader and violators as followers.
- Compute patrol probabilities proportional to risk, adjusted by recent patrol saturation.
- Simulate waterbed effect by shifting some risk to neighboring zones.

---

## 16. Minimum Viable Hackathon Build

### Build Only What Creates A Strong Demo

**Day 1: Data and Map**

- Clean CSV into parquet/DB.
- Parse list-like violation fields.
- Convert timestamps to IST.
- Create grid/H3 zones.
- Build map heatmap with station and time filters.

**Day 2: Risk and Forecast**

- Implement risk score.
- Show top hotspots with explanations.
- Add simple forecast: rolling mean + lag features.
- Backtest one metric so judges see rigor.

**Day 3: Simulation and LLM**

- Add patrol-team slider.
- Recommend top zones and show uncovered high-risk areas.
- Add LLM explanation using structured context from the zone, not raw CSV.
- Polish demo story.

### MVP Data Tables

| Table | Purpose |
|---|---|
| `violations_clean` | One cleaned row per original violation event. |
| `violation_items` | Exploded row per violation item/offence code. |
| `zones` | Grid/H3/road-segment zones with centroid and station. |
| `zone_time_counts` | Aggregated counts by zone and time bucket. |
| `risk_scores` | Component and final risk score by zone/time. |
| `forecasts` | Predicted count/risk by zone/time. |
| `patrol_recommendations` | Team assignments and uncovered risk. |

### MVP API Endpoints

| Endpoint | Output |
|---|---|
| `GET /summary` | Dataset totals and date coverage. |
| `GET /hotspots?hour=&station=&view=` | Ranked hotspot list and map points. |
| `GET /risk/{zone_id}?time=` | Risk components and explanation context. |
| `GET /forecast?zone_id=&horizon=` | Predicted counts/risk. |
| `POST /simulate` | Team allocation and uncovered risk. |
| `POST /explain-zone` | LLM-generated explanation from structured facts. |

---

## 17. Best Hackathon Angles

### 1. "From Reactive Patrols To Predictive Patrols"

Use historical violations to rank tomorrow's hotspots. Show how the same number of teams can cover more risk.

### 2. "Congestion Proxy, Not Fake Congestion"

Be honest: this CSV does not contain vehicle speeds. Your contribution is a congestion-risk proxy built from parking behavior and road/junction context. This honesty will make the pitch stronger.

### 3. "Explainable Enforcement"

For every recommended zone, show:

- Why it is high risk.
- Which violation types dominate.
- What time it peaks.
- Which station owns it.
- What will remain uncovered if teams are limited.

### 4. "Confidence-Aware Policing"

Use validation status to show:

- Confirmed hotspots from approved violations.
- Suspected hotspots from all records.
- Low-confidence areas needing review.

### 5. "Waterbed Effect"

When enforcement increases in one hotspot, nearby streets may absorb illegal parking. Simulate this on neighboring grid cells/road segments.

---

## 18. What To Avoid In The Pitch

- Do not say the model directly measures congestion. It measures parking-induced congestion risk.
- Do not say validation status is complete. It is missing for 41.97% of rows.
- Do not use `created_datetime` as guaranteed real-world violation time without caveat.
- Do not rely on `closed_datetime`, `description`, or `action_taken_timestamp`; they are empty.
- Do not drop Kodigehalli just because `center_code` is missing.
- Do not expose raw anonymized vehicle numbers in the UI; aggregate repeat behavior.

---

## 19. Judge Demo Script

1. Open the Bengaluru map with risk heatmap.
2. Set time to morning/midday and show major hotspots: Upparpet, City Market, Shivajinagar, HAL Old Airport.
3. Click a hotspot.
4. Show explanation:
   - "This 250 m zone has X historical records."
   - "Dominant violations are wrong parking/no parking/main-road parking."
   - "It is near a named junction/market/commercial corridor."
   - "Repeat vehicles and heavier vehicle mix increase risk."
5. Toggle from "All Records" to "Approved Only" confidence layer.
6. Open forecast for next time bucket.
7. Move patrol-team slider from 3 to 8.
8. Show covered risk, uncovered risk, and potential spillover.
9. Ask the LLM: "Why should we patrol this zone first?"
10. End with impact: targeted enforcement, fewer blocked lanes, better use of limited officers.

---

## 20. Strong Project Extensions

If time allows, add one or two of these:

1. **Road-segment risk overlay:** Map violations to OSM road segments and color roads instead of showing only points.
2. **Metro/commercial/event context:** Add POI layers for metro stations, markets, hospitals, schools, and event venues.
3. **Before/after enforcement simulator:** Let user mark a zone as patrolled and show expected nearby displacement.
4. **Station commander dashboard:** Rank each station's top 10 hotspots, validation lag, and recommended patrol slots.
5. **Data-quality monitor:** Detect devices/users/stations with unusual rejection rates or timestamp inconsistencies.

---

## 21. Technical Architecture

### Data Layer

- Raw CSV stored unchanged.
- Cleaned parquet or PostgreSQL/PostGIS table.
- Spatial index on latitude/longitude or geometry.
- Aggregated zone/time tables for fast map loading.

### ML Layer

- Preprocessing pipeline.
- Hotspot detector.
- Risk scorer.
- Forecast model.
- Patrol simulator.
- Explanation context generator.

### API Layer

- FastAPI with Pydantic schemas.
- Cached hotspot/risk endpoints.
- Static demo mode if deployment time is limited.

### Frontend Layer

- React + TypeScript.
- Leaflet/MapLibre map.
- Heatmap, zone markers, station filter, time slider.
- Patrol simulation panel.
- Zone explanation drawer.

### LLM Layer

Use the LLM only after computing structured facts. Example context:

```json
{
  "zone_id": "grid_12.977_77.576",
  "station": "Upparpet",
  "records": 5838,
  "top_violations": ["WRONG PARKING", "NO PARKING"],
  "risk_score": 91,
  "dominant_time_bucket": "10:00-12:00 IST",
  "junction": "Elite Junction",
  "confidence": "medium-high"
}
```

The LLM should turn these facts into plain-language reasoning, not invent data.

---

## 22. Appendix: Top Station Validation Stats

| Station | Records | Rows With Validation | Approval Rate Among Validated | Validation Coverage |
|---|---:|---:|---:|---:|
| Upparpet | 34,468 | 21,040 | 73.2% | 61.0% |
| Shivajinagar | 28,044 | 17,551 | 62.8% | 62.6% |
| Malleshwaram | 22,200 | 12,106 | 70.0% | 54.5% |
| HAL Old Airport | 20,819 | 12,147 | 63.7% | 58.3% |
| City Market | 17,646 | 9,627 | 64.0% | 54.6% |
| Vijayanagara | 14,652 | 9,523 | 65.6% | 65.0% |
| Rajajinagar | 10,998 | 6,074 | 66.4% | 55.2% |
| Kodigehalli | 10,916 | 4,172 | 56.4% | 38.2% |
| Magadi Road | 8,558 | 5,277 | 62.6% | 61.7% |
| Jeevanbheemanagar | 6,736 | 4,200 | 73.9% | 62.4% |
| K.R. Pura | 6,546 | 3,575 | 60.9% | 54.6% |
| Halasuru Gate | 6,294 | 3,632 | 64.2% | 57.7% |
| Mahadevapura | 6,187 | 3,421 | 62.9% | 55.3% |
| Chikkajala | 5,834 | 3,408 | 65.6% | 58.4% |
| HSR Layout | 5,018 | 3,111 | 61.7% | 62.0% |

---

## 23. Appendix: Top Location Strings

| Location | Count |
|---|---:|
| Unnamed Road, Begur Chikkanahalli, Bengaluru, Karnataka. Pin-562149 | 4,090 |
| Kamaraj Road, Sri Nagamma Devi Circle, Sivanchetti Gardens, Bengaluru, Karnataka. Pin-560042 | 3,999 |
| New Horizon College Road, New Horizon College of Engineering, Kadubisanahalli, Bengaluru, Karnataka. Pin-560103 | 3,785 |
| MBT Road, Devasandra Junction, KR Puram, Bengaluru, Karnataka. Pin-560036 | 3,027 |
| Dispensary Road, Tasker Town, Shivaji Nagar, Bengaluru, Karnataka. Pin-560001 | 2,670 |
| Bellary Road, Vinayaka Nagar, Hebbal, Bengaluru, Karnataka. Pin-560024 | 2,639 |
| 5th Main Road, Kempe Gowda Circle, Gandhi Nagar, Bengaluru, Karnataka. Pin-560009 | 2,604 |
| Main Guard Cross Road, Tasker Town, Shivaji Nagar, Bengaluru, Karnataka. Pin-560001 | 2,549 |
| New Horizon College Road, Embassy Tech Village, Devara Beesana Halli, Bengaluru, Karnataka. Pin-560103 | 2,416 |
| 3rd Cross Road, Kempegowda Extension, Chickpete, Bengaluru, Karnataka. Pin-560009 | 2,315 |
| Mysore Road, Sri Krishna Rajendra Market, Chickpete, Bengaluru, Karnataka. Pin-560002 | 2,122 |
| 80 Feet Ring Road, Orion, Brigade Gateway, Malleshwaram West, Bengaluru, Karnataka. Pin-560055 | 2,117 |
| Meenakshi Koil Street, Shivaji Nagar, Bengaluru, Karnataka. Pin-560001 | 2,111 |
| Subedar Chatram Road, RK Puram, Gandhi Nagar, Bengaluru, Karnataka. Pin-560009 | 1,940 |
| Dickenson Road, Sri Nagamma Devi Circle, Sivanchetti Gardens, Bengaluru, Karnataka. Pin-560042 | 1,924 |

---

## 24. Final Recommendation

Build the hackathon project around **"Predictive Parking Congestion Risk and Patrol Optimization."**

The winning version should not just show historical dots. It should answer:

1. Where is illegal parking repeatedly happening?
2. Which of those places are likely to choke traffic?
3. Which hotspots will matter next?
4. Where should limited patrol teams go first?
5. Why did the model recommend that zone?

This dataset can support that story well if the project is transparent that congestion impact is a proxy and if the demo focuses on explainable enforcement decisions.
