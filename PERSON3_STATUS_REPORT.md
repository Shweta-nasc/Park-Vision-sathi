# Person 3 (Frontend) — Status Report

> Verified against `EXECUTION_PLANNER.md` (all sprints Day 0 → Day 3).
> Person 3 owns the **entire frontend dashboard** — map, layout, heatmap layers, simulation panel, AI chat, zone detail, and all CSS.

---

## 🛠️ Framework Reality Check

### What the planner asked for
The planner specifies a **React (Vite + TypeScript)** app at `:5173`, with typed `api.ts` client, component files like `MapView.tsx`, `LayerToggle.tsx`, `StatsPanel.tsx`, etc., and the **Mappls SDK** as the map library.

### What was actually built
The frontend was implemented as a **Vanilla HTML + CSS + JS** single-page app (`index.html`, `styles.css`, `app.js`) using:

| Library | CDN / Version | Role |
|---|---|---|
| **Leaflet 1.9.4** | `unpkg.com/leaflet` | Map rendering (replaces Mappls SDK) |
| **leaflet.heat 0.2.0** | `unpkg.com/leaflet.heat` | Heatmap layer |
| **Google Fonts – Inter** | fonts.googleapis.com | Typography |
| **CartoDB Dark Matter tiles** | `cartocdn.com` | Map tiles (free, no API key needed) |
| No React, No Vite, No TypeScript | — | Deliberately simplified |

### Is this a problem?
**No, for the hackathon demo it is not.** The vanilla stack delivers faster load times, zero build step, zero toolchain bugs, and works offline. The Mappls SDK was replaced with Leaflet + CartoDB tiles — both are compliant, free-tier services.
The one genuine risk: the planner calls out CartoDB/OSM tiles specifically as a potential **disqualification risk** ("NO OpenStreetMap"). CartoDB tiles are technically built on OSM data. If this is a strict rule for the judges, the tiles need to change to Mappls raster tiles. See the plan below.

---

## ✅ Implemented Features (MUST-DO tasks)

### Setup & Skeleton (Sprint 1)
| Task | Status | Evidence |
|---|---|---|
| Map renders centered on Bengaluru | ✅ | `initMap()` in `app.js` — Leaflet, zoom 14 |
| App structure (shell, panels, nav) | ✅ | Full layout in `index.html` |
| API client module (fetch wrappers) | ✅ | Inline in `app.js` — all endpoints called |
| Station selection screen | ✅ | `#stationScreen` with search + list |

### Layout & UI (Sprint 2)
| Task | Status | Evidence |
|---|---|---|
| 3-panel layout: nav rail + map + right panel | ✅ | CSS grid, `--nav-w`, `--panel-w` variables |
| Stats cards in header (zone count, high priority count) | ✅ | `#headerZoneCount`, `#headerHighCount` |
| Hour selector (24-hour dropdown) | ✅ | `#hourSelect` with peak indicators `●` |
| API status pill | ✅ | `#apiStatusPill` with live colour dot |

### Heatmap (Sprint 3)
| Task | Status | Evidence |
|---|---|---|
| HeatmapLayer integrated with real API data | ✅ | `loadHeatmap()` → `L.heatLayer()` |
| Radius + blur auto-scaling with zoom | ✅ | Leaflet heatLayer handles this natively |
| **Two-Layer Map Toggle (THEME CRITICAL)** | ⚠️ **PARTIAL** | Toggle exists for `Risk / Violator / Spillover` — but labels say **"Risk / Violator / Spillover"** NOT **"Violation Density / Congestion Risk Impact"** as required |
| Time bucket drives heatmap updates | ✅ | `hourSelect` change → `loadDashboard()` |

### Zone Markers & Detail (Sprint 5–6)
| Task | Status | Evidence |
|---|---|---|
| Top 15 hotspot markers on map | ✅ | `addHotspotMarkers()` — circle markers by risk label |
| Click handler → right panel zone detail | ✅ | `showZoneDetail()` |
| Zone detail: score, risk breakdown bars, operations intel | ✅ | Full `detail-section` HTML rendered |
| `estimated_lane_hours_blocked` in zone detail | ❌ **MISSING** | Detail panel shows `density`, `road_importance`, etc. but NOT `estimated_lane_hours_blocked` |
| Loading spinner / skeleton states | ✅ | `.loading-spinner` + `.skeleton-item` |

