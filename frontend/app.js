/**
 * ParkVisionSaathi – Patrol Operations Dashboard  v5
 * Mappls SDK · Sea-green accent · Map-first · Station-aware
 */

const API = '';

/* ═══ STATE ════════════════════════════════════════════════════════ */
const state = {
    station: null,
    hour: new Date().getHours(),
    layer: 'risk',
    selectedZone: null,
    map: null,
    heatLayer: null,
    markers: [],
    routeLayer: null,
    destMarker: null,
    stations: [],
    priorityAreas: [],
    mapplsReady: false,
};

/* ═══ MAPPLS CALLBACK ═════════════════════════════════════════════ */
/* Called by the SDK script tag's &callback=onMapplsReady */
window.onMapplsReady = function () {
    state.mapplsReady = true;
    console.log('[Mappls] SDK loaded');
    // If a station was already selected before SDK loaded, init map now
    if (state.station && !state.map) {
        initMap(state.station.lat, state.station.lon);
        loadDashboard();
    }
};

/* ═══ INIT ═════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
    populateHourSelect();
    checkApi();
    loadStations();
    bindEvents();
});

/* ── API Health ────────────────────────────────────────────────── */
async function checkApi() {
    try {
        const r = await fetch(`${API}/health`);
        if (r.ok) setStatus('ok', 'Connected');
        else setStatus('err', 'API error');
    } catch { setStatus('err', 'Offline'); }
}

function setStatus(type, text) {
    const pill = document.getElementById('apiStatusPill');
    if (!pill) return;
    pill.querySelector('.status-dot').className = `status-dot ${type}`;
    pill.querySelector('span:last-child').textContent = text;
}

