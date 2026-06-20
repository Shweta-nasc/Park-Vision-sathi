/**
 * ParkVisionSaathi – Patrol Operations Dashboard (Leaflet Edition)
 * Interactive Leaflet Map with Heatmaps, Game-Theory Overlays, Routing, and Patrol Simulation.
 */

const API = ''; // Empty string resolves to same host (http://localhost:8000)

/* ═══ STATE ════════════════════════════════════════════════════════ */
const state = {
    station: null,
    hour: 9,
    layer: 'risk',
    selectedZone: null,
    map: null,
    heatLayer: null,
    markers: [],
    routeLayer: null,
    destMarker: null,
    stations: [],
    priorityAreas: [],
    arrowLayers: [],
    // Simulation state
    numTeams: 6,
    teamMarkers: [],
    apiConnected: false,
    isLoading: false,
};

// ── Team colors for simulation markers ──────────────────────────────────
const TEAM_COLORS = [
    '#2A9D8F', '#E76F51', '#457B9D', '#F4A261', '#9B5DE5',
    '#00F5D4', '#F15BB5', '#FEE440', '#00BBF9', '#8338EC',
    '#FF006E', '#3A86C8', '#38B000', '#70E000', '#CCff00',
];

// ── Time period labels ──────────────────────────────────────────────────
function getTimePeriod(hour) {
    if (hour >= 8 && hour <= 10) return '🔴 Morning Peak';
    if (hour >= 17 && hour <= 19) return '🔴 Evening Peak';
    if (hour >= 6 && hour < 8) return 'Early Morning';
    if (hour >= 11 && hour <= 16) return 'Midday';
    if (hour >= 20 && hour <= 22) return 'Late Evening';
    return 'Night';
}

// ── Initialize App ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    populateHourSelect();
    checkApi();
    loadStations();
    bindEvents();
});

// ── API Health Check ────────────────────────────────────────────────────
async function checkApi() {
    try {
        const r = await fetch(`${API}/health`);
        if (r.ok) {
            state.apiConnected = true;
            setStatus('ok', 'Connected');
            showToast('Connected to ParkVisionSaathi API', 'success');
        } else {
            state.apiConnected = false;
            setStatus('err', 'API error');
        }
    } catch {
        state.apiConnected = false;
        setStatus('err', 'Offline');
        showToast('FastAPI server offline. Run: uvicorn backend.app.main:app --reload', 'error');
    }
}

function setStatus(type, text) {
    const pill = document.getElementById('apiStatusPill');
    if (!pill) return;
    pill.querySelector('.status-dot').className = `status-dot ${type}`;
    pill.querySelector('span:last-child').textContent = text;
}

// ── Toast Notifications ─────────────────────────────────────────────────
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    
    // Inline styling for premium look if stylesheet has no toast classes
    toast.style.position = 'fixed';
    toast.style.bottom = '24px';
    toast.style.right = '24px';
    toast.style.padding = '12px 20px';
    toast.style.borderRadius = '8px';
    toast.style.backgroundColor = type === 'success' ? '#059669' : type === 'error' ? '#DC2626' : '#2563EB';
    toast.style.color = '#FFFFFF';
    toast.style.fontFamily = 'Inter, sans-serif';
    toast.style.fontSize = '13px';
    toast.style.fontWeight = '500';
    toast.style.zIndex = '9999';
    toast.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
    toast.style.transition = 'opacity 0.3s ease';
    
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ── Station Selection Screen ────────────────────────────────────────────
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

    initMap(s.lat, s.lon);
    loadDashboard();
}

// ── Initialize Map (Leaflet) ────────────────────────────────────────────
function initMap(lat, lon) {
    if (state.map) {
        state.map.setView([lat, lon], 14);
        return;
    }

    state.map = L.map('map', {
        center: [lat, lon],
        zoom: 14,
        zoomControl: true,
        attributionControl: true,
    });

    // CartoDB Dark Matter map tiles (free, offline fallback)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 20,
    }).addTo(state.map);

    // Station Base Icon
    const stationIcon = L.divIcon({
        className: '',
        html: `<div style="width:32px; height:32px; background:#2A9D8F; border:3px solid white; border-radius:50%; display:flex; align-items:center; justify-content:center; box-shadow:0 2px 5px rgba(0,0,0,0.5)">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5"><path d="M12 22s-8-4.5-8-11.8A8 8 0 0 1 12 2a8 8 0 0 1 8 8.2c0 7.3-8 11.8-8 11.8z"/><circle cx="12" cy="10" r="3"/></svg>
               </div>`,
        iconSize: [32, 32],
        iconAnchor: [16, 16],
    });

    L.marker([lat, lon], { icon: stationIcon })
        .addTo(state.map)
        .bindPopup(`<div style="font-family:Inter,sans-serif;padding:4px;color:#f3f4f6;"><strong>${state.station.name}</strong><br><span style="color:#9CA3AF;font-size:12px">Jurisdiction Base Station</span></div>`);

    // Map click for generic coordinate detail query
    state.map.on('click', (e) => {
        loadZoneDetailByCoords(e.latlng.lat, e.latlng.lng);
    });
}