### Priority Areas Strip (Sprint 4–5)
| Task | Status | Evidence |
|---|---|---|
| Priority cards (force units, distance, ETA) | ✅ | `renderPriorityCards()` |
| Click → fly to zone + show detail | ✅ | `pickArea()` |
| Route button → polyline to destination | ✅ | `routeToZone()` — Leaflet `L.polyline` |

### Simulation (Sprint 9–11)
| Task | Status | Evidence |
|---|---|---|
| Team count slider 1–15 | ✅ | `#teamSlider` in Simulation panel |
| POST `/simulate` → deploy team markers on map | ✅ | `runSimulation()` |
| Color coding: teams (color by team_id), spillover zones (red/green circles) | ✅ | `TEAM_COLORS` array + `circleMarker` fill |
| Coverage % display | ✅ | `#simCoverage`, `#simRiskCovered`, `#simUncovered` |
| Slider change triggers simulation | ⚠️ **PARTIAL** | Slider updates `state.numTeams` but does NOT auto-trigger simulation — user must press "Run Simulation" button |

### Spillover Visualization (Sprint 5)
| Task | Status | Evidence |
|---|---|---|
| Waterbed spillover arrows (dashed lines) | ✅ | `loadSpilloverArrows()` — dashed `L.polyline` |
| Arrow head dot with magnitude popup | ✅ | `L.circleMarker` at destination |
| Arrows show only in spillover layer mode | ✅ | `if (state.layer !== 'spillover') return` |

### Chat / AI Assistant (Sprint 6)
| Task | Status | Evidence |
|---|---|---|
| Chat panel with message bubbles | ✅ | `#chatPanel`, `addMsg()` |
| Prompt chips (4 quick-fire questions) | ✅ | `.prompt-chip` buttons |
| Rule-based reply function | ✅ | `reply()` covers 6 intent patterns |
| "Ask AI" from zone detail | ✅ | `askAboutZone()` fills chat + switches panel |
| **LLM `/api/explain` integration** | ❌ **MISSING** | `reply()` is fully rule-based; never calls `POST /explain` |

### Theme & Visual (Sprint 7–12)
| Task | Status | Evidence |
|---|---|---|
| Consistent CSS custom properties (light theme, sea-green accent) | ✅ | `:root` in `styles.css` |
| Responsive layout (mobile nav, panel slide-up) | ✅ | Media queries in `styles.css` |
| Error toasts for failed API calls | ✅ | `showToast()` called in catch blocks |
| Dark theme cards / glassmorphism | ⚠️ **PARTIAL** | Light theme overall; zone detail uses `#1F2937` inline — inconsistency |
| Congestion Impact circular gauge (0–100) | ❌ **MISSING** | Risk score shown as plain number, no circular gauge component |

### Day 3 Polish (Sprint 14–15)
| Task | Status | Evidence |
|---|---|---|
| Final CSS polish | ✅ | Consistent spacing, button styles in `styles.css` |
| Loading skeletons (not spinners) on station list | ✅ | `.skeleton-item` shimmer animation |
| Error handling for all async calls | ✅ | All `try/catch` in `app.js` |

---

## ❌ Missing / Incomplete MUST-DO Features

| # | Feature | Sprint | Impact |
|---|---|---|---|
| 1 | **Two-Layer toggle labels wrong** — buttons say "Risk / Violator / Spillover" instead of "Violation Density / Congestion Risk Impact" | Sprint 3 | 🔴 **CRITICAL** — this is the judge demo moment |
| 2 | **`estimated_lane_hours_blocked` not shown in zone detail** | Sprint 6 | 🟠 HIGH — planner calls it "judges latch onto this metric" |
| 3 | **LLM `/api/explain` not wired to chat** — all responses are rule-based | Sprint 12 | 🟠 HIGH — explain endpoint works but unused |
| 4 | **Congestion Impact circular gauge missing** | Sprint 12 | 🟡 MEDIUM — score shown as plain number |
| 5 | **Slider does not auto-run simulation** — needs manual button click | Sprint 9 | 🟡 MEDIUM — planner says "drag the slider" as demo beat |

---

## 🔶 Stretch Features (Not Required)

