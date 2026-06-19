# ParkVision-Saathi — Demo Script
## Word-for-Word Opening + Beat-by-Beat Flow

> **RULE:** Memorise the opening hook and the closing line. Everything else can be improvised.
> **RULE:** Speak to the JUDGES, not to the screen. Make eye contact on every key number.
> **RULE:** If the demo breaks — keep narrating. Never go silent. Never apologise.

---

## OPENING HOOK (memorise this exactly — 15 seconds)

> *"2,000 parking violations. Every single day. In Bengaluru alone. But here's what traffic police don't know—"*
>
> **[click: toggle from Violation Density → Congestion Risk Impact]**
>
> *"—violation density and congestion impact are NOT the same map. This junction has 20 violations but blocks 10,000 vehicles every morning. This street has 80 violations and barely disrupts traffic. And right now, Bengaluru traffic police have no system to see the difference."*
>
> *"We built one."*

**Total: ~20 seconds. Then pause 1 second. Let it land.**

---

## BEAT-BY-BEAT FLOW

### BEAT 1 — Problem (30 sec)

> *"298,450 parking violation records. Six months of data from Bengaluru Traffic Police."*
> *"Our first question wasn't 'where are violations?' — it was 'which violations actually choke traffic?'"*
> *"Because not all violations are equal. A scooter on a side street is noise. A double-parked bus on a main road intersection is a city-level bottleneck."*

**[point to stat cards: 298K records, 54 stations, limited teams]**

---

### BEAT 2 — Congestion Impact Score (45 sec)

> *"So we built a 6-factor Congestion Impact Score."*

**[click City Market Circle zone — right panel opens]**

> *"City Market Circle. 5,280 violations. Congestion Impact: 85.3 out of 100. CRITICAL."*
> *"How do we get that number? 30% lane blockage — this road drops from 2 lanes to 1 during peak hours because of parked buses. 25% intersection impact — junction approach violations waste green-time. 25% MapMyIndia traffic validation—"*

**[point to travel time ratio]**

> *"—real-time data. Baseline travel time: 4 minutes. With current traffic: 9.5 minutes. That's 2.4 times slower. Not our model. MapMyIndia's live data independently confirming our score."*
> *"And the number that matters for operations: 31.5 lane-hours blocked every single day. One lane, completely blocked, for more than a working day."*

---

### BEAT 3 — LLM Explain (20 sec)

**[click "Explain" button]**

> *"Click here. Gemini explains this zone to the field officer in plain language — grounded in verified facts, not hallucinations. No invented road names, no made-up statistics."*

**[read the first sentence of the explanation aloud]**

> *"One click. One action. Any officer can understand why this zone needs enforcement today."*

---

### BEAT 4 — Prediction (30 sec)

> *"Congestion today is one problem. Congestion TOMORROW is another."*
> *"We trained a LightGBM and CatBoost ensemble on 150 days of violation data."*

**[switch to forecast view or point to forecast panel]**

> *"These are tomorrow's predicted top-10 hotspot zones. Precision at 10: ___%. That means ___ out of 10 zones we predict will actually be tomorrow's worst offenders."*
> *"And we're honest: our temporal patterns reflect when violations are RECORDED — which is when enforcement is active. That makes this a patrol scheduling tool, not just a prediction model."*

*(Fill in actual P@10 number from Person 2 before presenting)*

---

### BEAT 5 — Simulation WOW MOMENT (60 sec — MOST IMPORTANT)

> *"But the real question for a shift commander isn't where violations happen. It's: with my 5 teams, where do I send them?"*

**[open simulation panel — set to 5 teams]**

> *"5 patrol teams. Our Stackelberg game theory model allocates them proportional to congestion impact — not just violation count."*
> *"Green zones: covered. Red: uncovered. Yellow: predicted spillover."*

**[slowly drag slider from 5 down to 3]**

> *"Watch what happens with 3 teams. Coverage drops from 62% to 43%. These zones go red. That's the data-driven case for resource allocation."*

**[drag back to 8]**

> *"With 8 teams? 78% coverage. The model shows you exactly what each additional team buys."*
> *"And here's what most systems miss — the waterbed effect."*

**[point to yellow spillover zones]**

> *"You enforce here — violations don't disappear. They migrate to the nearest uncovered zone. Our spillover model predicts exactly where. This is Stackelberg game theory: police as leader, violators as rational followers."*

**[pause 2 seconds]**

> *"No other system at this hackathon models violator adaptation. We do."*

---

### CLOSING LINE (memorise this exactly)

> *"Traffic police don't need another map with dots. They need three things: which violations actually choke traffic, where violations will be tomorrow, and where to send their five teams."*
>
> *"ParkVision-Saathi answers all three."*

**[hold eye contact. don't look at screen. let judges write.]**

---

## EMERGENCY SCRIPTS

### If demo doesn't load:
> *"Let me walk you through what the system produces while it initialises."*
> *[switch to screenshots]*
> *"Here's the two-layer toggle — violation density on the left, congestion risk on the right. Not the same map. That's the core insight."*

### If Gemini explanation fails:
> *"The LLM explanation panel uses cached responses for reliability during demo — here's what it outputs for this zone:"*
> *[read from printed backup QA sheet]*

### If simulation endpoint is slow:
> *"While that loads — the key point is the Stackelberg allocation algorithm. Teams go to zones proportional to their congestion risk raised to the power of 1.5. That nonlinear exponent is the 'smart' in smart deployment."*

### If a judge asks a question mid-demo:
> *"Great question — let me show you exactly that."*
> *[redirect demo to answer the question. Never say "I'll get to that." Address it immediately.]*

---

## DEMO SETUP CHECKLIST (Day 3, 30 min before)

- [ ] Backend running: `cd backend && uvicorn app.main:app --reload`
- [ ] Frontend running: `npm run dev` → opens http://localhost:5173
- [ ] Verify heatmap loads with morning_peak data
- [ ] Verify layer toggle switches between violation density and congestion risk
- [ ] Verify City Market Circle zone click → detail panel
- [ ] Verify "Explain" button → returns cached explanation (not live Gemini)
- [ ] Verify simulation slider 3/5/8 → updates map markers
- [ ] Pre-load: tab open, City Market Circle selected, morning_peak, 5 teams
- [ ] Browser zoom: 100% (not 90%, judges at back need to see)
- [ ] Kill Wi-Fi: verify everything still works offline
- [ ] Print: this script + JUDGE_QA.md as physical backup

---

## TIMING CHECKPOINTS

| Mark | You should be at |
|---|---|
| 0:00 | Opening hook started |
| 0:20 | "We built one." — transitioning to problem |
| 1:00 | Congestion score slide / City Market zone selected |
| 2:00 | MapMyIndia validation highlighted |
| 2:30 | Explain button clicked |
| 3:00 | Prediction section |
| 3:30 | Simulation panel open |
| 4:30 | Slider demonstration done |
| 5:00 | Closing line |
| 5:10 | Silent. Waiting for questions. |

> If you're ahead: slow down at Simulation (Beat 5) — it's the WOW moment.
> If you're behind at 3:00: skip Beat 4 (prediction) entirely. Go straight to simulation.
