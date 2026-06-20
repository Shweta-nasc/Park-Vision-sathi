# ParkVision-Saathi — Presentation Outline
## 8-Slide Structure | Theme: "Quantify. Predict. Optimize."

> **Demo-first rule:** Every slide either (a) shows a live demo action or (b) explains a number the judge will remember.
> Speaker notes are in `docs/DEMO_SCRIPT.md`. Judge Q&A attacks in `docs/JUDGE_QA.md`.

---

## SLIDE 1 — HOOK: THE TWO MAPS

**Title:** "2,000 Violations. Every Day. But Police Are Looking at the Wrong Map."

**Visual:** Side-by-side split → LEFT: violation density heatmap | RIGHT: congestion risk heatmap
*(live toggle on the actual app — NOT a screenshot)*

**Bullet points:**
- Left map: where violations are recorded
- Right map: where violations CHOKE traffic
- **These are NOT the same map. That difference is the problem.**
- City Market Circle: 20 violations → blocks 9.5 min of traffic. A quiet road: 80 violations → barely disrupts flow.

**Speaking beat (7 seconds):**
> *"2,000 parking violations. Every single day. In Bengaluru alone. But right now, traffic police have no system to see THIS—"*
> *[click toggle]*
> *"—violation density and congestion impact are NOT the same map."*

**Why this slide wins:** Opens with conflict. Forces judges to pay attention before the first fact lands.

---

## SLIDE 2 — THE PROBLEM (30 seconds)

**Title:** "Illegal Parking Doesn't Just Annoy — It Costs the City"

**Key numbers (all real, from dataset + Mappls API):**
- **298,450** violation records, Bengaluru, Nov 2023–Apr 2024
- **34.2 lane-hours** blocked daily by the top single zone (Upparpet/Subedar Chatram Road)
- **2.40x** travel time degradation at City Market Circle — validated by MapMyIndia real-time data
- **54 police stations**, limited patrol teams, zero data-driven deployment

**Visual:** Simple stat cards in dark theme — no busy chart

**Core message:** The problem is real, measurable, and solvable. We measured it.

---

## SLIDE 3 — OUR ANSWER: THE CONGESTION IMPACT SCORE

**Title:** "Not a Heatmap. A 6-Factor Congestion Impact Score."

**Visual:** Donut/spider chart showing the 6 components for City Market Circle

| Component | Weight | What It Measures |
|---|---|---|
| Lane Blockage | 30% | Main-road & double parking → lanes lost |
| Intersection Impact | 25% | Junction approach violations → green time wasted |
| Traffic Degradation | 25% | MapMyIndia travel time ratio (real data) |
| Transit Access Blockage | 10% | Bus stop & school/hospital zone violations |
| Vehicle Size Impact | 10% | Heavy vehicle obstruction multiplier |

**Speaking beat:**
> *"We don't count violations. We measure how many lane-hours they destroy."*
> *"Top zone: 34 lane-hours blocked per day. That's one lane, completely unusable, for a full working day."*

**Why this slide wins:** Answers the theme directly. "Quantify their impact on traffic flow" — this IS the answer.

---

## SLIDE 4 — LIVE DEMO: ZONE DETAIL + EXPLAIN

**Title:** "Every Zone Has a Congestion Story"