// ── Dashboard Loading ───────────────────────────────────────────────────
async function loadDashboard() {
    showLoading(true);
    await Promise.all([
        loadHeatmap(),
        loadPriorityAreas(),
        loadStationSummary()
    ]);
    showLoading(false);
}

function showLoading(v) {
    document.getElementById('mapLoading')?.classList.toggle('hidden', !v);
}

// ── Heatmap Rendering ───────────────────────────────────────────────────
async function loadHeatmap() {
    if (!state.map) return;
    try {
        const r = await fetch(`${API}/heatmap?hour=${state.hour}&type=${state.layer}`);
        const data = await r.json();

        // Clear old heatmap layer and zone markers
        if (state.heatLayer) {
            state.map.removeLayer(state.heatLayer);
            state.heatLayer = null;
        }
        state.markers.forEach(m => state.map.removeLayer(m));
        state.markers = [];

        // Build data for Leaflet heatLayer
        const heatData = data.points.map(p => [
            p.lat,
            p.lon,
            p.intensity / (data.max_intensity || 1)
        ]);

        const gradients = {
            risk:      { 0.0: '#059669', 0.4: '#F59E0B', 0.7: '#F97316', 1.0: '#DC2626' },
            violator:  { 0.0: '#6366F1', 0.4: '#A855F7', 0.7: '#EC4899', 1.0: '#DC2626' },
            spillover: { 0.0: '#06B6D4', 0.4: '#2A9D8F', 0.7: '#F59E0B', 1.0: '#DC2626' },
        };

        if (typeof L.heatLayer === 'function') {
            state.heatLayer = L.heatLayer(heatData, {
                radius: 25,
                blur: 15,
                max: 1.0,
                gradient: gradients[state.layer] || gradients.risk
            }).addTo(state.map);
        } else {
            console.warn('L.heatLayer not loaded. Drawing circle fallbacks.');
            // Circle fallback for points
            const sorted = data.points.sort((a, b) => b.intensity - a.intensity).slice(0, 80);
            sorted.forEach(p => {
                const intensity = p.intensity / (data.max_intensity || 100);
                const color = intensity > 0.7 ? '#DC2626' : intensity > 0.4 ? '#F59E0B' : '#059669';
                const circle = L.circleMarker([p.lat, p.lon], {
                    radius: 8 + intensity * 12,
                    fillColor: color,
                    fillOpacity: 0.3,
                    color: color,
                    weight: 1,
                    opacity: 0.4,
                }).addTo(state.map);
                state.markers.push(circle);
            });
        }

        // Add clickable hotspot zone pins
        await addHotspotMarkers();
        // Load displacement arrows if spillover mode
        await loadSpilloverArrows();
    } catch (e) {
        console.error('Heatmap error:', e);
    }
}

