# Script

# ParkVision-Saathi — Video Script

---

## SCENE 1 — INTRODUCTION

*[Screen: black. City timelapse of Bengaluru traffic fading in. ]*

**Narrator:**
Every day, Bengaluru generates nearly two thousand parking violation records. Officers patrol, tickets get filed, and tomorrow it happens again.

But here's what nobody's tracking — *which* of those violations are actually choking the city's roads. A scooter parked on a side lane is a nuisance. A double-parked bus blocking the approach to a major junction is costing tens of thousands of commuter-hours daily.

The system treating both of those the same isn't a data problem. It's a visibility problem.

*[Logo fades up: ParkVision–Saathi. Tagline appears word by word:]*

**"Quantify. Predict. Optimize."**

---

## SCENE 2 — THE PROBLEM

*[Cut to: split screen — one side shows a quiet lane with a parked car, other side shows a blocked junction with buses]*

**Narrator:**
Today, traffic enforcement is reactive and habit-driven. Patrol teams are sent to where violations are *frequent* — not where they *hurt most*. That's because no system exists to measure the difference.

The dataset we're working with has two hundred and ninety-eight thousand violation records across Bengaluru — one hundred and fifty-one days of enforcement data, fifty-four police stations, complete location and violation type for every record.

*[Animated callouts appear: 298,450 records / 54 stations / 169 named junctions / Top zone: 5,838 violations at Elite Junction]*

But here's what's missing from every single row: traffic speed. Queue lengths. Road capacity. There is zero direct congestion data. That's the honest reality — and it's exactly the gap we built to close.

---

## SCENE 3 — OUR SOLUTION

*[Cut to: the three pillars graphic animating in, one by one]*

**Narrator:**
ParkVision-Saathi answers three questions that enforcement currently can't.

**Quantify** — Which violations actually choke traffic? We compute a Congestion Impact Score per zone, weighted by lane blockage, junction throughput, access blockage, vehicle size, and validated against real MapmyIndia travel-time data. Every score is transparent, documented, and defensible.

**Predict** — Where will tomorrow's hotspots be? A LightGBM-Poisson ensemble forecasts violation counts per H3 zone, using lag features, rolling averages, and calendar effects — trained on the same spatial grid as the map itself.

**Optimize** — Given five patrol teams, where should they go? A simplified Stackelberg game models how violators rationally respond to enforcement — and allocates teams to zones where deployment actually changes behaviour, not just where the map looks red.

---

## SCENE 4 — THE WEBSITE

*[Screen recording: browser opens to the ParkVision-Saathi dashboard. Dark mode, Bengaluru map centred, heatmap visible.]*

**Narrator:**
This is the ParkVision-Saathi dashboard — built for a traffic shift commander who needs to make deployment decisions fast.

At the top, you select your police station — we cover all fifty-four in Bengaluru. Alongside that, a time controls header lets you filter the entire view by time bucket — night, morning peak, midday, or afternoon — reflecting the actual enforcement windows in the data.

The map occupies the centre. Everything around it is context that makes it actionable.

---

## SCENE 5 — THE TWO-LAYER TOGGLE MAP

*[Narrator clicks "Violation Density" toggle. A dense, red heatmap fills the map.]*

**Narrator:**
This is Layer One — Violation Density. Where violations happen. It looks alarming, with red coverage across most of the city. This is what every other system shows.

*[Click: toggle to "Congestion Risk Impact"]*

Now watch what changes.

*[The heatmap shifts — fewer red zones, concentrated tightly at junctions and main road corridors. Side streets fade to green or yellow.]*

This is Layer Two — Congestion Risk. Fewer red zones, but concentrated exactly at the places that matter for traffic flow: main road junctions, intersection approaches, bus stop corridors.

These are *not the same map.* That difference is the entire answer to the question this project is built around. A quiet side street with fifty violations scores low. A junction approach with twenty violations, where a double-parked bus blocks the turning lane, scores CRITICAL.

*[Click on a zone — detail panel slides in on the right]*

---

## SCENE 6 — SPILLOVER LAYER

*[Toggle clicks to "Spillover" in the layer selector]*

**Narrator:**
There's a third layer — Spillover. This is the waterbed effect.

*[Map shows animated arrows radiating outward from enforced zones into neighbouring hexagons]*

When you place a patrol team in a high-risk zone, violations don't disappear — rational violators migrate to the nearest uncovered area. The spillover layer makes that migration visible before you commit to a deployment decision.

Each arrow represents displaced violator pressure. The receiving zone's risk score increases by up to twenty-five percent of the patrolled zone's patrol probability. It's conservation-enforcing — pressure that leaves one zone has to land somewhere.

---

## SCENE 7 — PRIORITY STRIP

*[Top of the map shows a horizontal strip of ranked zone chips, highlighted in amber/red]*

**Narrator:**
Across the top of the map runs the Priority Strip — the top zones for the currently selected station, ranked by Congestion Impact Score in real time as you change the time bucket or layer.

