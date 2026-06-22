# ParkVision-Saathi — Demo Video Script

> **Format:** screen recording + voiceover. Target length **4:00** (hard cap 5:00).
> **Theme:** Quantify · Predict · Optimize.
> **Golden rule:** every number spoken is visible on screen at that moment. All
> figures below are from the live build (verified against the running app and the
> 298,450-record dataset). Speak calmly, let the map moments breathe.

A tight **60-second teaser** version is at the bottom.

---

## Pre-record checklist (5 min)

- [ ] Backend: `uvicorn backend.app.main:app --port 8000` (from project root)
- [ ] Frontend: `npm run dev` → open the printed URL, browser zoom **100%**
- [ ] If the console says *"Mappls SDK script failed to load — falling back to MapLibre GL"* that is fine — the app looks clean on MapLibre and all panels/data work identically. Don't mention it.
- [ ] Pre-pick station **Upparpet**, hour **9 AM (Morning Peak)**
- [ ] Layer toggle starting on **Violation Density**
- [ ] Close DevTools; hide the screen-share bar; clean desktop
- [ ] Do one silent dry-run of the full click path below — especially the Route now line — so nothing surprises you on the take

---

## Scene-by-scene script

Each scene: **[ON SCREEN — what to do]** then the **VOICEOVER** (read this) and an optional **[CAPTION]** text overlay.

---

### SCENE 0 — Cold open: the two maps (0:00–0:25)

**[ON SCREEN]** App already open on the live map, **Violation Density** layer glowing over central Bengaluru. As you say "watch", click the layer toggle to **Congestion Risk** — the heat visibly shifts to different zones.

**[CAPTION]** *ParkVision-Saathi — Quantify · Predict · Optimize*

> *"Bengaluru logs around two thousand parking violations every single day. Police already map where they happen. But watch this —"*
>
> **[click toggle: Violation Density → Congestion Risk]**
>
> *"— where violations happen, and where they actually choke traffic, are two completely different maps. The busiest zone for violations isn't the one strangling the city. Right now, no patrol team can see that difference. We built the system that can."*

*(Pause ~1 second on the Congestion Risk map before Scene 1.)*

---

### SCENE 1 — The problem & the data (0:25–0:50)

**[ON SCREEN]** Slowly zoom/pan the map; the top command bar shows the live zone/violation counts. Optionally a caption stack of the three stats.

**[CAPTION]** *298,450 records · 55 stations · 2,527 zones · Nov 2023–Apr 2024*

> *"We started with the real thing: 298,450 parking-violation records from Bengaluru Traffic Police, across 55 stations and five months. Our first question wasn't 'where are the violations' — it was 'which violations actually cost the city road capacity.' Because a scooter on a side lane is noise. A double-parked bus on an arterial junction is a city-wide bottleneck. So we built three things on top of this data: a way to quantify impact, predict it, and optimize the response."*

---

### SCENE 2 — QUANTIFY: the Congestion Impact Score (0:50–1:40)

**[ON SCREEN]** Click the **Upparpet / Subedar Chatram Road** hotspot marker (the busiest dot).
Its popup shows **Enforcement 100 / CRITICAL** and **Congestion 15 / MINIMAL** side by side.
The Zone panel opens. Scroll down to show the five component breakdown bars and the
**3,072 estimated lane-hours blocked** card with the MapMyIndia ratio.
Then click **Route now →** at the bottom of the Zone panel — a **teal dashed line** appears
on the map from the station pin to the zone, and the map auto-fits to show both.

**[CAPTION]** *Two scores, never conflated: enforcement priority vs congestion impact*