/* ═══ STATION SELECTION ════════════════════════════════════════════ */
async function loadStations() {
    try {
        const r = await fetch(`${API}/stations`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        state.stations = await r.json();
        renderStationList(state.stations);
        const lbl = document.getElementById('stationCountLabel');
        if (lbl) lbl.textContent = `${state.stations.length} stations available`;
    } catch (e) {
        console.error('Station load error:', e);
        document.getElementById('stationList').innerHTML =
            `<div style="padding:32px;text-align:center;color:#9CA3AF">
                <p style="font-size:14px;margin-bottom:8px">Could not load stations</p>
                <p style="font-size:12px">Check that the API is running on port 8000</p>
            </div>`;
    }
}

function renderStationList(list) {
    const el = document.getElementById('stationList');
    if (!list.length) {
        el.innerHTML = '<div style="padding:32px;text-align:center;color:#9CA3AF;font-size:13px">No stations match your search</div>';
        return;
    }
    el.innerHTML = list.map(s => `
        <div class="station-item" data-station='${JSON.stringify(s).replace(/'/g, "&#39;")}'>
            <div class="station-item-left">
                <div class="station-item-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 22s-8-4.5-8-11.8A8 8 0 0 1 12 2a8 8 0 0 1 8 8.2c0 7.3-8 11.8-8 11.8z"/>
                        <circle cx="12" cy="10" r="3"/>
                    </svg>
                </div>
                <div>
                    <div class="station-item-name">${s.name}</div>
                    <div class="station-item-meta">${s.zone_count} zones · ${s.total_violations.toLocaleString()} violations</div>
                </div>
            </div>
            <svg class="station-item-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
        </div>`).join('');

    el.querySelectorAll('.station-item').forEach(row => {
        row.addEventListener('click', () => selectStation(JSON.parse(row.dataset.station)));
    });
}

function selectStation(s) {
    state.station = s;
    document.getElementById('stationScreen').classList.add('hidden');
    document.getElementById('appShell').classList.remove('hidden');
    document.getElementById('currentStationName').textContent = s.name;
    document.getElementById('stripStation').textContent = `Under ${s.name}`;

    if (state.mapplsReady && !state.map) {
        initMap(s.lat, s.lon);
        loadDashboard();
    } else if (state.map) {
        state.map.setCenter([s.lat, s.lon]);
        state.map.setZoom(14);
        loadDashboard();
    }
    // If SDK not loaded yet, onMapplsReady will handle it
}

/* ═══ MAP (Mappls SDK) ════════════════════════════════════════════ */
function initMap(lat, lon) {
    state.map = new mappls.Map('map', {
        center: [lat, lon],
        zoom: 14,
        zoomControl: true,
        search: false,
        location: false,
    });

    state.map.addListener('load', () => {
        // Station marker
        new mappls.Marker({
            map: state.map,
            position: { lat, lng: lon },
            fitbounds: false,
            icon: {
                url: 'data:image/svg+xml,' + encodeURIComponent(
                    `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
                        <circle cx="16" cy="16" r="14" fill="#2A9D8F" stroke="white" stroke-width="3"/>
                        <circle cx="16" cy="14" r="4" fill="white"/>
                    </svg>`
                ),
                size: { width: 32, height: 32 },
                anchor: { x: 16, y: 16 },
            },
            popupHtml: `<div style="font-family:Inter,sans-serif;padding:8px"><strong>${state.station.name}</strong><br><span style="color:#555;font-size:12px">Police Station</span></div>`,
        });
    });
}

/* ═══ DASHBOARD LOADING ═══════════════════════════════════════════ */
async function loadDashboard() {
    showLoading(true);
    await Promise.all([loadHeatmap(), loadPriorityAreas(), loadStationSummary()]);
    showLoading(false);
}

function showLoading(v) {
    document.getElementById('mapLoading')?.classList.toggle('hidden', !v);
}

/* ── Heatmap ────────────────────────────────────────────────────── */
async function loadHeatmap() {
    if (!state.map) return;
    try {
        const r = await fetch(`${API}/heatmap?hour=${state.hour}&type=${state.layer}`);
        const data = await r.json();

        // Remove old heat + markers
        if (state.heatLayer) { state.heatLayer.remove(); state.heatLayer = null; }
        state.markers.forEach(m => m.remove && m.remove());
        state.markers = [];

        // Build data for Mappls HeatmapLayer
        const pts = data.points.map(p => ({ lat: p[0], lng: p[1], weight: p[2] }));

        const gradients = {
            risk:      ['rgba(5,150,105,0)', 'rgba(5,150,105,1)', '#F59E0B', '#F97316', '#DC2626'],
            violator:  ['rgba(99,102,241,0)', 'rgba(99,102,241,1)', '#a855f7', '#ec4899', '#DC2626'],
            spillover: ['rgba(6,182,212,0)', 'rgba(6,182,212,1)', '#2A9D8F', '#F59E0B', '#DC2626'],
        };

        try {
            state.heatLayer = new mappls.HeatmapLayer({
                map: state.map,
                data: pts,
                opacity: 0.7,
                radius: 30,
                gradient: gradients[state.layer] || gradients.risk,
            });
        } catch (hErr) {
            console.warn('HeatmapLayer not available, using circle markers fallback', hErr);
            // Fallback: draw circles for top-intensity points
            const sorted = data.points.sort((a, b) => b[2] - a[2]).slice(0, 80);
            sorted.forEach(p => {
                const intensity = p[2] / (data.max_intensity || 100);
                const color = intensity > 0.7 ? '#DC2626' : intensity > 0.4 ? '#F59E0B' : '#059669';
                const circle = new mappls.Circle({
                    map: state.map,
                    center: { lat: p[0], lng: p[1] },
                    radius: 120 + intensity * 200,
                    fillColor: color,
                    fillOpacity: 0.25 + intensity * 0.3,
                    strokeColor: color,
                    strokeOpacity: 0.4,
                    strokeWeight: 1,
                });
                state.markers.push(circle);
            });
        }

        // Add clickable zone markers
        addHotspotMarkers();
    } catch (e) { console.error('Heatmap error:', e); }
}

async function addHotspotMarkers() {
    if (!state.map) return;
    try {
        const r = await fetch(`${API}/risk/top_zones?hour=${state.hour}&n=15`);
        const zones = await r.json();
        zones.forEach(z => {
            const color = z.risk_label === 'HIGH' ? '#DC2626' : z.risk_label === 'MEDIUM' ? '#F59E0B' : '#059669';
            const size = z.risk_label === 'HIGH' ? 16 : 12;

            const marker = new mappls.Marker({
                map: state.map,
                position: { lat: z.grid_lat, lng: z.grid_lon },
                fitbounds: false,
                icon: {
                    url: 'data:image/svg+xml,' + encodeURIComponent(
                        `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
                            <circle cx="${size/2}" cy="${size/2}" r="${size/2-1}" fill="${color}" stroke="white" stroke-width="2"/>
                        </svg>`
                    ),
                    size: { width: size, height: size },
                    anchor: { x: size / 2, y: size / 2 },
                },
                popupHtml: `<div style="font-family:Inter,sans-serif;padding:8px;min-width:160px">
                    <strong style="font-size:13px">${z.grid_cell_id}</strong><br>
                    <span style="color:#555;font-size:12px">Risk: <strong style="color:${color}">${z.risk_score.toFixed(0)}</strong> (${z.risk_label})</span>
                    <div style="margin-top:8px">
                        <button onclick="window._selectZone('${z.grid_cell_id}')" style="
                            background:#2A9D8F;color:white;border:none;padding:6px 14px;
                            border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;
                            font-family:Inter,sans-serif;width:100%;
                        ">View Details</button>
                    </div>
                </div>`,
            });

            // Store zone data for click handler
            marker._zoneData = z;
            state.markers.push(marker);
        });

        // Global click handler for popup buttons
        window._selectZone = (cellId) => {
            const zone = state.markers.find(m => m._zoneData?.grid_cell_id === cellId)?._zoneData;
            if (zone) showZoneDetail(zone);
        };
    } catch (e) { console.error('Markers error:', e); }
}

/* ── Priority Areas ─────────────────────────────────────────────── */
async function loadPriorityAreas() {
    if (!state.station) return;
    try {
        const r = await fetch(`${API}/stations/${encodeURIComponent(state.station.name)}/priority_areas?hour=${state.hour}&limit=12`);
        state.priorityAreas = await r.json();
        renderPriorityCards();
    } catch (e) { console.error('Priority error:', e); }
}

function renderPriorityCards() {
    const el = document.getElementById('priorityCards');
    if (!state.priorityAreas.length) {
        el.innerHTML = '<div style="padding:16px;color:#9CA3AF;font-size:12px">No areas for this hour</div>';
        return;
    }
    el.innerHTML = state.priorityAreas.map((a, i) => {
        const cls = a.priority === 'High' ? 'high' : a.priority === 'Medium' ? 'medium' : 'low';
        const name = a.top_junction && a.top_junction !== 'No Junction'
            ? a.top_junction.replace(/^BTP\d+\s*-\s*/, '') : a.grid_cell_id;
        return `
        <div class="priority-card" data-idx="${i}">
            <div class="card-top">
                <span class="card-area-name" title="${name}">${name}</span>
                <span class="priority-badge ${cls}">${a.priority}</span>
            </div>
            <div class="card-meta">
                <span class="card-meta-item">👮 ${a.force_needed}</span>
                <span class="card-meta-item">📍 ${a.distance_km}km</span>
                <span class="card-meta-item">⏱ ${a.eta_minutes}m</span>
            </div>
            <div class="card-actions">
                <button class="card-route-btn" data-idx="${i}">Route now →</button>
            </div>
        </div>`;
    }).join('');

    el.querySelectorAll('.priority-card').forEach(card => {
        card.addEventListener('click', e => {
            if (e.target.classList.contains('card-route-btn')) return;
            pickArea(+card.dataset.idx);
        });
    });
    el.querySelectorAll('.card-route-btn').forEach(btn => {
        btn.addEventListener('click', e => {
            e.stopPropagation();
            const idx = +btn.dataset.idx;
            pickArea(idx);
            const a = state.priorityAreas[idx];
            if (a && state.map) { state.map.setCenter([a.grid_lat, a.grid_lon]); state.map.setZoom(16); }
        });
    });
}

function pickArea(idx) {
    const area = state.priorityAreas[idx];
    if (!area) return;
    document.querySelectorAll('.priority-card').forEach(c => c.classList.remove('selected'));
    document.querySelector(`.priority-card[data-idx="${idx}"]`)?.classList.add('selected');
    if (state.map) { state.map.setCenter([area.grid_lat, area.grid_lon]); state.map.setZoom(15); }
    showZoneDetail(area);
}

/* ── Station Summary ─────────────────────────────────────────────── */
async function loadStationSummary() {
    if (!state.station) return;
    try {
        const r = await fetch(`${API}/stations/${encodeURIComponent(state.station.name)}/summary?hour=${state.hour}`);
        const d = await r.json();
        document.getElementById('headerZoneCount').textContent = `${d.total_zones} zones`;
        document.getElementById('headerHighCount').textContent = `${d.high_risk_zones} high priority`;
    } catch (e) { console.error('Summary error:', e); }
}

/* ═══ ZONE DETAIL PANEL ═══════════════════════════════════════════ */
async function showZoneDetail(zone) {
    state.selectedZone = zone;
    activatePanel('details');

    const content = document.getElementById('detailsContent');
    const empty = document.getElementById('detailsEmpty');
    empty.classList.add('hidden');
    content.classList.remove('hidden');
    content.innerHTML = '<div style="padding:40px;text-align:center"><div class="loading-spinner" style="margin:0 auto"></div></div>';

    // Fetch game theory data
    let stack = null, viol = null;
    try {
        const [sR, vR] = await Promise.all([
            fetch(`${API}/game/stackelberg_strategy?hour=${state.hour}&zone_id=${zone.grid_cell_id}`),
            fetch(`${API}/game/violator_adaptation?hour=${state.hour}&zone_id=${zone.grid_cell_id}`),
        ]);
        const sD = await sR.json(); const vD = await vR.json();
        stack = Array.isArray(sD) ? sD[0] : sD;
        viol = Array.isArray(vD) ? vD[0] : vD;
    } catch {}

    const score = zone.risk_score || 0;
    const label = zone.risk_label || (score >= 67 ? 'HIGH' : score >= 34 ? 'MEDIUM' : 'LOW');
    const jName = zone.top_junction && zone.top_junction !== 'No Junction'
        ? zone.top_junction.replace(/^BTP\d+\s*-\s*/, '') : zone.grid_cell_id;
    const pp = stack?.patrol_probability ?? zone.patrol_probability ?? 0;
    const vr = viol?.violator_risk_score ?? zone.violator_risk_score ?? 0;
    const fn = zone.force_needed || (score >= 67 ? 3 : score >= 34 ? 2 : 1);

    content.innerHTML = `
        <div class="detail-zone-header">
            <div>
                <div style="font-size:15px;font-weight:700;margin-bottom:2px">${jName}</div>
                <div class="detail-zone-id">${zone.grid_cell_id} · Hour ${state.hour}:00</div>
            </div>
            <span class="detail-risk-badge ${label}">${label}</span>
        </div>
        <div class="detail-score-row">
            <span class="detail-score-big ${score>=67?'text-danger':score>=34?'text-warning':'text-success'}">${score.toFixed(0)}</span>
            <div>
                <div class="detail-score-label">Risk Score</div>
                <div class="detail-score-label">out of 100</div>
            </div>
        </div>
        <div class="detail-section">
            <div class="detail-section-title">Risk Breakdown</div>
            ${bar('Density', (zone.density||0)*100)}
            ${bar('Road Imp.', (zone.road_importance||0)*100)}
            ${bar('Peak Weight', ((zone.peak_weight||1)/1.5)*100)}
            ${bar('Repeat Offend.', (zone.repeat_offender||0)*100)}
            ${bar('Heavy Vehicle', (zone.heavy_vehicle_ratio||0)*100)}
        </div>
        <div class="detail-section">
            <div class="detail-section-title">Operations Intel</div>
            <div class="detail-stats">
                <div class="detail-stat"><div class="detail-stat-value">${fn}</div><div class="detail-stat-label">Units needed</div></div>
                <div class="detail-stat"><div class="detail-stat-value">${zone.violation_count || '—'}</div><div class="detail-stat-label">Violations</div></div>
                <div class="detail-stat"><div class="detail-stat-value">${(pp*100).toFixed(1)}%</div><div class="detail-stat-label">Patrol prob.</div></div>
                <div class="detail-stat"><div class="detail-stat-value">${vr.toFixed(0)}</div><div class="detail-stat-label">Violator risk</div></div>
            </div>
        </div>
        ${zone.distance_km ? `<div class="detail-section"><div class="detail-section-title">From Station</div><div style="display:flex;gap:16px;font-size:13px"><span>📍 <strong>${zone.distance_km} km</strong></span><span>⏱ <strong>${zone.eta_minutes}m</strong> ETA</span></div></div>` : ''}
        <div class="detail-actions">
            <button class="detail-btn detail-btn-primary" onclick="routeToZone()">Route now →</button>
            <button class="detail-btn detail-btn-outline" onclick="askAboutZone()">Ask AI</button>
        </div>`;

    document.querySelector('.right-panel')?.classList.add('mobile-visible');
}

function bar(label, pct) {
    pct = Math.max(0, Math.min(100, pct));
    const c = pct >= 70 ? 'var(--danger)' : pct >= 40 ? 'var(--warning)' : 'var(--accent)';
    return `<div class="detail-bar-row"><span class="detail-bar-label">${label}</span><div class="detail-bar-track"><div class="detail-bar-fill" style="width:${pct}%;background:${c}"></div></div><span class="detail-bar-value">${pct.toFixed(0)}%</span></div>`;
}

/* ═══ ROUTING (Mappls Polyline) ═══════════════════════════════════ */
function routeToZone() {
    if (!state.selectedZone || !state.station || !state.map) return;
    const z = state.selectedZone;

    // Clear old route
    if (state.routeLayer) { state.routeLayer.remove(); state.routeLayer = null; }
    if (state.destMarker) { state.destMarker.remove(); state.destMarker = null; }

    // Draw polyline from station to zone
    state.routeLayer = new mappls.Polyline({
        map: state.map,
        path: [
            { lat: state.station.lat, lng: state.station.lon },
            { lat: z.grid_lat, lng: z.grid_lon },
        ],
        strokeColor: '#2A9D8F',
        strokeWeight: 3,
        strokeOpacity: 0.8,
        dashArray: [8, 6],
    });

    // Destination marker
    state.destMarker = new mappls.Marker({
        map: state.map,
        position: { lat: z.grid_lat, lng: z.grid_lon },
        fitbounds: false,
        icon: {
            url: 'data:image/svg+xml,' + encodeURIComponent(
                `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22"><circle cx="11" cy="11" r="9" fill="#DC2626" stroke="white" stroke-width="3"/></svg>`
            ),
            size: { width: 22, height: 22 },
            anchor: { x: 11, y: 11 },
        },
    });

    // Fit bounds
    state.map.fitBounds([
        [state.station.lat, state.station.lon],
        [z.grid_lat, z.grid_lon],
    ], { padding: 60 });
}

/* ═══ CHAT ASSISTANT ══════════════════════════════════════════════ */
function askAboutZone() {
    if (!state.selectedZone) return;
    activatePanel('chat');
    const p = `Why is zone ${state.selectedZone.grid_cell_id} high risk at hour ${state.hour}?`;
    addMsg('user', p);
    reply(p);
}

function addMsg(role, text) {
    const c = document.getElementById('chatMessages');
    const d = document.createElement('div');
    d.className = `chat-msg ${role}`;
    d.textContent = text;
    c.appendChild(d);
    c.scrollTop = c.scrollHeight;
}

function reply(prompt) {
    const z = state.selectedZone;
    const st = state.station;
    const p = prompt.toLowerCase();
    let ans = '';

    if (p.includes('why') && p.includes('risk')) {
        ans = `Zone ${z?.grid_cell_id || '—'} — risk score ${(z?.risk_score||0).toFixed(0)}/100\n\nKey factors:\n• Violation density: ${((z?.density||0)*100).toFixed(0)}%\n• Repeat offenders: ${((z?.repeat_offender||0)*100).toFixed(0)}%\n• Heavy vehicles: ${((z?.heavy_vehicle_ratio||0)*100).toFixed(0)}%\n• Peak weight: ${z?.peak_weight||1}x\n\nDeploy ${z?.force_needed||2} units recommended.`;
    } else if (p.includes('strategy') || p.includes('patrol')) {
        const hi = state.priorityAreas.filter(a => a.priority === 'High').length;
        const total = state.priorityAreas.reduce((s, a) => s + (a.force_needed || 1), 0);
        ans = `${st?.name || 'Station'} at ${state.hour}:00\n\n• ${hi} high-priority zones\n• Total force: ${total} units\n• Closest high-risk: ${state.priorityAreas[0]?.distance_km || '—'} km\n\nPrioritize top 3 areas for maximum coverage.`;
    } else if (p.includes('summary') || p.includes('priority')) {
        const hi = state.priorityAreas.filter(a => a.priority === 'High').length;
        const md = state.priorityAreas.filter(a => a.priority === 'Medium').length;
        const tv = state.priorityAreas.reduce((s, a) => s + (a.violation_count || 0), 0);
        ans = `${st?.name || 'Station'} summary at ${state.hour}:00\n\n• ${hi} high-priority areas\n• ${md} medium-priority areas\n• ${tv.toLocaleString()} total violations\n\nTop: ${state.priorityAreas[0]?.grid_cell_id || '—'} (risk ${state.priorityAreas[0]?.risk_score?.toFixed(0) || '—'})`;
    } else if (p.includes('officer') || p.includes('force') || p.includes('needed')) {
        const total = state.priorityAreas.reduce((s, a) => s + (a.force_needed || 1), 0);
        ans = `Force for ${st?.name || 'station'}:\n\n` +
            state.priorityAreas.slice(0, 5).map(a => `• ${a.grid_cell_id}: ${a.force_needed} units (risk ${a.risk_score?.toFixed(0)})`).join('\n') +
            `\n\nTotal: ${total} units across ${state.priorityAreas.length} areas.`;
    } else if (p.includes('route')) {
        if (z) { routeToZone(); ans = `Route plotted to ${z.grid_cell_id}\n\n📍 ${z.distance_km || '—'} km · ⏱ ${z.eta_minutes || '—'} min · Risk: ${z.risk_label || '—'}`; }
        else { ans = 'Select a zone first, then ask to route.'; }
    } else {
        ans = `I can help with:\n\n• "Why is this area high risk?"\n• "Suggest patrol strategy"\n• "How many officers needed?"\n• "Summarize priority areas"\n• "Show route to zone"\n\nSelect a zone for contextual answers.`;
    }
    setTimeout(() => addMsg('assistant', ans), 400);
}

/* ═══ EVENT BINDINGS ══════════════════════════════════════════════ */
function bindEvents() {
    // Station search
    document.getElementById('stationSearch')?.addEventListener('input', e => {
        const q = e.target.value.toLowerCase();
        renderStationList(state.stations.filter(s => s.name.toLowerCase().includes(q)));
    });

    // Hour
    document.getElementById('hourSelect')?.addEventListener('change', e => {
        state.hour = +e.target.value;
        if (state.station) loadDashboard();
    });

    // Layer toggle
    document.querySelectorAll('.layer-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.layer-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.layer = btn.dataset.layer;
            if (state.map) loadHeatmap();
        });
    });

    // Nav rail tabs
    document.querySelectorAll('.nav-item[data-tab]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.nav-item[data-tab]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            handleTab(btn.dataset.tab);
        });
    });

    // Mobile tabs
    document.querySelectorAll('.mobile-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.mobile-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            handleTab(btn.dataset.tab);
        });
    });

    // Panel tabs
    document.querySelectorAll('.panel-tab').forEach(btn => {
        btn.addEventListener('click', () => activatePanel(btn.dataset.panel));
    });

    // Chat
    document.getElementById('chatSend')?.addEventListener('click', sendChat);
    document.getElementById('chatInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(); });
    document.querySelectorAll('.prompt-chip').forEach(chip => {
        chip.addEventListener('click', () => { addMsg('user', chip.dataset.prompt); reply(chip.dataset.prompt); });
    });

    // Switch station
    document.getElementById('switchStationBtn')?.addEventListener('click', () => {
        document.getElementById('stationScreen').classList.remove('hidden');
        document.getElementById('appShell').classList.add('hidden');
    });
}