async function addHotspotMarkers() {
    if (!state.map) return;
    try {
        const r = await fetch(`${API}/risk/top_zones?hour=${state.hour}&n=15`);
        const zones = await r.json();

        zones.forEach(z => {
            const color = z.risk_label === 'HIGH' ? '#DC2626' : z.risk_label === 'MEDIUM' ? '#F59E0B' : '#059669';
            const size = z.risk_label === 'HIGH' ? 16 : 12;

            const icon = L.divIcon({
                className: '',
                html: `<div style="width:${size}px; height:${size}px; background:${color}; border:2px solid white; border-radius:50%; box-shadow:0 1px 4px rgba(0,0,0,0.4)"></div>`,
                iconSize: [size, size],
                iconAnchor: [size / 2, size / 2],
            });

            const marker = L.marker([z.grid_lat, z.grid_lon], { icon })
                .addTo(state.map)
                .bindPopup(`
                    <div style="font-family:Inter,sans-serif;padding:8px;min-width:160px;color:#f3f4f6;">
                        <strong style="font-size:13px">${z.grid_cell_id}</strong><br>
                        <span style="color:#9ca3af;font-size:12px">Risk: <strong style="color:${color}">${z.risk_score.toFixed(0)}</strong> (${z.risk_label})</span>
                        <div style="margin-top:8px">
                            <button onclick="window._selectZone('${z.grid_cell_id}')" style="
                                background:#2A9D8F;color:white;border:none;padding:6px 14px;
                                border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;
                                font-family:Inter,sans-serif;width:100%;
                            ">View Details</button>
                        </div>
                    </div>`);

            marker._zoneData = z;
            state.markers.push(marker);
        });

        window._selectZone = (cellId) => {
            const zone = state.markers.find(m => m._zoneData?.grid_cell_id === cellId)?._zoneData;
            if (zone) showZoneDetail(zone);
        };
    } catch (e) {
        console.error('Hotspot markers error:', e);
    }
}

// ── Spillover Animated Arrows ───────────────────────────────────────────
async function loadSpilloverArrows() {
    if (state.arrowLayers) {
        state.arrowLayers.forEach(l => state.map.removeLayer(l));
    }
    state.arrowLayers = [];

    if (state.layer !== 'spillover') return;

    try {
        const r = await fetch(`${API}/game/spillover_arrows`);
        const data = await r.json();
        if (data && data.arrows) {
            const hourArrows = data.arrows.filter(a => a.hour === state.hour);
            hourArrows.forEach(a => {
                const line = L.polyline([[a.from_lat, a.from_lon], [a.to_lat, a.to_lon]], {
                    color: '#F43F5E',
                    weight: 2.5,
                    dashArray: '5, 5',
                    opacity: 0.75
                }).addTo(state.map);

                const head = L.circleMarker([a.to_lat, a.to_lon], {
                    radius: 4,
                    fillColor: '#F43F5E',
                    fillOpacity: 1,
                    color: '#FFFFFF',
                    weight: 1
                }).addTo(state.map).bindPopup(`
                    <div style="font-family:Inter,sans-serif;padding:4px;color:#f3f4f6;">
                        <strong>Waterbed Spillover Arrow</strong><br>
                        <span style="font-size:12px;">Risk Shifted: +${a.magnitude.toFixed(1)} points</span>
                    </div>
                `);

                state.arrowLayers.push(line, head);
            });
        }
    } catch (e) {
        console.error('Arrows load error:', e);
    }
}

// ── Priority Areas cards ────────────────────────────────────────────────
async function loadPriorityAreas() {
    if (!state.station) return;
    try {
        const r = await fetch(`${API}/stations/${encodeURIComponent(state.station.name)}/priority_areas?hour=${state.hour}&limit=12`);
        state.priorityAreas = await r.json();
        renderPriorityCards();
    } catch (e) {
        console.error('Priority load error:', e);
    }
}

function renderPriorityCards() {
    const el = document.getElementById('priorityCards');
    if (!state.priorityAreas.length) {
        el.innerHTML = '<div style="padding:16px;color:#9CA3AF;font-size:12px">No priority areas defined for this shift</div>';
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
                <span class="card-meta-item">👮 ${a.force_needed} units</span>
                <span class="card-meta-item">📍 ${a.distance_km} km</span>
                <span class="card-meta-item">⏱ ${a.eta_minutes}m ETA</span>
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
            routeToZone();
        });
    });
}

function pickArea(idx) {
    const area = state.priorityAreas[idx];
    if (!area) return;
    document.querySelectorAll('.priority-card').forEach(c => c.classList.remove('selected'));
    document.querySelector(`.priority-card[data-idx="${idx}"]`)?.classList.add('selected');
    if (state.map) {
        state.map.setView([area.grid_lat, area.grid_lon], 15);
    }
    showZoneDetail(area);
}

// ── Station Summary Stats ───────────────────────────────────────────────
async function loadStationSummary() {
    if (!state.station) return;
    try {
        const r = await fetch(`${API}/stations/${encodeURIComponent(state.station.name)}/summary?hour=${state.hour}`);
        const d = await r.json();
        document.getElementById('headerZoneCount').textContent = `${d.total_zones} zones`;
        document.getElementById('headerHighCount').textContent = `${d.high_risk_zones} high priority`;
    } catch (e) {
        console.error('Summary stats error:', e);
    }
}