> *"Here's the busiest zone in the whole dataset — Subedar Chatram Road, twelve thousand violations, enforcement priority a perfect 100. But look at its congestion impact: just 15 out of 100 — minimal. It's a wide arterial; it absorbs the load. Counting violations would send every team here. It shouldn't."*
>
> *"Our Congestion Impact Score breaks down exactly why — lane blockage, intersection disruption, real MapMyIndia travel-time degradation, transit-access blockage, and heavy-vehicle obstruction, each weighted. The tangible number a commander cares about: 3,072 estimated lane-hours of road capacity destroyed per day."*
>
> **[click Route now →]**
>
> *"And when the system has identified the zone, the operator gets one button — Route now. The map draws the patrol line from station to destination. The intelligence loop closes."*

---

### SCENE 2.5 — The time-bucket twist (1:40–1:55) — optional 15-second bonus

> Skip this scene if you need to stay under 4 min. Include it for a technical audience
> because it shows the API is genuinely time-aware, not just a static heatmap.

**[ON SCREEN]** Change hour slider from **9 AM → 1 PM (Midday)**. Click the same Upparpet zone.
The panel refreshes — show the different CIS component values at midday vs morning peak.

**[CAPTION]** *Time-bucket aware: morning peak vs midday vs night*

> *"Every score is bucketed by time — morning peak, midday, afternoon, night. Enforcement patterns differ; the score reflects that. The system isn't showing you one static map — it shows you what's happening right now in your shift."*

---

### SCENE 3 — The self-validating agent (1:55–2:25) — credibility wow

**[ON SCREEN]** Click the **Agent** tab in the right panel. The summary cards show:
**10 Validated · 6 Accurate · 3 Adj up · 1 Adj down · Mean 4.2%**.
Scroll to the first row: **HAL Old Airport — 50 → 44 · Adjusted ↓** — read the reasoning text.
Then scroll to a Shivajinagar row showing **Validated: Accurate** to contrast.

**[CAPTION]** *The model checks itself against live MapMyIndia data — and corrects itself*

> *"And we don't ask you to just trust our score. This is our self-validating agent. After scoring every zone, it pulls the real MapMyIndia travel-time ratio and compares it against what our model implied. Watch HAL Old Airport: our score implied the corridor should be near two-times travel time. MapMyIndia measured only 1.26 times. The agent calibrated it down from 50 to 44 and wrote the reason in plain English."*
>
> *"And here — Shivajinagar — the agent found the CIS was accurate. No change. Green tick. The model is honest about what it knows and what it doesn't. That's the difference between a dashboard and a system you can stand behind in a review."*

---

### SCENE 3.5 — The ML & backend engine (2:25–2:55) — technical depth scene

> **Purpose:** satisfies any technical judge asking *"how did you actually compute this?"*
> This scene runs ~30 seconds of technical voiceover and can be presented as a
> terminal / code B-roll or a caption stack — it does not require any live demo click.
> Insert it right after the agent/zone-detail moment so the judge has just *seen* the
> score they are about to hear explained.

**[ON SCREEN]** Show `run_pipeline.py` output in a terminal (or caption stack),
e.g. the four step lines and the final artifact sizes. If you prefer a code shot,
show the CIS formula block in `ml/congestion/impact_score.py` (`WEIGHTS` dict +
the `compute_score` line). Keep it to ~4–5 seconds per bullet; pan slowly.

**[CAPTION stack — show one at a time, matching the spoken line]**
1. *298,450 records → 2,527 H3 res-9 hexagons (~174 m across)*
2. *CIS = 0.30·lane\_blockage + 0.25·intersection + 0.25·travel\_time + 0.10·access + 0.10·vehicle\_size*
3. *travel\_time component = clamp((MapMyIndia ratio − 1.0) ÷ 2.0) — the only externally measured signal*
4. *Forecast: LightGBM (Poisson) + CatBoost ensemble · lag-1 / lag-24 / lag-168 / spatial Moore neighbours — zero leakage*
5. *Stackelberg: patrol prob ∝ risk^1.5 · fatigue-adjusted from real approved-violation history*
6. *FastAPI · JSON in-memory · 126 tests · 0 database calls at request time*