These aren't just the most-violated zones. They're the zones where violations have the highest measured impact on traffic flow. One click on any chip centres the map on that zone and loads its full profile.

---

## SCENE 8 — TIME SLIDER

*[Narrator drags the time bucket slider from "Morning Peak" to "Midday"]*

**Narrator:**
The time controls aren't decorative. The entire heatmap re-aggregates when you shift the time bucket.

Morning peak — six to ten AM — shows the enforcement-heavy window where most records were captured. Midday shifts the hotspot distribution. The data is honest about its limitations here: the afternoon bucket drops sharply after four PM because the dataset reflects enforcement shift patterns, not parking behaviour around the clock.

We call these outputs *predicted detection hotspots* — where deploying an officer will find violations. That framing is both honest and operationally useful.

---

## SCENE 9 — ZONE DETAIL PANEL

*[Narrator clicks a CRITICAL zone on the map. Right panel opens to ZoneDetail view.]*

**Narrator:**
Click any zone on the map and the Zone Detail panel opens.

At the top: a gauge running zero to one hundred — the Congestion Impact Score for this zone. Below that, the impact band: MINIMAL, MODERATE, SEVERE, or CRITICAL.

*[Scrolls down the panel — five component bars appear]*

The score breaks down into five components, each visualised as a horizontal bar.

**Lane Blockage** — thirty percent weight — driven by main-road and double-parking violations blocking lanes directly.

**Intersection Impact** — twenty-five percent — how many violations fall near named junctions, weighted by violation density.

**Traffic Degradation** — twenty-five percent — this one is different. This is the real MapmyIndia travel-time ratio for this zone. Peak travel time divided by baseline. A ratio of one-point-seven means traffic through this zone moves seventy percent slower than free-flow. This is the only externally measured signal in the model.

**Access Blockage** — ten percent — bus stops, school and hospital zones, road crossing violations.

**Vehicle Size** — ten percent — the proportion of heavy vehicles, which occupy disproportionate road space.

---

## SCENE 10 — ENFORCEMENT PRIORITY AND TRAFFIC IMPACT

*[Panel scrolls to show estimated lane-hours blocked and enforcement priority fields]*

**Narrator:**
Below the component breakdown, two key operational numbers.

**Estimated lane-hours blocked daily** — for the top zone, City Market, that number is thirty-one point two lane-hours. That's a concrete, documentable cost, derived from the violation mix and vehicle type distribution. Not a vague "high risk" label.

**Enforcement Priority** — a separate score from the Congestion Impact Score. CIS measures congestion. Enforcement Priority measures where deploying a team will have the largest deterrence effect given the zone's history. A zone can have high CIS but lower enforcement priority if it's already covered — and vice versa.

This distinction is what makes the two-layer toggle meaningful in practice: you can see where congestion is worst, and separately, where enforcement investment will do the most good.

---

## SCENE 11 — ROUTE AND AI ASSISTANCE

*[Panel shows a "Route now →" button. Narrator clicks it. Map draws a route from the selected station to the zone.]*

**Narrator:**
Once a zone is prioritised, the officer needs to get there. Clicking Route Now draws an optimal route from the current station to the selected zone, powered by the MapmyIndia Routing API.

*[Chat Panel slides open on the right — AI explanation appears]*

Alongside the route, the AI Assistance panel generates a plain-language explanation of the zone — why it scores the way it does, what the dominant violation type is, what the MapmyIndia travel data shows, and what action is recommended.

*[Text on screen: "Upparpet — Elite Junction. CIS: 87. Main-road parking blocks 1.4 lanes near Elite Junction. Double parking observed in 4.2% of records. MapmyIndia travel-time ratio: 1.62×. Recommend immediate enforcement during 10:00–12:00."]*

This isn't a chatbot. Every sentence is built from real data fields — violation counts, junction names, travel-time ratios. There are no hallucinated numbers, no invented road names. The grounded template fallback ensures the explanation is accurate even without a live API connection.

---

## SCENE 12 — SIMULATION PANEL

*[Narrator clicks to the Simulation tab in the right panel. A slider appears: "Patrol Teams: 1–20."]*

**Narrator:**
Now the most powerful feature — the What-If Simulation.

*[Drags slider from 3 to 5]*

You're a shift commander. You have five teams available tonight. Where should they go?

*[Map updates: green circles appear on covered zones, red on uncovered high-risk zones, yellow arrows show spillover zones]*

With five teams, the Stackelberg model covers sixty-two percent of CRITICAL and SEVERE zones, leaving four high-risk zones uncovered. The spillover layer activates automatically — those yellow zones are where violator pressure migrates when the covered zones are patrolled.

*[Slider drags to 8]*

Add three more teams. Coverage jumps to eighty-seven percent. The remaining uncovered zones are lower-CIS side streets where enforcement impact is marginal.

*[Panel below slider shows: Coverage %, Uncovered High-Risk Zones list, Spillover Zones table]*