function handleTab(tab) {
    const rp = document.querySelector('.right-panel');
    if (tab === 'assistant') { rp?.classList.add('mobile-visible'); activatePanel('chat'); }
    else if (tab === 'areas') { document.getElementById('priorityStrip')?.scrollIntoView({ behavior: 'smooth' }); }
    else if (tab === 'map') { rp?.classList.remove('mobile-visible'); }
    else if (tab === 'dispatch' && state.selectedZone) { rp?.classList.add('mobile-visible'); activatePanel('details'); }
}

function activatePanel(p) {
    document.querySelectorAll('.panel-tab').forEach(t => t.classList.toggle('active', t.dataset.panel === p));
    document.querySelectorAll('.panel-content').forEach(el => el.classList.remove('active'));
    document.getElementById(p === 'chat' ? 'chatPanel' : 'detailsPanel')?.classList.add('active');
}

function sendChat() {
    const inp = document.getElementById('chatInput');
    const msg = inp.value.trim();
    if (!msg) return;
    inp.value = '';
    addMsg('user', msg);
    reply(msg);
}

function populateHourSelect() {
    const sel = document.getElementById('hourSelect');
    if (!sel) return;
    for (let h = 0; h < 24; h++) {
        const opt = document.createElement('option');
        opt.value = h;
        const lbl = h === 0 ? '12 AM' : h < 12 ? `${h} AM` : h === 12 ? '12 PM' : `${h - 12} PM`;
        const peak = (h >= 8 && h <= 10) || (h >= 17 && h <= 19);
        opt.textContent = peak ? `${lbl} ●` : lbl;
        if (h === state.hour) opt.selected = true;
        sel.appendChild(opt);
    }
}