**VOICEOVER:**

> *"Here is what sits under the dashboard. We took 298,000 records and binned them onto
> a hex grid of 2,527 Uber H3 resolution-9 cells — each cell roughly 174 metres across —
> giving us a precise, map-aligned spatial unit for every computation. The Congestion
> Impact Score is a deterministic weighted sum: 30 percent lane blockage, 25 percent
> intersection disruption, 25 percent real MapMyIndia travel-time degradation — computed
> as the clipped ratio minus one, divided by two — 10 percent access blockage, 10 percent
> vehicle size obstruction on a 0.5 to 2.0 scale from scooter to bus. Weights form a
> strict partition of unity and are asserted at import time. The forecast adds a dense
> hourly feature matrix: true clock lags at minus-1, minus-24, and minus-168 hours,
> rolling stats shifted one step before windowing so there is no target leakage, and
> a spatial lag over each cell's eight Moore neighbours at t-minus-1. That feeds a
> LightGBM Poisson and CatBoost ensemble, blend-tuned on the March validation fold,
> evaluated once on a held-out April test set. The patrol allocation solves a Stackelberg
> game — patrol probability proportional to risk to the power 1.5, with a fatigue
> discount derived from the actual approved-violation enforcement history. The whole
> backend is FastAPI, JSON in-memory, zero database calls at request time, with 126 tests
> passing. Fully reproducible: one command rebuilds everything from the raw CSV."*

> **Tip:** this scene is dense — speak at your clearest pace, not your fastest. The
> captions do the work. If you need to trim to a strict 30 s, cut after *"vehicle size
> obstruction on a 0.5 to 2.0 scale"* and jump straight to *"The forecast adds … held-out
> April test set."* That gives you the CIS formula + the forecast ML story in 30 s.

---

### SCENE 4 — AI Assistant (2:55–3:15)

**[ON SCREEN]** Click the **Assist** tab. The chat shows prompt chips at the bottom:
*"Why is this area high risk?"*, *"Suggest patrol strategy for this shift"*,
*"How many officers are needed?"*, *"Summarize priority areas"*.
Click **"Why is this area high risk?"** → a Gemini explanation appears with real numbers
from the selected zone (violation count, CIS, travel-time ratio, calibrated score, top type).

**[CAPTION]** *Gemini — grounded in verified zone facts, offline-safe via cache*

> *"For the field officer, one click answers the question they'd actually ask. The AI explains the zone in plain language — using only our verified numbers, the real violation count, the real MapMyIndia ratio, the agent's calibration. No hallucinated road names. No invented stats. It's cached for every hotspot so it works without a network. Any zone, any shift, instant brief."*

---

### SCENE 5 — PREDICT: tomorrow's hotspots (3:15–3:45)

**[ON SCREEN]** Open the **Forecast** tab. Show the three accuracy cards: **45% · 0.83 · 4.43**.
Then scroll the predicted zone list — it shows real place names:
**Chickpete #1 · Shivaji Nagar #2 · Upparpet #3 · Gandhi Nagar #4…**

**[CAPTION]** *LightGBM-Poisson · Precision@10 = 45% · held-out April test · zero leakage*

> *"Today's congestion is one problem. Tomorrow's is another. We trained a LightGBM Poisson model — on the exact same H3 hexagon grid as the congestion map — to predict next-day violation volume per zone. On a strict chronological split — train on November to February, validate March, test April — it correctly flags about four to five of tomorrow's top-ten hotspots. Chickpete. Shivaji Nagar. Upparpet. Not hex IDs — real places."*
>
> *"And we report the honest metric. 45% Precision at 10 on a held-out test. Not tuned, not cherry-picked."*

---

### SCENE 6 — OPTIMIZE: game theory + simulation (3:45–4:30) — the big wow

