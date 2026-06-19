/**
 * ParkVisionSaathi – Dashboard Application
 * Interactive map with heatmaps, game-theory overlays, and patrol simulation.
 */

const API_BASE = 'http://localhost:8000';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
    currentHour: 9,
    currentView: 'risk',
    map: null,
    heatLayer: null,
    teamMarkers: [],
    patrolCircles: [],
    isLoading: false,
    apiConnected: false,
};

// ── Team colors for simulation markers ──────────────────────────────────
const TEAM_COLORS = [
    '#3b82f6', '#f43f5e', '#10b981', '#f59e0b', '#8b5cf6',
    '#06b6d4', '#ec4899', '#14b8a6', '#f97316', '#6366f1',
    '#84cc16', '#e11d48', '#0ea5e9', '#a855f7', '#22c55e',
];

// ── Time period labels ──────────────────────────────────────────────────
function getTimePeriod(hour) {
    if (hour >= 8 && hour <= 10) return '🔴 Morning Peak';
    if (hour >= 17 && hour <= 19) return '🔴 Evening Peak';
    if (hour >= 6 && hour < 8) return '🟡 Early Morning';
    if (hour >= 11 && hour <= 16) return '🟢 Midday';
    if (hour >= 20 && hour <= 22) return '🟡 Late Evening';
    return '🔵 Night';
}

// ── Initialize Map ──────────────────────────────────────────────────────
function initMap() {
    state.map = L.map('map', {
        center: [12.97, 77.59],
        zoom: 12,
        zoomControl: true,
        attributionControl: true,
    });

    // OPTION A: CartoDB Dark Matter map tiles (free, fallback)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 20,
    }).addTo(state.map);

    // OPTION B: MapmyIndia (Mappls) tiles (uncomment and replace key once allocated)
    /*
    L.tileLayer('https://apis.mapmyindia.com/advancedmaps/v1/YOUR_MAPMYINDIA_API_KEY/maptiles/v2/default/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.mapmyindia.com/">MapmyIndia</a> | ParkVisionSaathi',
        maxZoom: 19,
    }).addTo(state.map);
    */

    // Initialize empty heat layer
    state.heatLayer = L.heatLayer([], {
        radius: 25,
        blur: 15,
        maxZoom: 15,
        max: 100,
        gradient: {
            0.0: '#10b981',
            0.3: '#22d3ee',
            0.5: '#f59e0b',
            0.7: '#f97316',
            0.9: '#f43f5e',
            1.0: '#dc2626',
        },
    }).addTo(state.map);
}