The simulation runs in zero latency — it reads from pre-computed coverage data across all team counts from one to twenty, so the map updates instantly with no API call at demo time.

---

## SCENE 13 — FORECAST PANEL

*[Narrator clicks to Forecast tab]*

**Narrator:**
The Forecast panel answers tomorrow's question before it arrives.

*[Panel shows a list of predicted hotspot zones for the next day, ranked by predicted violation count]*

The LightGBM-Poisson model was trained on the same H3 hexagonal grid as the map — so predicted hotspots align exactly with the zones you see on the heatmap. There's no translation layer between the model and the visual.

Features include lag violations from the previous day and the previous week, seven and fourteen-day rolling averages, day-of-week, is-weekend, and the zone's historical rank. Trained on November through February, validated on March, tested on April.

*[Accuracy metrics appear: Precision@10 = 0.45 on H3 fine grain, 0.68 on coarser grid]*

We report the real accuracy numbers — not just the best-case figure. Precision at ten on fine-grained H3 cells is zero-point-four-five. On the coarser grid it reaches zero-point-six-eight. The honest answer is that eight days of April test data is a limited window — and we say so directly in the interface.

---

## SCENE 14 — GAME THEORY PANEL

*[Narrator clicks to Game Theory tab]*

**Narrator:**
The Game Theory panel makes the strategic reasoning visible.

*[Panel shows two columns: Patrol Probabilities per zone, and Violator Expected Utility per zone]*

Police are the leader in a Stackelberg game — they commit to a mixed-strategy patrol distribution. Violators are rational followers who best-respond to that strategy.

Patrol probability is allocated proportional to risk score raised to the power of one-point-five — a deliberate emphasis on high-risk zones. The violator column shows net expected benefit per zone: the value of parking illegally, discounted by the probability of getting caught, minus the fine. Zones where this is still positive are the strategic gaps — where rational violators will concentrate even under optimal patrol.

*[Arrows on the map highlight zones where violator utility is highest]*

This is the difference between naive hotspot coverage and game-theoretic enforcement. A naive system covers the top-five violation zones. The Stackelberg model asks: given that coverage, where will violations migrate? And it answers that question before you deploy.

---

## SCENE 15 — SELF-VALIDATING AGENT

*[Narrator clicks to Agent tab. A log appears with entries per zone.]*

**Narrator:**
The self-validating agent is the intellectual backbone of the system.

After the Congestion Impact Scores are computed, an agentic loop runs across every top zone. For each one, it reads the raw CIS, checks what travel-time ratio that score implies, then compares it against the *actual* MapmyIndia travel-time ratio measured for that zone.

Where the model overestimated — perhaps a high-violation zone on a wide arterial road that flows well — the agent calibrates the score down. Where the model underestimated — a junction with fewer recorded violations but severe measured slowdown — the agent calibrates up.

*[On screen, agent log entry appears:]"Subedar Chatram Road — adjusted 89 → 72: MapMyIndia shows only 1.08× travel time, not the 2.77× the raw score implied. Wide road absorbs parking impact."*

Every calibration is logged in plain English. The update is bounded and trust-weighted — a blend of eighty percent original score and twenty percent MapmyIndia-implied score, capped between zero and one hundred. No LLM, no network call at runtime. Fully deterministic, fully offline.

Across our dataset: six zones confirmed accurate. Three adjusted upward. One adjusted downward. The AI doesn't just predict — it checks its own work against reality.

---

## SCENE 16 — AI ASSISTANCE (CHAT PANEL)

*[Chat Panel opens. Narrator types a zone name or clicks Explain on a zone.]*

**Narrator:**
Finally, the AI Assistance panel brings everything together in a form any officer can act on immediately.

The system resolves explanations in three tiers. First, a pre-generated cache — instant, no API call. Second, a live Gemini call if a key is configured and network is available. Third, a grounded template fallback that builds the explanation purely from verified data fields.

*[Explanation text animates in]*

The result is a plain-language briefing: what the zone scores, why it scores that way, what the dominant violation type is, what MapmyIndia's traffic data confirms, and what the recommended enforcement window is.

Every number in that explanation comes from a real data file. There is no guessing, no hallucination, no generic phrasing detached from the actual zone. The AI explains the data — it doesn't invent it.

---

## CLOSING

*[Cut back to city aerial shot. Logo reappears.]*

**Narrator:**
ParkVision-Saathi doesn't add more data to a problem that already has data. It adds the one thing that was missing — the ability to see which violations actually matter, predict where they'll be tomorrow, and deploy the right teams to the right places before the congestion begins.

*[Three words appear on screen, one at a time:]*

**Quantify.Predict.Optimize.**

*[Logo holds. Fade to black.]*

---

**Total estimated runtime: ~4.5–5 minutes at natural narration pace.**
Each scene maps to a screen recording segment — you can trim or expand any scene independently without breaking the flow.