// ── Zone Detail Panel ───────────────────────────────────────────────────
async function showZoneDetail(zone) {
    state.selectedZone = zone;
    activatePanel('details');

    const content = document.getElementById('detailsContent');
    const empty = document.getElementById('detailsEmpty');
    empty.classList.add('hidden');
    content.classList.remove('hidden');
    content.innerHTML = '<div style="padding:40px;text-align:center"><div class="loading-spinner" style="margin:0 auto"></div></div>';

    // Fetch detailed risk details
    let detail = null;
    try {
        const r = await fetch(`${API}/risk/${zone.grid_cell_id}?hour=${state.hour}`);
        if (r.ok) {
            detail = await r.json();
        }
    } catch (err) {
        console.error('Detail fetch error:', err);
    }

    const score = zone.risk_score || detail?.risk_score || 0;
    const label = zone.risk_label || detail?.risk_label || (score >= 67 ? 'HIGH' : score >= 34 ? 'MEDIUM' : 'LOW');
    const jName = zone.top_junction && zone.top_junction !== 'No Junction'
        ? zone.top_junction.replace(/^BTP\d+\s*-\s*/, '') : (detail?.grid_cell_id || zone.grid_cell_id);
    
    // Fallback values
    const densityVal = zone.density ?? detail?.density ?? 0;
    const roadVal = zone.road_importance ?? detail?.road_importance ?? 0;
    const peakVal = zone.peak_weight ?? detail?.peak_weight ?? 1;
    const offenderVal = zone.repeat_offender ?? detail?.repeat_offender ?? 0;
    const heavyVal = zone.heavy_vehicle_ratio ?? detail?.heavy_vehicle_ratio ?? 0;

    const pp = detail?.patrol_probability ?? zone.patrol_probability ?? 0;
    const vr = detail?.violator_risk_score ?? zone.violator_risk_score ?? 0;
    const expCost = detail?.expected_cost ?? 0;
    const fn = zone.force_needed || (score >= 67 ? 3 : score >= 34 ? 2 : 1);

    content.innerHTML = `
        <div class="detail-zone-header" style="display:flex; justify-content:space-between; margin-bottom:16px;">
            <div>
                <div style="font-size:15px;font-weight:700;margin-bottom:2px;color:#f3f4f6;">${jName}</div>
                <div class="detail-zone-id" style="font-size:11px;color:#9CA3AF">${zone.grid_cell_id} · Hour ${state.hour}:00</div>
            </div>
            <span class="detail-risk-badge ${label}" style="padding:4px 8px; border-radius:4px; font-size:11px; font-weight:700; text-transform:uppercase;">${label}</span>
        </div>
        <div class="detail-score-row" style="display:flex; align-items:center; gap:12px; margin-bottom:16px;">
            <span class="detail-score-big" style="font-size:32px; font-weight:800; color:#EF4444">${score.toFixed(0)}</span>
            <div>
                <div class="detail-score-label" style="font-size:11px; color:#9CA3AF">Risk Score</div>
                <div class="detail-score-label" style="font-size:11px; color:#9CA3AF">out of 100</div>
            </div>
        </div>
        <div class="detail-section" style="margin-bottom:16px;">
            <div class="detail-section-title" style="font-size:12px; font-weight:600; color:#9CA3AF; margin-bottom:8px; text-transform:uppercase;">Risk Breakdown</div>
            ${bar('Density', densityVal * 100)}
            ${bar('Road Imp.', roadVal * 100)}
            ${bar('Peak Weight', (peakVal / 1.5) * 100)}
            ${bar('Repeat Offend.', offenderVal * 100)}
            ${bar('Heavy Vehicle', heavyVal * 100)}
        </div>
        <div class="detail-section" style="margin-bottom:16px;">
            <div class="detail-section-title" style="font-size:12px; font-weight:600; color:#9CA3AF; margin-bottom:8px; text-transform:uppercase;">Operations Intel</div>
            <div class="detail-stats" style="display:grid; grid-template-columns: repeat(2, 1fr); gap:8px;">
                <div class="detail-stat" style="background:#1F2937; padding:8px; border-radius:6px; text-align:center;"><div class="detail-stat-value" style="font-weight:700; font-size:16px;">${fn}</div><div class="detail-stat-label" style="font-size:10px; color:#9CA3AF;">Force units</div></div>
                <div class="detail-stat" style="background:#1F2937; padding:8px; border-radius:6px; text-align:center;"><div class="detail-stat-value" style="font-weight:700; font-size:16px;">${zone.violation_count || detail?.violation_count || '—'}</div><div class="detail-stat-label" style="font-size:10px; color:#9CA3AF;">Violations</div></div>
                <div class="detail-stat" style="background:#1F2937; padding:8px; border-radius:6px; text-align:center;"><div class="detail-stat-value" style="font-weight:700; font-size:16px; color:#3B82F6;">${(pp*100).toFixed(1)}%</div><div class="detail-stat-label" style="font-size:10px; color:#9CA3AF;">Patrol prob.</div></div>
                <div class="detail-stat" style="background:#1F2937; padding:8px; border-radius:6px; text-align:center;"><div class="detail-stat-value" style="font-weight:700; font-size:16px; color:#EC4899;">${vr.toFixed(0)}</div><div class="detail-stat-label" style="font-size:10px; color:#9CA3AF;">Violator risk</div></div>
            </div>
        </div>
        ${zone.distance_km ? `<div class="detail-section" style="margin-bottom:16px;"><div class="detail-section-title" style="font-size:12px; font-weight:600; color:#9CA3AF; margin-bottom:4px; text-transform:uppercase;">From Station</div><div style="display:flex;gap:16px;font-size:13px;color:#f3f4f6;"><span>📍 <strong>${zone.distance_km} km</strong></span><span>⏱ <strong>${zone.eta_minutes}m</strong> ETA</span></div></div>` : ''}
        <div class="detail-actions" style="display:flex; gap:8px;">
            <button class="detail-btn detail-btn-primary" onclick="routeToZone()" style="flex:1;">Route now →</button>
            <button class="detail-btn detail-btn-outline" onclick="askAboutZone()" style="flex:1;">Ask AI</button>
        </div>`;

    document.getElementById('rightPanel')?.classList.add('mobile-visible');
}

