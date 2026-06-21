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
- [ ] Hard-refresh so Mappls loads (console should say "Mappls SDK loaded successfully")
- [ ] Pre-pick station **Upparpet**, hour **9 AM (Morning Peak)**
- [ ] Layer toggle starting on **Violation Density**
- [ ] Close DevTools; hide the screen-share bar; clean desktop
- [ ] Do one silent dry-run of the click path below so nothing surprises you on the take

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

### SCENE 2 — QUANTIFY: the Congestion Impact Score (0:50–1:35)

**[ON SCREEN]** Click the **Upparpet / Subedar Chatram Road** hotspot marker (the busiest). Its popup shows **Enforcement 100 / CRITICAL** and **Congestion 15 / MINIMAL** side by side. Then click a high-impact marker (**HAL Old Airport**) → the right **Zone** panel opens with the gauge, lane-hours, and component breakdown.

**[CAPTION]** *Two scores, never conflated: enforcement priority vs congestion impact*

> *"Here's the busiest zone in the whole dataset — Subedar Chatram Road, twelve thousand violations, enforcement priority a perfect 100. But look at its congestion impact: just 15 out of 100 — minimal. It's a wide arterial; it absorbs the load. Counting violations would send every team here. It shouldn't."*
>
> **[click HAL Old Airport zone → Zone panel opens]**
>
> *"Now this zone has fewer violations but the highest congestion impact in the city. Our Congestion Impact Score breaks down exactly why — lane blockage, intersection disruption, real travel-time degradation, transit-access blockage, and heavy-vehicle obstruction, each weighted. And the tangible number a commander cares about: the lane-hours of road capacity this zone destroys."*

---

### SCENE 3 — The self-validating agent (1:35–2:10) — credibility wow

**[ON SCREEN]** Open the **Agent** panel (left tool rail). Scroll to the **HAL Old Airport** row showing **50 → 44 · Adjusted ↓** and its reasoning text.

**[CAPTION]** *The model checks itself against live MapMyIndia data — and corrects itself*

> *"And we don't ask you to just trust our score. This is our self-validating agent. After scoring every zone, it pulls the real MapMyIndia travel-time ratio and checks our model against live traffic. Watch what it did here: our score implied this corridor should be crawling at nearly two-times travel time. MapMyIndia measured only 1.26 times. So the agent calibrated the score down from 50 to 44 — and wrote the reason in plain English. Our AI caught its own overestimate, using third-party ground truth. That's the difference between a dashboard and a system you can defend."*

---

### SCENE 4 — LLM explanations (2:10–2:30)

**[ON SCREEN]** From the Zone panel click **Ask AI** (or open the **Assist** panel) → a Gemini explanation appears. Read its first line.

**[CAPTION]** *Gemini explanations — grounded in verified facts, offline-safe*

> *"For the officer in the field, one click turns all of this into plain language. Gemini explains the zone — grounded strictly in our verified numbers, no hallucinated roads, no invented stats — and it's cached so it works even with no signal. Any officer, any zone, instant context."*

---

### SCENE 5 — PREDICT: tomorrow's hotspots (2:30–3:00)

**[ON SCREEN]** Open the **Forecast** panel. Show the **45% Precision@10**, MAE/RMSE cards, and the predicted top-zone list (now with place names).

**[CAPTION]** *LightGBM-Poisson · held-out April test · Precision@10 = 45%*

> *"Today's congestion is one problem. Tomorrow's is another. We trained a LightGBM Poisson model on the same map grid to forecast next-day violation volume per zone. On a strict, leakage-free held-out test, it hits 45% precision at ten — it correctly flags about four to five of tomorrow's ten worst zones, a day ahead. And we're honest about the metric: this is genuine held-out accuracy, not a number we tuned to."*

---

### SCENE 6 — OPTIMIZE: game theory + simulation (3:00–3:50) — the big wow

**[ON SCREEN]** Open the **Sim** panel. Slider at **5 teams** → show **Coverage ~16%**, uncovered high-risk count, and the map markers. Then drag to **10 teams** → coverage climbs to ~30%. Switch the map layer to **Spillover** so the red **waterbed arrows** are visible; point to the **Waterbed Effect** list (now showing place names).

**[CAPTION]** *Stackelberg patrol allocation + violator adaptation (waterbed effect)*

> *"Now the question a shift commander actually asks: with my teams, where do I send them? We model this as a Stackelberg game — police lead, violators rationally respond. With five teams, the optimizer covers about 16% of the weighted hotspot risk, and it shows you exactly which high-risk zones stay exposed."*
>
> **[drag slider 5 → 10]**
>
> *"Double to ten teams and coverage roughly doubles — the commander sees precisely what each extra team buys. And here's what most systems ignore: the waterbed effect. Enforce a zone and violations don't vanish — they migrate to the nearest soft spot. Our model predicts where, and draws it on the map. Police as leader, violators as adaptive followers. That's optimization, not decoration."*