**Demo action sequence:**
1. Click on City Market Circle zone (rank #2 on map)
2. Right panel shows: Impact Score 85.3/100 CRITICAL, road name, 31.5 lane-hours blocked
3. Click "Explain" → Gemini LLM generates natural language explanation
4. Show MapMyIndia validation: 2.40x travel time (Baseline 4.0min → ETA 9.5min)

**Key LLM output to highlight (pre-cached for reliability):**
> *"BGS Flyover at City Market Circle scores 85.3/100 — CRITICAL. Three bus stops within 60 metres make this an acute bus bay obstruction zone. MapMyIndia confirms 2.4x travel time degradation, independently validating our model prediction. Enforce NO PARKING between 08:30–12:00 IST."*

**Speaking beat:**
> *"And if a field officer wants to understand WHY — one click. Gemini explains the zone in plain language, grounded in verified facts."*

---

## SLIDE 5 — PREDICT: TOMORROW'S HOTSPOTS

**Title:** "LightGBM + CatBoost Ensemble: Predict Tomorrow's Top-10 Hotspots"

**Model architecture (bullet points):**
- **LightGBM** (Poisson objective — count data) + **CatBoost** (native categoricals: station, pincode)
- Features: 7-day lag, 14-day rolling mean, day-of-week, zone historical rank, junction flag
- Train: Nov 2023 – Feb 2024 | Validate: March 2024

**Metric to present (pick the best one — fill in actual number from Person 2):**
- `Precision@10: ___%` (what % of tomorrow's real top-10 hotspots did we predict?)
- OR: `MAE: ___ vs baseline ___ (___% improvement)`

**Visual:** Bar chart — predicted top-10 zones for "tomorrow" highlighted on map

**Temporal cliff disclosure (shows honesty = credibility):**
> *"We don't claim 'violations peak at 10 AM.' Our temporal patterns reflect enforcement shift recording — which is still operationally useful for patrol scheduling."*

**Why this slide wins:** Honesty about limitations + a real metric = credible. Judges reward this.

---

## SLIDE 6 — OPTIMIZE: STACKELBERG GAME THEORY + SIMULATION

**Title:** "Deploy 5 Teams. Cover 62% of Congestion Impact. Watch Violations Move."

**Demo action sequence:**
1. Open Simulation panel
2. Drag team slider: 3 → 5 → 8 teams
3. Map shows: green (covered), red (uncovered), yellow (spillover — where violations migrate)
4. Coverage % updates live: 62% with 5 teams

**Key concepts (one bullet each — no theory jargon):**
- **Stackelberg Game:** Police are the "leader" — allocate proportional to risk. Violators are "followers" — they adapt.
- **Violator Utility:** If enforcement probability × fine > time saved → violator moves. We model this.
- **Waterbed Effect:** Patrol one zone → violations don't disappear. They flow to neighbours. We show it.

**Speaking beat:**
> *"Violators are rational. You enforce here — they move there. Our game theory model predicts exactly where."*
> *[drag slider from 5 to 3]*
> *"With 3 teams? Coverage drops to 43%. These red zones are exposed. That's the resource case for more teams."*

**Why this slide wins:** Live simulation is the WOW moment. Tangible, interactive, memorable.

---

## SLIDE 7 — ARCHITECTURE (30 seconds, skip if time short)

**Title:** "Full Stack: Built in 3 Days on Permitted Tech Only"

```
MapMyIndia SDK (Maps + Distance Matrix + Nearby)
        ↓
Frontend: Vite + React + TypeScript (port 5173)
        ↓
FastAPI Backend (port 8000, JSON + pandas, no Docker)
        ↓
ML Pipeline: LightGBM | CatBoost | Stackelberg | Congestion Impact
        ↓
Gemini 2.0 Flash (zone explanations, cache-first)
        ↓
Data: 298,450 records | H3 grid resolution 9 | MapMyIndia enrichment
```

**Key compliance statements:**
- ✅ No OSM/OpenStreetMap — MapMyIndia only
- ✅ No PostgreSQL/Redis/Docker — JSON + in-memory pandas
- ✅ No external traffic data — MapMyIndia APIs provide real-time validation

---

## SLIDE 8 — CLOSE: WHAT WE BUILT, WHY IT WINS

**Title:** "Quantify. Predict. Optimize. A System That Actually Changes Patrol Decisions."

**The Three Pillars summary:**

| Pillar | What We Built | The Number |
|---|---|---|
| QUANTIFY | 6-factor Congestion Impact Score | 34.2 lane-hours/day blocked at top zone |
| PREDICT | LightGBM + CatBoost ensemble | `___% Precision@10` (fill from P2) |
| OPTIMIZE | Stackelberg game theory + spillover | 62% critical congestion covered with 5 teams |

**Closing line (memorise this):**
> *"Traffic police don't need another map with dots. They need to know: which violations choke traffic, where violations will be tomorrow, and where to send their five teams. ParkVision-Saathi answers all three."*

**Final screen state:** App open. Two-layer toggle visible. City Market Circle zone selected. Explanation panel showing.

---

## TIMING GUIDE

| Slide | Target Time | Hard Limit |
|---|---|---|
| 1 — Hook | 30 sec | 45 sec |
| 2 — Problem | 45 sec | 60 sec |
| 3 — Congestion Score | 60 sec | 75 sec |
| 4 — Live Demo (zone explain) | 60 sec | 90 sec |
| 5 — Predict | 45 sec | 60 sec |
| 6 — Simulate (WOW moment) | 75 sec | 90 sec |
| 7 — Architecture | 30 sec | 45 sec |
| 8 — Close | 30 sec | 45 sec |
| **TOTAL** | **6:15** | **7:30** |

> If demo runs long → skip Slide 7 entirely. Merge architecture into Slide 8 as one bullet.

---

## DEMO RELIABILITY PROTOCOL

**Before presenting:**
1. Start backend: `uvicorn app.main:app --reload` (port 8000)
2. Start frontend: `npm run dev` (port 5173)
3. Pre-load: open browser to morning_peak heatmap, City Market Circle selected
4. Verify: `/api/explain` returns cached response (not live Gemini call)
5. Verify: `/api/simulate` with 5 teams returns valid JSON
6. Kill internet connection — demo must survive offline

**Fallback if demo breaks:**
- Screenshots pre-loaded as backup slides (Person 3 takes these Day 3 morning)
- Narrate from screenshots: "Here's what the app shows..."
- Never apologise. Say: "Let me walk you through what this produces."