async function loadZoneDetailByCoords(lat, lon) {
    if (!state.apiConnected) return;
    const cellLat = (Math.floor(lat / 0.005) * 0.005 + 0.0025);
    const cellLon = (Math.floor(lon / 0.005) * 0.005 + 0.0025);
    const cellId = `${Math.floor(lat / 0.005)}_${Math.floor(lon / 0.005)}`;

    // Fake a zone model for layout
    const dummyZone = {
        grid_cell_id: cellId,
        grid_lat: cellLat,
        grid_lon: cellLon,
        risk_score: 0,
        risk_label: 'LOW',
        violation_count: 0,
        density: 0,
        road_importance: 0,
        peak_weight: 1,
        repeat_offender: 0,
        heavy_vehicle_ratio: 0,
    };
    showZoneDetail(dummyZone);
}

function bar(label, pct) {
    pct = Math.max(0, Math.min(100, pct));
    const c = pct >= 70 ? '#EF4444' : pct >= 40 ? '#F59E0B' : '#059669';
    return `
    <div class="detail-bar-row" style="display:flex; align-items:center; margin-bottom:6px; font-size:12px;">
        <span class="detail-bar-label" style="min-width:100px; color:#9CA3AF;">${label}</span>
        <div class="detail-bar-track" style="flex:1; background:#374151; height:6px; border-radius:3px; margin:0 8px; overflow:hidden;">
            <div class="detail-bar-fill" style="width:${pct}%; background:${c}; height:100%"></div>
        </div>
        <span class="detail-bar-value" style="font-family:monospace; min-width:32px; text-align:right;">${pct.toFixed(0)}%</span>
    </div>`;
}