// ── Toast Notification ──────────────────────────────────────────────────
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// ── API Fetch Helper ────────────────────────────────────────────────────
async function apiFetch(endpoint, options = {}) {
    try {
        const resp = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers: { 'Content-Type': 'application/json', ...options.headers },
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (err) {
        console.error(`API error (${endpoint}):`, err);
        return null;
    }
}

// ── Show/Hide Loading ───────────────────────────────────────────────────
function setLoading(loading) {
    state.isLoading = loading;
    document.getElementById('loadingOverlay').classList.toggle('hidden', !loading);
}

// ── Check API Connection ────────────────────────────────────────────────
async function checkApiConnection() {
    const statusEl = document.getElementById('apiStatus');
    const dot = statusEl.querySelector('.status-dot');
    const text = statusEl.querySelector('span:last-child');

    const data = await apiFetch('/health');
    if (data) {
        state.apiConnected = true;
        dot.className = 'status-dot connected';
        text.textContent = 'API Connected';
        showToast('Connected to ParkVisionSaathi API', 'success');
        return true;
    } else {
        dot.className = 'status-dot error';
        text.textContent = 'API Offline';
        showToast('API not reachable. Start: uvicorn backend.app.main:app --reload', 'error');
        return false;
    }
}

// ── Load Heatmap Data ───────────────────────────────────────────────────
async function loadHeatmap() {
    if (!state.apiConnected) return;
    setLoading(true);

    const data = await apiFetch(`/heatmap?hour=${state.currentHour}&type=${state.currentView}`);
    if (data && data.points) {
        const heatData = data.points.map(p => [
            p.lat, p.lon, p.intensity / (data.max_intensity || 1),
        ]);
        state.heatLayer.setLatLngs(heatData);

        // Update legend
        const legendTitle = document.getElementById('legendTitle');
        const titles = {
            risk: 'Risk Score',
            violator: 'Violator Risk',
            spillover: 'Spillover Risk',
            raw: 'Violation Count',
        };
        legendTitle.textContent = titles[state.currentView] || 'Intensity';
    }

    setLoading(false);
}

// ── Load Risk Summary Stats ─────────────────────────────────────────────
async function loadRiskSummary() {
    if (!state.apiConnected) return;

    const type = state.currentView === 'spillover' ? 'spillover' : 'risk';
    const data = await apiFetch(`/risk/summary?hour=${state.currentHour}&type=${type}`);
    if (data) {
        let high = 0, med = 0, low = 0, total = 0;
        data.forEach(row => {
            if (row.risk_label === 'HIGH') high = row.zone_count;
            else if (row.risk_label === 'MEDIUM') med = row.zone_count;
            else if (row.risk_label === 'LOW') low = row.zone_count;
            total += row.total_violations || 0;
        });
        document.getElementById('highRiskCount').textContent = high;
        document.getElementById('medRiskCount').textContent = med;
        document.getElementById('lowRiskCount').textContent = low;
        document.getElementById('totalViolations').textContent = total.toLocaleString();
    }
}

// ── Load Game Theory Summary ────────────────────────────────────────────
async function loadGameSummary() {
    if (!state.apiConnected) return;

    const data = await apiFetch(`/game/summary?hour=${state.currentHour}`);
    const container = document.getElementById('gameSummary');

    if (data && data.stackelberg) {
        const s = data.stackelberg;
        const v = data.violator_adaptation;
        container.innerHTML = `
            <div class="game-stat">
                <span class="game-stat-label">Active Zones</span>
                <span class="game-stat-value">${s.zones || '—'}</span>
            </div>
            <div class="game-stat">
                <span class="game-stat-label">Max Patrol Prob.</span>
                <span class="game-stat-value">${s.max_patrol_prob ? (s.max_patrol_prob * 100).toFixed(1) + '%' : '—'}</span>
            </div>
            <div class="game-stat">
                <span class="game-stat-label">Avg Violator Risk</span>
                <span class="game-stat-value">${v.avg_violator_risk || '—'}</span>
            </div>
            <div class="game-stat">
                <span class="game-stat-label">Avg Expected Cost</span>
                <span class="game-stat-value">₹${v.avg_expected_cost || '—'}</span>
            </div>
            ${data.spillover_by_type ? data.spillover_by_type.map(sp => `
                <div class="game-stat">
                    <span class="game-stat-label">${sp.spillover_type}</span>
                    <span class="game-stat-value">${sp.avg_risk_change_pct > 0 ? '+' : ''}${sp.avg_risk_change_pct}%</span>
                </div>
            `).join('') : ''}
        `;
    } else {
        container.innerHTML = '<p class="muted">Game theory data not available for this hour</p>';
    }
}

// ── Load Patrol Overlay ─────────────────────────────────────────────────
async function loadPatrolOverlay() {
    // Clear existing circles
    state.patrolCircles.forEach(c => state.map.removeLayer(c));
    state.patrolCircles = [];

    if (!state.apiConnected) return;

    const data = await apiFetch(`/heatmap/patrol_overlay?hour=${state.currentHour}`);
    if (data && data.patrols) {
        data.patrols.slice(0, 30).forEach(p => {
            const radius = Math.max(100, p.probability * 15000);
            const circle = L.circle([p.lat, p.lon], {
                radius: radius,
                color: 'rgba(59, 130, 246, 0.4)',
                fillColor: 'rgba(59, 130, 246, 0.08)',
                fillOpacity: 0.6,
                weight: 1,
            }).addTo(state.map);

            circle.bindPopup(`
                <div class="popup-title">Patrol Zone</div>
                <div class="popup-row"><span class="popup-label">Probability</span><span class="popup-value">${(p.probability * 100).toFixed(1)}%</span></div>
                <div class="popup-row"><span class="popup-label">Risk Score</span><span class="popup-value">${p.risk_score?.toFixed(1) || '—'}</span></div>
            `);

            state.patrolCircles.push(circle);
        });
    }
}

// ── Run Simulation ──────────────────────────────────────────────────────
async function runSimulation() {
    if (!state.apiConnected) {
        showToast('API not connected', 'error');
        return;
    }

    const numTeams = parseInt(document.getElementById('teamSlider').value);
    setLoading(true);

    const data = await apiFetch('/simulate', {
        method: 'POST',
        body: JSON.stringify({
            num_teams: numTeams,
            hour: state.currentHour,
            strategy: 'stackelberg',
        }),
    });

    if (data) {
        // Clear old markers
        state.teamMarkers.forEach(m => state.map.removeLayer(m));
        state.teamMarkers = [];

        // Add team markers
        data.assignments.forEach(a => {
            const color = TEAM_COLORS[(a.team_id - 1) % TEAM_COLORS.length];
            const icon = L.divIcon({
                className: '',
                html: `<div class="team-marker" style="background:${color}">${a.team_id}</div>`,
                iconSize: [32, 32],
                iconAnchor: [16, 16],
            });

            const marker = L.marker([a.grid_lat, a.grid_lon], { icon })
                .addTo(state.map)
                .bindPopup(`
                    <div class="popup-title">Team ${a.team_id}</div>
                    <div class="popup-row"><span class="popup-label">Zone</span><span class="popup-value">${a.grid_cell_id}</span></div>
                    <div class="popup-row"><span class="popup-label">Risk Score</span><span class="popup-value">${a.risk_score.toFixed(1)}</span></div>
                    <div class="popup-row"><span class="popup-label">Patrol Prob.</span><span class="popup-value">${(a.patrol_probability * 100).toFixed(1)}%</span></div>
                    <div class="popup-row"><span class="popup-label">Priority</span><span class="popup-value">#${a.priority_rank}</span></div>
                `);

            state.teamMarkers.push(marker);
        });

        // Update results panel
        document.getElementById('simResults').classList.remove('hidden');
        document.getElementById('simCoverage').textContent = `${data.coverage_pct}%`;
        document.getElementById('simRiskCovered').textContent = data.total_risk_covered.toFixed(0);
        document.getElementById('simUncovered').textContent = data.uncovered_high_risk.length;

        await Promise.all([
            loadHeatmap(),
            loadRiskSummary()
        ]);

        showToast(`Simulation complete: ${numTeams} teams deployed`, 'success');
    }

    setLoading(false);
}

// ── Load Zone Detail on Map Click ───────────────────────────────────────
async function loadZoneDetail(lat, lon) {
    if (!state.apiConnected) return;

    // Find nearest grid cell
    const gridLat = (Math.floor(lat / 0.005) * 0.005 + 0.0025).toFixed(4);
    const gridLon = (Math.floor(lon / 0.005) * 0.005 + 0.0025).toFixed(4);
    const cellId = `${Math.floor(lat / 0.005)}_${Math.floor(lon / 0.005)}`;

    const riskData = await apiFetch(`/risk?hour=${state.currentHour}&zone_id=${cellId}`);
    const stackData = await apiFetch(`/game/stackelberg_strategy?hour=${state.currentHour}&zone_id=${cellId}`);
    const violData = await apiFetch(`/game/violator_adaptation?hour=${state.currentHour}&zone_id=${cellId}`);

    const panel = document.getElementById('zoneDetailPanel');
    const content = document.getElementById('zoneDetailContent');

    if (riskData && riskData.length > 0) {
        const r = riskData[0];
        const s = stackData?.[0] || {};
        const v = violData?.[0] || {};

        content.innerHTML = `
            <div class="zone-header">
                <span style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted)">${r.grid_cell_id}</span>
                <span class="zone-risk-badge ${r.risk_label}">${r.risk_label} – ${r.risk_score.toFixed(0)}</span>
            </div>
            <div class="zone-components">
                ${makeComponentBar('Violation Density', r.density)}
                ${makeComponentBar('Road Importance', r.road_importance)}
                ${makeComponentBar('Peak Weight', r.peak_weight / 1.5)}
                ${makeComponentBar('Repeat Offenders', r.repeat_offender)}
                ${makeComponentBar('Validation Trust', r.validation_trust)}
                ${makeComponentBar('Heavy Vehicle Ratio', r.heavy_vehicle_ratio)}
                <div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border)">
                    <div class="zone-component">
                        <span style="color:var(--text-secondary)">Patrol Prob.</span>
                        <span style="font-family:var(--font-mono);color:var(--accent-blue);font-weight:600">${s.patrol_probability ? (s.patrol_probability * 100).toFixed(2) + '%' : '—'}</span>
                    </div>
                    <div class="zone-component">
                        <span style="color:var(--text-secondary)">Expected Cost</span>
                        <span style="font-family:var(--font-mono);color:var(--accent-amber);font-weight:600">₹${v.expected_cost?.toFixed(0) || '—'}</span>
                    </div>
                    <div class="zone-component">
                        <span style="color:var(--text-secondary)">Violator Risk</span>
                        <span style="font-family:var(--font-mono);color:var(--accent-rose);font-weight:600">${v.violator_risk_score?.toFixed(1) || '—'}</span>
                    </div>
                </div>
            </div>
        `;
        panel.classList.remove('hidden');
    } else {
        content.innerHTML = '<p class="muted">No data available for this zone at this hour</p>';
        panel.classList.remove('hidden');
    }
}

function makeComponentBar(label, value) {
    const pct = Math.min(100, Math.max(0, (value || 0) * 100));
    return `
        <div class="zone-component">
            <span style="color:var(--text-secondary);min-width:110px;font-size:11px">${label}</span>
            <div class="component-bar"><div class="component-fill" style="width:${pct}%"></div></div>
            <span style="font-family:var(--font-mono);font-size:11px;color:var(--text-primary);min-width:35px;text-align:right">${pct.toFixed(0)}%</span>
        </div>
    `;
}

// ── Update Everything for Current Hour ──────────────────────────────────
async function updateForHour() {
    document.getElementById('currentTimeLabel').textContent =
        `${String(state.currentHour).padStart(2, '0')}:00`;
    document.getElementById('timePeriod').textContent = getTimePeriod(state.currentHour);

    await Promise.all([
        loadHeatmap(),
        loadRiskSummary(),
        loadGameSummary(),
        loadPatrolOverlay(),
    ]);
}

// ── Event Listeners ─────────────────────────────────────────────────────
function setupEventListeners() {
    // Time slider
    const timeSlider = document.getElementById('timeSlider');
    let debounceTimer;
    timeSlider.addEventListener('input', (e) => {
        state.currentHour = parseInt(e.target.value);
        document.getElementById('currentTimeLabel').textContent =
            `${String(state.currentHour).padStart(2, '0')}:00`;
        document.getElementById('timePeriod').textContent = getTimePeriod(state.currentHour);

        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => updateForHour(), 200);
    });

    // View toggles
    document.querySelectorAll('.view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.currentView = btn.dataset.view;
            loadHeatmap();
            loadRiskSummary();
        });
    });

    // Team slider
    document.getElementById('teamSlider').addEventListener('input', (e) => {
        document.getElementById('teamCount').textContent = e.target.value;
    });

    // Run simulation
    document.getElementById('runSimBtn').addEventListener('click', runSimulation);

    // Close zone detail
    document.getElementById('closeZoneDetail').addEventListener('click', () => {
        document.getElementById('zoneDetailPanel').classList.add('hidden');
    });

    // Map click for zone detail
    state.map.on('click', (e) => {
        loadZoneDetail(e.latlng.lat, e.latlng.lng);
    });
}

// ── Initialization ──────────────────────────────────────────────────────
async function init() {
    initMap();
    setupEventListeners();

    const connected = await checkApiConnection();
    if (connected) {
        await updateForHour();
    }
}

// Start
document.addEventListener('DOMContentLoaded', init);