---

### SCENE 7 — Under the hood: what we built (3:50–4:25)

**[ON SCREEN]** B-roll: quickly pan the panels, or show a simple architecture caption while you talk. Keep clicking through tabs so it stays visual.

**[CAPTION stack]**
- *Data: 298,450 records → H3 res-9 → 2,527 zones*
- *CIS: 6-factor weighted score + MapMyIndia Distance-Matrix validation*
- *Self-validating agent · LightGBM-Poisson forecast · Stackelberg game theory*
- *FastAPI (JSON, in-memory, no DB, fully offline) · 126 tests passing*
- *React + Vite + TypeScript · Mappls vector SDK · Gemini 2.0 Flash*

> *"Under the hood: the raw records are cleaned and binned onto an H3 hex grid — 2,527 zones. The impact score fuses six factors and validates the traffic component against MapMyIndia's Distance Matrix. The forecast is a Poisson gradient-boosted model; the patrol layer is real game theory with violator utility and spillover. The backend is FastAPI — pure JSON in memory, no database, runs fully offline, with 126 passing tests. The front end is React and TypeScript on the MapMyIndia vector SDK, with Gemini for the explanations. Built to actually be deployed, not just demoed."*

---

### SCENE 8 — Close (4:25–4:45)

**[ON SCREEN]** Return to the full map; toggle once more Violation Density → Congestion Risk; leave it on Congestion Risk with a hotspot selected.

**[CAPTION]** *ParkVision-Saathi — which violations choke traffic, where they'll be tomorrow, where to send your teams.*

> *"Traffic police don't need another map with dots. They need three answers: which violations actually choke traffic, where they'll be tomorrow, and where to send their limited teams today. ParkVision-Saathi answers all three — on real data, validating itself against the real world. Thank you."*

---

## Voiceover-only master (paste into a teleprompter)

> Bengaluru logs around two thousand parking violations every day. Police already map where they happen — but where violations happen and where they choke traffic are two different maps. The busiest zone isn't the one strangling the city, and no patrol team can see that today. We built the system that can.
> We started with 298,450 real violation records — 55 stations, five months. Our question wasn't "where are violations" but "which ones cost the city road capacity."
> Here's the busiest zone in the data — twelve thousand violations, enforcement priority 100 — yet its congestion impact is just 15. A wide arterial absorbs the load. This other zone has fewer violations but the highest impact in the city; our score shows exactly why, down to the lane-hours of capacity destroyed.
> And we don't just trust our score — our self-validating agent pulls the live MapMyIndia travel time and corrects the model itself, here from 50 down to 44, with the reason written out. One click turns it into a grounded, offline-safe Gemini explanation for the field officer.
> For tomorrow, a LightGBM Poisson model forecasts next-day hotspots at 45% precision-at-ten on a strict held-out test. And for deployment, a Stackelberg game allocates teams — five teams cover about 16% of weighted risk, ten teams double it — and it predicts the waterbed effect: where enforcement pushes violations next.
> Under the hood: an H3 hex grid of 2,527 zones, a six-factor impact score validated against MapMyIndia, a self-validating agent, a Poisson forecast, real game theory — on a FastAPI backend that runs fully offline with 126 passing tests, and a React MapMyIndia front end.
> Traffic police don't need another map with dots. They need to know which violations choke traffic, where they'll be tomorrow, and where to send their teams. ParkVision-Saathi answers all three.

---

## 60-second teaser cut

**[0:00]** **[toggle the two maps]** *"Where parking violations happen, and where they actually choke traffic, are two different maps — and no patrol team can see the difference today."*

**[0:12]** **[click busiest zone → 100 enforcement / 15 congestion]** *"The single busiest zone for violations? Minimal traffic impact. We score all 2,527 zones on real congestion impact, from 298,000 records."*

**[0:28]** **[Agent panel: 50→44]** *"Our AI even checks itself against live MapMyIndia traffic and corrects its own score."*

**[0:38]** **[Sim slider 5→10 + waterbed arrows]** *"Then it deploys your teams with game theory — and predicts where enforcement pushes violations next."*

**[0:50]** **[full map, Congestion Risk]** *"Quantify. Predict. Optimize. ParkVision-Saathi."*

---

## Recording tips

- **Cursor:** move deliberately and pause before each click so viewers track the action.
- **Pacing:** silence is fine on the map-toggle and the slider drag — let the visuals carry it.
- **Numbers on screen:** never say a figure that isn't visible; if a panel is slow, narrate the concept until it loads.
- **One feature per breath:** don't stack two clicks under one sentence.
- **If Mappls shows the lighter fallback map,** it's fine — don't mention it; the data story is identical.
- **Edit:** add the caption overlays in post; they double the retention of each number.