// ── Routing Polyline (Leaflet) ──────────────────────────────────────────
function routeToZone() {
    if (!state.selectedZone || !state.station || !state.map) return;
    const z = state.selectedZone;

    // Clear old route line and marker
    if (state.routeLayer) { state.map.removeLayer(state.routeLayer); state.routeLayer = null; }
    if (state.destMarker) { state.map.removeLayer(state.destMarker); state.destMarker = null; }

    // Draw Leaflet polyline
    state.routeLayer = L.polyline(
        [
            [state.station.lat, state.station.lon],
            [z.grid_lat, z.grid_lon]
        ],
        {
            color: '#2A9D8F',
            weight: 3.5,
            opacity: 0.85,
            dashArray: '8, 6',
        }
    ).addTo(state.map);

    // Destination target marker
    const destIcon = L.divIcon({
        className: '',
        html: `<div style="width:20px; height:20px; background:#DC2626; border:3px solid white; border-radius:50%; box-shadow:0 1px 4px rgba(0,0,0,0.5)"></div>`,
        iconSize: [20, 20],
        iconAnchor: [10, 10],
    });

    state.destMarker = L.marker([z.grid_lat, z.grid_lon], { icon: destIcon })
        .addTo(state.map)
        .bindPopup(`<div style="font-family:Inter,sans-serif;padding:4px;color:#f3f4f6;"><strong>Patrol Destination</strong><br><span style="color:#9CA3AF;font-size:12px">Zone: ${z.grid_cell_id}</span></div>`);

    // Zoom map to cover station and target
    state.map.fitBounds([
        [state.station.lat, state.station.lon],
        [z.grid_lat, z.grid_lon]
    ], { padding: [50, 50] });

    showToast(`Route plotted: ${z.distance_km} km · ETA ${z.eta_minutes} mins`, 'info');
}

// ── Chatbot Assistant ───────────────────────────────────────────────────
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
    
    // Apply styling for chat bubbles
    d.style.padding = '10px 14px';
    d.style.borderRadius = '8px';
    d.style.marginBottom = '8px';
    d.style.maxWidth = '85%';
    d.style.fontSize = '12.5px';
    d.style.lineHeight = '1.4';
    
    if (role === 'user') {
        d.style.backgroundColor = '#2A9D8F';
        d.style.color = '#FFFFFF';
        d.style.alignSelf = 'flex-end';
        d.style.marginLeft = 'auto';
    } else {
        d.style.backgroundColor = '#1F2937';
        d.style.color = '#F3F4F6';
        d.style.alignSelf = 'flex-start';
        d.style.marginRight = 'auto';
        d.style.whiteSpace = 'pre-line';
    }
    
    c.appendChild(d);
    c.scrollTop = c.scrollHeight;
}

function reply(prompt) {
    const z = state.selectedZone;
    const st = state.station;
    const p = prompt.toLowerCase();
    let ans = '';

    if (p.includes('why') && p.includes('risk')) {
        const score = z?.risk_score ?? 0;
        ans = `Zone ${z?.grid_cell_id || 'unselected'} — risk score ${score.toFixed(0)}/100\n\nKey components driving this risk:\n• Violation density: ${((z?.density||0)*100).toFixed(0)}%\n• Repeat offender weight: ${((z?.repeat_offender||0)*100).toFixed(0)}%\n• Heavy commercial vehicles: ${((z?.heavy_vehicle_ratio||0)*100).toFixed(0)}%\n• Peak congestion weight: ${z?.peak_weight||1}x\n\nPatrol recommendation: deploy ${z?.force_needed||2} officers to maintain enforcement coverage.`;
    } else if (p.includes('strategy') || p.includes('patrol')) {
        const hi = state.priorityAreas.filter(a => a.priority === 'High').length;
        const total = state.priorityAreas.reduce((s, a) => s + (a.force_needed || 1), 0);
        ans = `Strategic Patrol Summary for ${st?.name || 'Jurisdiction'} at ${state.hour}:00:\n\n• High-priority hotspots: ${hi}\n• Total required force: ${total} officers\n• Closest hotspot: ${state.priorityAreas[0]?.distance_km || '—'} km away\n\nRecommended: deploy units to the top 3 priority areas to optimize coverage.`;
    } else if (p.includes('summary') || p.includes('priority')) {
        const hi = state.priorityAreas.filter(a => a.priority === 'High').length;
        const md = state.priorityAreas.filter(a => a.priority === 'Medium').length;
        const tv = state.priorityAreas.reduce((s, a) => s + (a.violation_count || 0), 0);
        ans = `Shift Briefing Summary (${state.hour}:00):\n\n• High priority areas: ${hi}\n• Medium priority areas: ${md}\n• Aggregated violations: ${tv.toLocaleString()}\n\nTop focus point: grid cell ${state.priorityAreas[0]?.grid_cell_id || '—'} (risk: ${state.priorityAreas[0]?.risk_score?.toFixed(0) || '—'}).`;
    } else if (p.includes('officer') || p.includes('force') || p.includes('needed')) {
        const total = state.priorityAreas.reduce((s, a) => s + (a.force_needed || 1), 0);
        ans = `Officer requirements for ${st?.name || 'jurisdiction'}:\n\n` +
            state.priorityAreas.slice(0, 5).map(a => `• Grid ${a.grid_cell_id}: ${a.force_needed} units (risk ${a.risk_score?.toFixed(0)})`).join('\n') +
            `\n\nTotal requirement across all zones: ${total} units.`;
    } else if (p.includes('route')) {
        if (z) { 
            routeToZone(); 
            ans = `Route successfully plotted to zone ${z.grid_cell_id}\n\n📍 Distance: ${z.distance_km || '—'} km\n⏱ ETA: ${z.eta_minutes || '—'} min\n🛡 Risk Level: ${z.risk_label || '—'}`; 
        } else { 
            ans = 'Please select a hotspot or priority zone first, then ask to route.'; 
        }
    } else {
        ans = `Hello! I am your Patrol Assistant. I can help you with:\n\n• "Why is this area high risk?"\n• "Suggest patrol strategy"\n• "How many officers are needed?"\n• "Summarize priority areas"\n• "Show route to zone"\n\nSelect any zone to get started!`;
    }
    setTimeout(() => addMsg('assistant', ans), 400);
}