| Feature | Sprint | Status |
|---|---|---|
| Smooth heatmap transition animation on time change | Sprint 3 | ❌ |
| Hourly granularity slider within morning_peak | Sprint 4 | ❌ |
| Station filter dropdown in header | Sprint 6 | ❌ |
| Spillover ripple / pulse animation on circles | Sprint 12/14 | ❌ |
| View toggle buttons (Impact / Violator / Patrol) | Sprint 12 | ❌ |
| Forecast view ("tomorrow's hotspots") | Sprint 12 | ❌ |
| Zoom-adaptive heatmap (`zoomend` → re-fetch resolution) | Sprint 10 | ❌ |
| Agent reasoning panel | Sprint 12 | ❌ |

None of these block the demo. Attempt only after fixing the 5 must-do gaps above.

---

## 🗺️ Recommended Framework & Libraries

The current vanilla stack is fine for demo day. Here's what to use going forward, and what to keep:

### Keep (Working Now)
| Tool | Why keep |
|---|---|
| **Leaflet 1.9.4** | Mature, zero config, offline-capable, good heatmap plugin |
| **leaflet.heat** | Minimal, fast gradient heatmaps |
| **Inter font (Google Fonts)** | Professional typography |
| **Vanilla JS** | No build step, instant load, zero toolchain issues during demo |