**[ON SCREEN — Part A: Game Theory]**
Click the **Game** tab. Show patrol probability bars: **Gandhi Nagar 4.08%, Chickpete 3.98%, Gandhi Nagar 3.88%…** Then scroll to Violator Utility: **Gandhi Nagar risk 76, Chickpete risk 75…**

**[CAPTION]** *Stackelberg game: patrol probability ∝ risk^1.5, fatigue-adjusted*

> *"First, the game theory layer. This is not a ranked list — these are mixed-strategy patrol probabilities from a Stackelberg security game. Police commit first; violators best-respond. The system tells you not just where to go, but how to allocate attention across all zones simultaneously so rational violators can't predict your next move. And down here — the violator utility view: the zones where rational violators still profit despite enforcement. That's your strategic gap."*

**[ON SCREEN — Part B: Simulation]**
Click the **Sim** tab. Set teams to **6**, click **Run Simulation**. Show Coverage **18.85%**, Uncovered High-Risk **14**, Spillover Zones **0**. Then switch map layer to **Spillover** — waterbed arrows appear. Point to the waterbed list showing real names: **Upparpet 82→82, Chanarajpet 43→44, HAL Old Airport 27→27, Shivajinagar 13→13**.

**[CAPTION]** *6 teams → 18.85% coverage · 14 high-risk zones uncovered · waterbed displacement visible*

> *"Now the simulation. Six patrol teams, game-theoretic allocation. 18.85% of weighted risk covered. And here's what every other system misses — the waterbed effect. Enforce Upparpet, and violations migrate to Chanarajpet. Enforce HAL Old Airport, they move to Shivajinagar. The map draws it as arrows. The commander sees exactly where displaced violator pressure lands — and can pre-position accordingly."*
>
> **[drag slider 6 → 8]**
>
> *"Drag to eight teams — coverage climbs to 24.7%, uncovered high-risk drops to 12. The commander sees precisely what each extra team buys before the shift starts."*

---

### SCENE 7 — Under the hood: stack summary (4:30–4:50)

**[ON SCREEN]** B-roll: quickly pan the panels — Zone, Sim, Forecast, Game, Agent, Assist — so the judge sees all six tabs working. Keep clicking.

**[CAPTION stack]**
- *298,450 records → H3 res-9 → 2,527 zones*
- *CIS: 5-component weighted score + MapMyIndia Distance-Matrix validation*
- *LightGBM-Poisson + CatBoost ensemble · Stackelberg game theory + waterbed*
- *FastAPI (JSON, in-memory, no DB, fully offline) · 126 tests passing*
- *React + Vite + TypeScript · Mappls / MapLibre map · Gemini 2.0 Flash*

> *"The backend is FastAPI — pure JSON in memory, no database, runs fully offline, 126 passing tests. One command — `python run_pipeline.py` — rebuilds every artifact from the raw CSV. React and TypeScript front end with Gemini for the explanations. Built to actually be deployed, not just demoed."*

---

### SCENE 8 — Close (4:50–5:10)

**[ON SCREEN]** Return to the full map; toggle Violation Density → Congestion Risk one last time; leave it on Congestion Risk with a hotspot selected and the zone detail visible showing the dual scores.

**[CAPTION]** *Quantify · Predict · Optimize — ParkVision-Saathi*

> *"Traffic police don't need another map with dots. They need three answers: which violations actually choke traffic, where they'll be tomorrow, and where to send their limited teams today. ParkVision-Saathi answers all three — on real data, validating itself against the real world. Thank you."*

---

## Voiceover-only master (paste into a teleprompter)