// ── Run Simulation (Greedy Team Deployment) ─────────────────────────────
async function runSimulation() {
    if (!state.apiConnected) {
        showToast('API not connected', 'error');
        return;
    }

    showLoading(true);
    try {
        const r = await fetch(`${API}/simulate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                num_teams: state.numTeams,
                hour: state.hour,
                strategy: 'stackelberg',
            }),
        });
        const data = await r.json();

        if (data) {
            // Clear old simulation markers
            state.teamMarkers.forEach(m => state.map.removeLayer(m));
            state.teamMarkers = [];

            // Deploy team markers on map
            data.assignments.forEach(a => {
                const color = TEAM_COLORS[(a.team_id - 1) % TEAM_COLORS.length];
                const icon = L.divIcon({
                    className: '',
                    html: `<div class="team-marker" style="background:${color}; width:32px; height:32px; border:2px solid white; border-radius:50%; display:flex; align-items:center; justify-content:center; color:white; font-weight:bold; font-size:12px; box-shadow:0 2px 5px rgba(0,0,0,0.4)">${a.team_id}</div>`,
                    iconSize: [32, 32],
                    iconAnchor: [16, 16],
                });

                const marker = L.marker([a.grid_lat, a.grid_lon], { icon })
                    .addTo(state.map)
                    .bindPopup(`
                        <div style="font-family:Inter,sans-serif;padding:8px;color:#f3f4f6;">
                            <strong style="font-size:13px">Team ${a.team_id} Assigned</strong><br>
                            <span style="font-size:12px;">Zone: ${a.grid_cell_id}</span><br>
                            <span style="font-size:12px;">Risk Score: ${a.risk_score.toFixed(0)}</span><br>
                            <span style="font-size:12px;">Patrol Prob: ${(a.patrol_probability * 100).toFixed(1)}%</span><br>
                            <span style="font-size:12px;">Priority Rank: #${a.priority_rank}</span>
                        </div>
                    `);
                state.teamMarkers.push(marker);
            });

            // Draw simulation spillover circles
            if (data.spillover_zones && data.spillover_zones.length > 0) {
                data.spillover_zones.forEach(sz => {
                    const circle = L.circleMarker([sz.grid_lat, sz.grid_lon], {
                        radius: 8,
                        fillColor: sz.risk_change_pct > 0 ? '#EF4444' : '#10B981',
                        fillOpacity: 0.5,
                        color: '#FFFFFF',
                        weight: 1,
                    }).addTo(state.map).bindPopup(`
                        <div style="font-family:Inter,sans-serif;padding:8px;color:#f3f4f6;">
                            <strong>Simulation Spillover</strong><br>
                            <span style="font-size:12px;">Zone: ${sz.grid_cell_id}</span><br>
                            <span style="font-size:12px;">Original Risk: ${sz.original_risk.toFixed(1)}</span><br>
                            <span style="font-size:12px;">Adjusted Risk: ${sz.adjusted_risk.toFixed(1)}</span><br>
                            <span style="font-size:12px;color:${sz.risk_change_pct > 0 ? '#EF4444' : '#10B981'};">Change: ${sz.risk_change_pct > 0 ? '+' : ''}${sz.risk_change_pct.toFixed(1)}%</span>
                        </div>
                    `);
                    state.teamMarkers.push(circle);
                });
            }

            // Update simulation results sidebar panel
            document.getElementById('simResults').classList.remove('hidden');
            document.getElementById('simCoverage').textContent = `${data.coverage_pct}%`;
            document.getElementById('simRiskCovered').textContent = data.total_risk_covered.toFixed(0);
            document.getElementById('simUncovered').textContent = data.uncovered_high_risk.length;

            showToast(`Simulation complete: ${state.numTeams} teams deployed`, 'success');
        }
    } catch (err) {
        console.error('Simulation run error:', err);
        showToast('Error running simulation', 'error');
    }
    showLoading(false);
}

// ── Hour select population ──────────────────────────────────────────────
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

// ── Tab Management ──────────────────────────────────────────────────────
function handleTab(tab) {
    const rp = document.getElementById('rightPanel');
    if (tab === 'assistant') { 
        rp?.classList.add('mobile-visible'); 
        activatePanel('chat'); 
    } else if (tab === 'areas') { 
        document.getElementById('priorityStrip')?.scrollIntoView({ behavior: 'smooth' }); 
    } else if (tab === 'map') { 
        rp?.classList.remove('mobile-visible'); 
    } else if (tab === 'dispatch' && state.selectedZone) { 
        rp?.classList.add('mobile-visible'); 
        activatePanel('details'); 
    }
}

function activatePanel(p) {
    document.querySelectorAll('.panel-tab').forEach(t => t.classList.toggle('active', t.dataset.panel === p));
    document.querySelectorAll('.panel-content').forEach(el => el.classList.remove('active'));
    
    if (p === 'chat') {
        document.getElementById('chatPanel')?.classList.add('active');
    } else if (p === 'sim') {
        document.getElementById('simPanel')?.classList.add('active');
    } else {
        document.getElementById('detailsPanel')?.classList.add('active');
    }
}

function sendChat() {
    const inp = document.getElementById('chatInput');
    const msg = inp.value.trim();
    if (!msg) return;
    inp.value = '';
    addMsg('user', msg);
    reply(msg);
}

// ── Event Bindings ──────────────────────────────────────────────────────
function bindEvents() {
    // Station search input filter
    document.getElementById('stationSearch')?.addEventListener('input', e => {
        const q = e.target.value.toLowerCase();
        renderStationList(state.stations.filter(s => s.name.toLowerCase().includes(q)));
    });

    // Hour select trigger
    document.getElementById('hourSelect')?.addEventListener('change', e => {
        state.hour = +e.target.value;
        if (state.station) loadDashboard();
    });

    // Heatmap layer type toggle
    document.querySelectorAll('.layer-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.layer-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.layer = btn.dataset.layer;
            if (state.map) loadHeatmap();
        });
    });

    // Left nav rail tabs
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

    // Sidebar tab panel switcher
    document.querySelectorAll('.panel-tab').forEach(btn => {
        btn.addEventListener('click', () => activatePanel(btn.dataset.panel));
    });

    // AI chat operations
    document.getElementById('chatSend')?.addEventListener('click', sendChat);
    document.getElementById('chatInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(); });
    document.querySelectorAll('.prompt-chip').forEach(chip => {
        chip.addEventListener('click', () => { addMsg('user', chip.dataset.prompt); reply(chip.dataset.prompt); });
    });

    // Switch police station
    document.getElementById('switchStationBtn')?.addEventListener('click', () => {
        document.getElementById('stationScreen').classList.remove('hidden');
        document.getElementById('appShell').classList.add('hidden');
    });

    // Patrol simulation setup
    const teamSlider = document.getElementById('teamSlider');
    const teamCountLbl = document.getElementById('teamCount');
    if (teamSlider && teamCountLbl) {
        teamSlider.addEventListener('input', e => {
            state.numTeams = parseInt(e.target.value);
            teamCountLbl.textContent = e.target.value;
        });
    }

    document.getElementById('runSimBtn')?.addEventListener('click', runSimulation);
}