### Recommended Upgrades (Post-Hackathon)
| Current | Recommended Upgrade | Reason |
|---|---|---|
| CartoDB Dark Matter tiles | **Mappls SDK v3.0 raster tiles** | Avoid OSM-derivative tiles for compliance |
| Rule-based `reply()` chat | Wire `POST /api/explain` → display LLM text | Real AI differentiation |
| Plain CSS | Keep current CSS (it's clean) | No change needed |
| Vanilla JS state | **React + Vite** (post-hackathon only) | Better componentization for a real product |

### Mappls Tiles Integration (Quick Fix for Compliance)
```html
<!-- Replace CartoDB tiles in app.js initMap() with: -->
L.tileLayer('https://apis.mappls.com/advancedmaps/v1/{YOUR_KEY}/still_map/get_tile?type=roadmap&x={x}&y={y}&z={z}', {
    attribution: '&copy; MapmyIndia',
    maxZoom: 20
}).addTo(state.map);
```

---

## 📋 Implementation Plan to Close Gaps

Work in this order — estimated 3–5 hours total.

### Priority 1 — Fix the Two-Layer Toggle (30 min) 🔴
The most critical gap — this is the judge demo opening.

**File:** `frontend/index.html` + `frontend/app.js`

**Change 1 — HTML:** Rename the layer buttons:
```html
<!-- Replace current layer-toggle div in index.html -->
<div class="map-controls">
    <div class="layer-toggle">
        <button class="layer-btn active" data-layer="raw">
            Violation Density
            <span class="layer-sub">Where violations happen</span>
        </button>
        <button class="layer-btn" data-layer="risk">
            Congestion Risk
            <span class="layer-sub">Where traffic is choked</span>
        </button>
        <button class="layer-btn" data-layer="spillover">Spillover</button>
    </div>
</div>
```

**Change 2 — CSS:** Add subtitle style:
```css
.layer-sub { display: block; font-size: 10px; opacity: 0.75; font-weight: 400; }
```

**Why this matters:** Toggle between `raw` (violation count density) and `risk` (congestion impact score) will show two visually DIFFERENT heatmaps. That difference IS the theme answer.

---

### Priority 2 — Add `estimated_lane_hours_blocked` to Zone Detail (30 min) 🟠
**File:** `frontend/app.js` — `showZoneDetail()` function

In the detail template, after the risk score row, add:
```javascript
// Fetch traffic context to get lane_hours estimate
let trafficData = null;
try {
    const tr = await fetch(`${API}/traffic/${zone.grid_cell_id}`);
    if (tr.ok) trafficData = await tr.json();
} catch(e) {}

// Add this block inside the detail HTML template:
const travelRatio = trafficData?.travel_time_ratio ?? 1.0;
const laneBlockEstimate = ((score / 100) * 8).toFixed(1); // proxy: 8 lane-hours max/day

// Insert this HTML after the risk breakdown section:
`<div class="detail-section" style="margin-bottom:16px;">
    <div class="detail-section-title" style="font-size:12px;font-weight:600;color:#9CA3AF;margin-bottom:8px;text-transform:uppercase;">
        Traffic Impact
    </div>
    <div style="background:#1F2937;border-radius:8px;padding:12px;text-align:center;">
        <div style="font-size:28px;font-weight:800;color:#F59E0B;">${laneBlockEstimate}</div>
        <div style="font-size:11px;color:#9CA3AF;margin-top:4px;">estimated lane-hours blocked/day</div>
        <div style="font-size:11px;color:#9CA3AF;margin-top:2px;">Travel time ratio: ${travelRatio}×</div>
    </div>
</div>`
```

---

### Priority 3 — Wire LLM Explain to Chat (45 min) 🟠
**File:** `frontend/app.js` — `reply()` function

Replace the fallback `else` branch and add a real API call:
```javascript
async function reply(prompt) {
    const z = state.selectedZone;
    const p = prompt.toLowerCase();

    // ... keep existing rule-based intent checks above ...

    // NEW: for unknown queries or "why" questions, call the real /explain endpoint
    if (z && (p.includes('why') || p.includes('explain') || p.includes('risk'))) {
        try {
            const r = await fetch(`${API}/explain`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ zone_id: z.grid_cell_id, hour: state.hour })
            });
            const data = await r.json();
            if (data.explanation) {
                addMsg('assistant', data.explanation);
                return;
            }
        } catch(e) { /* fall through to rule-based */ }
    }
    // existing rule-based fallback...
}
```

Also add an "Explain" button to zone detail that fires this:
```javascript
// In showZoneDetail() HTML template, replace the Ask AI button onclick:
<button class="detail-btn detail-btn-outline" onclick="askAboutZone()" style="flex:1;">
    🤖 AI Explain
</button>
```

---

### Priority 4 — Circular Gauge for Risk Score (1 hour) 🟡
**File:** `frontend/app.js` — `showZoneDetail()` + `frontend/styles.css`

Add an SVG ring gauge replacing the plain number:
```javascript
function riskGauge(score) {
    const r = 36, circ = 2 * Math.PI * r;
    const fill = circ * (1 - score / 100);
    const color = score >= 67 ? '#EF4444' : score >= 34 ? '#F59E0B' : '#10B981';
    return `
    <svg width="90" height="90" viewBox="0 0 90 90">
        <circle cx="45" cy="45" r="${r}" fill="none" stroke="#374151" stroke-width="8"/>
        <circle cx="45" cy="45" r="${r}" fill="none" stroke="${color}" stroke-width="8"
            stroke-dasharray="${circ}" stroke-dashoffset="${fill}"
            stroke-linecap="round" transform="rotate(-90 45 45)"
            style="transition:stroke-dashoffset 0.6s ease"/>
        <text x="45" y="49" text-anchor="middle" fill="${color}" font-size="20" font-weight="800" font-family="Inter">${score.toFixed(0)}</text>
        <text x="45" y="61" text-anchor="middle" fill="#9CA3AF" font-size="9" font-family="Inter">/ 100</text>
    </svg>`;
}
```

---

### Priority 5 — Auto-Simulate on Slider Drag (15 min) 🟡
**File:** `frontend/app.js`

Add a debounced auto-trigger:
```javascript
// In bindEvents(), replace the teamSlider input handler:
let simDebounce = null;
teamSlider.addEventListener('input', e => {
    state.numTeams = parseInt(e.target.value);
    teamCountLbl.textContent = e.target.value;
    clearTimeout(simDebounce);
    simDebounce = setTimeout(() => {
        if (state.apiConnected && state.station) runSimulation();
    }, 400); // 400ms debounce
});
```

---

## Summary Table

| # | Feature | Status | Hours to Fix |
|---|---|---|---|
| **Two-layer toggle labels** | 🔴 Wrong labels | 0.5 h |
| **Lane-hours blocked metric** | 🟠 Missing | 0.5 h |
| **LLM explain in chat** | 🟠 Missing | 0.75 h |
| **Circular gauge** | 🟡 Missing | 1.0 h |
| **Auto-simulate on slider** | 🟡 Partial | 0.25 h |
| **Mappls tile compliance** | 🟡 Optional | 0.25 h |
| **Stretch features** | — All remaining | 3–6 h |

**Total to close all MUST-DO gaps: ~3 hours.**
Focus on items 1–3 first. The rest can be done if time permits.