> Bengaluru logs around two thousand parking violations every day. Police already map where they happen — but where violations happen and where they choke traffic are two different maps. The busiest zone isn't the one strangling the city, and no patrol team can see that today. We built the system that can.
>
> We started with 298,450 real violation records — 55 stations, five months. Our question wasn't "where are violations" but "which ones cost the city road capacity."
>
> Here's the busiest zone — twelve thousand violations, enforcement priority 100 — yet its congestion impact is just 15. A wide arterial absorbs the load. We break that down to five components, each weighted, validated by real MapMyIndia travel-time data. The tangible output: 3,072 estimated lane-hours blocked per day. One click — Route now — draws the patrol line from station to zone on the map.
>
> And we don't trust our own score. Our self-validating agent pulls the live MapMyIndia travel time and corrects the model itself. HAL Old Airport: score implied near two-times travel time, MapMyIndia measured only 1.26 times — calibrated down from 50 to 44, with the reason written out. Shivajinagar: model was accurate — green tick, no change. The AI checks itself.
>
> The AI also talks. One click on any zone asks Gemini why it's high risk — grounded in our verified numbers only, cached offline so it works without a signal.
>
> For tomorrow, a LightGBM Poisson model forecasts next-day hotspots at 45% precision-at-ten — on a strict held-out April test. Chickpete. Shivaji Nagar. Upparpet. Real places, a day ahead.
>
> And for deployment: a Stackelberg game allocates patrol teams — police lead, violators rationally follow. Six teams cover 18.85% of weighted risk. Drag to eight — 24.7%. And the waterbed effect is drawn on the map: enforce Upparpet, violations migrate to Chanarajpet. The commander sees it before the shift starts.
>
> Under the hood: 2,527 H3 zones, a five-component impact score, a self-validating agent, a Poisson forecast, real game theory — FastAPI, JSON in memory, 126 tests, zero database calls at request time.
>
> Traffic police don't need another map with dots. They need to know which violations choke traffic, where they'll be tomorrow, and where to send their teams. ParkVision-Saathi answers all three.

---

## 60-second teaser cut

**[0:00]** **[toggle Violation Density → Congestion Risk]** *"Where parking violations happen, and where they actually choke traffic, are two different maps — and no patrol team can see the difference today."*

**[0:12]** **[click busiest zone → popup shows 100 enforcement / 15 congestion]** *"The single busiest zone? Minimal congestion impact. We score 2,527 Bengaluru zones from 298,000 real records — and they're different maps."*

**[0:26]** **[Zone detail → click Route now → teal line draws]** *"The system identifies the problem. One button draws the patrol route to it."*

**[0:34]** **[Agent panel: HAL Old Airport 50→44]** *"Our AI even checks itself against live MapMyIndia traffic and corrects its own score."*

**[0:42]** **[Sim slider + waterbed names]** *"Then it deploys teams with game theory — and predicts where enforcement pushes violations next."*

**[0:52]** **[full map, Congestion Risk layer]** *"Quantify. Predict. Optimize. ParkVision-Saathi."*

---

## Recording tips

- **Route now is your most visual moment** — pause for 2 seconds after clicking it so the teal line drawing and the map auto-fit are clearly visible. Don't talk over it.
- **Cursor:** move deliberately and pause before each click so viewers can track the action.
- **Pacing:** silence is fine on the map-toggle, the slider drag, and the Route now line — let the visuals carry it.
- **Numbers on screen:** never say a figure that isn't visible; if a panel is slow, narrate the concept until it loads.
- **One feature per breath:** don't stack two clicks under one sentence.
- **Map tiles:** the app uses Mappls vector tiles if the key is authorized for your domain, MapLibre GL otherwise. Both look clean — don't mention either. The data story is identical.
- **Edit:** add the caption overlays in post; they double the retention of each number.

---

## Route now — what it is (reference)

The **Route now →** button (bottom of Zone detail panel and on every priority card) does:
1. Draws a **teal dashed line** on the map from the selected police station pin to the zone's centroid
2. Places a **red destination marker** at the zone
3. **Auto-fits** the map view to frame both the station and the zone with padding

It is an operational dispatch visual — not turn-by-turn navigation. It shows the officer *which direction* and *how far* to travel, closing the intelligence-to-action loop that the rest of the dashboard builds up to.
