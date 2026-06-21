import React, { useState, useEffect, useRef } from 'react';

// --- CONSTANTS ---
const BUCKETS = [
  { label: 'Night 00–06', start: 0, end: 6, dimFrom: 4 },
  { label: 'Morning 06–10', start: 6, end: 10, dimFrom: 10 },
  { label: 'Midday 10–14', start: 10, end: 14, dimFrom: 14 },
  { label: 'Afternoon 14–16', start: 14, end: 16, dimFrom: 15 }
];

const DENSITY = [
  0.08, 0.24, 0.42, 0.58, 0.72, 0.84, 0.95, 1.0, 0.97, 0.91, 0.81, 0.68,
  0.54, 0.38, 0.18, 0.06, 0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01
];

export default function ParkVisionSaathi() {
  // --- STATE ---
  const [activeTab, setActiveTab] = useState('police'); // 'police' | 'ctrl'
  const [selectedHotspot, setSelectedHotspot] = useState(0);
  const [teamCount, setTeamCount] = useState(5);
  const [currentBucketIdx, setCurrentBucketIdx] = useState(1);
  const [currentHour, setCurrentHour] = useState(9);
  const [isDragging, setIsDragging] = useState(false);

  // --- REFS ---
  const railRef = useRef(null);

  const currentBucket = BUCKETS[currentBucketIdx];
  const bucketHours = [];
  for (let h = currentBucket.start; h < currentBucket.end; h++) {
    bucketHours.push(h);
  }

  // --- COMPUTED VALUES ---
  const congestionPct = Math.min(100, Math.round(40 + teamCount * 9.5));
  
  const hourToPercent = (hour) => {
    const range = currentBucket.end - currentBucket.start;
    return Math.max(0, Math.min(1, (hour - currentBucket.start) / range));
  };

  const percentToHour = (pct) => {
    const range = currentBucket.end - currentBucket.start;
    return Math.round(currentBucket.start + pct * range);
  };

  const currentPct = hourToPercent(currentHour);
  const handleLeftPx = railRef.current ? Math.round(currentPct * railRef.current.offsetWidth) : 0;

  // --- HANDLERS & LOGIC ---
  const handleBucketChange = (idx) => {
    setCurrentBucketIdx(idx);
    setCurrentHour(BUCKETS[idx].start);
  };

  const updateHourFromEvent = (e) => {
    if (!railRef.current) return;
    const rect = railRef.current.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const calculatedHour = percentToHour(pct);
    setCurrentHour(Math.max(currentBucket.start, Math.min(currentBucket.end - 1, calculatedHour)));
  };

  // Drag listeners
  useEffect(() => {
    const handleMouseMove = (e) => {
      if (isDragging) updateHourFromEvent(e);
    };
    const handleMouseUp = () => setIsDragging(false);

    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
      window.addEventListener('touchmove', handleMouseMove);
      window.addEventListener('touchend', handleMouseUp);
    }

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      window.removeEventListener('touchmove', handleMouseMove);
      window.removeEventListener('touchend', handleMouseUp);
    };
  }, [isDragging, currentBucketIdx]);

  return (
    <>
      {/* Embedded UI Styles */}
      <style>{`
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        :root { --font: system-ui, -apple-system, sans-serif; }
        .pv-container { font-family: var(--font); background: #F5F6FA; color: #1A1D23; font-size: 14px; line-height: 1.5; min-height: 100vh; }
        .tab-bar { display: flex; align-items: center; gap: 0; background: #fff; border-bottom: 1px solid #E2E5EC; padding: 0 20px; height: 48px; position: sticky; top: 0; z-index: 100; }
        .tab-bar-brand { display: flex; align-items: center; gap: 8px; margin-right: 24px; }
        .brand-dot { width: 28px; height: 28px; border-radius: 8px; background: #1A56DB; display: flex; align-items: center; justify-content: center; }
        .brand-dot svg { width: 16px; height: 16px; fill: #fff; }
        .brand-name { font-size: 14px; font-weight: 600; color: #1A1D23; letter-spacing: -0.3px; }
        .brand-sub { font-size: 11px; color: #6B7280; letter-spacing: 0.5px; text-transform: uppercase; }
        .tab-btn { height: 48px; padding: 0 16px; border: none; background: transparent; cursor: pointer; font-size: 13px; font-weight: 500; color: #6B7280; border-bottom: 2px solid transparent; transition: color 0.15s, border-color 0.15s; white-space: nowrap; }
        .tab-btn.active { color: #1A56DB; border-bottom-color: #1A56DB; }
        .tab-btn:hover:not(.active) { color: #374151; }
        .tab-spacer { flex: 1; }
        .chip { display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 500; border: 1px solid; }
        .chip-blue { background: #EFF6FF; color: #1D4ED8; border-color: #BFDBFE; }
        .chip-green { background: #F0FDF4; color: #15803D; border-color: #BBF7D0; }
        .chip-amber { background: #FFFBEB; color: #92400E; border-color: #FDE68A; }
        .chip-red { background: #FEF2F2; color: #991B1B; border-color: #FECACA; }
        .chip-dot { width: 7px; height: 7px; border-radius: 50%; }
        .chip-dot-green { background: #22C55E; }
        .chip-dot-amber { background: #F59E0B; }
        .chip-dot-red { background: #EF4444; }
        .chip-dot-blue { background: #3B82F6; }
        .police-shell { display: flex; flex-direction: column; height: calc(100vh - 48px); overflow: hidden; }
        .police-topbar { background: #fff; border-bottom: 1px solid #E2E5EC; padding: 9px 16px; display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
        .topbar-title { font-size: 14px; font-weight: 600; color: #1A1D23; flex: 1; }
        .police-body { display: grid; grid-template-columns: 288px 1fr; flex: 1; overflow: hidden; }
        .police-left { background: #fff; border-right: 1px solid #E2E5EC; overflow-y: auto; padding: 12px; flex-shrink: 0; }
        .map-col { display: flex; flex-direction: column; overflow: hidden; }
        .map-area { background: #E8ECF2; position: relative; overflow: hidden; flex: 1; }
        .map-bg { position: absolute; inset: 0; background: #ECF0F6; }
        .map-road-h { position: absolute; background: #fff; height: 3px; opacity: 0.7; }
        .map-road-v { position: absolute; background: #fff; width: 3px; opacity: 0.7; }
        .map-major-h { position: absolute; background: #D1D9E6; height: 7px; opacity: 0.9; }
        .map-major-v { position: absolute; background: #D1D9E6; width: 7px; opacity: 0.9; }
        .heat-cell { position: absolute; border-radius: 4px; opacity: 0.35; }
        .map-marker { position: absolute; width: 32px; height: 32px; transform: translate(-50%, -100%); display: flex; flex-direction: column; align-items: center; }
        .marker-icon { width: 32px; height: 32px; border-radius: 50% 50% 50% 0; transform: rotate(-45deg); display: flex; align-items: center; justify-content: center; border: 2px solid #fff; box-shadow: 0 2px 6px rgba(0,0,0,0.2); }
        .marker-icon svg { transform: rotate(45deg); }
        .marker-red { background: #EF4444; }
        .marker-amber { background: #F59E0B; }
        .marker-green { background: #22C55E; }
        .marker-blue { background: #3B82F6; }
        .map-controls { position: absolute; right: 12px; top: 12px; display: flex; flex-direction: column; gap: 4px; }
        .map-btn { width: 32px; height: 32px; background: #fff; border: 1px solid #E2E5EC; border-radius: 6px; display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 16px; color: #374151; font-weight: 500; }
        .map-legend { position: absolute; right: 12px; bottom: 12px; background: #fff; border: 1px solid #E2E5EC; border-radius: 8px; padding: 10px 12px; font-size: 11px; }
        .map-legend-title { font-weight: 600; margin-bottom: 6px; color: #374151; }
        .legend-row { display: flex; align-items: center; gap: 6px; margin-bottom: 3px; color: #6B7280; }
        .legend-box { width: 14px; height: 10px; border-radius: 2px; }
        .time-scrubber { background: #fff; border-top: 1px solid #E2E5EC; padding: 14px 20px 12px; flex-shrink: 0; user-select: none; }
        .scrubber-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
        .scrubber-title { font-size: 12px; font-weight: 600; color: #374151; }
        .scrubber-time-display { font-size: 18px; font-weight: 700; color: #1A56DB; letter-spacing: -0.5px; min-width: 72px; text-align: right; }
        .scrubber-buckets { display: flex; gap: 6px; }
        .scrubber-bucket { padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 500; cursor: pointer; border: 1px solid #E2E5EC; color: #6B7280; background: #F9FAFB; transition: background 0.12s, color 0.12s, border-color 0.12s; }
        .scrubber-bucket.active { background: #EFF6FF; color: #1D4ED8; border-color: #BFDBFE; }
        .scrubber-track-wrap { position: relative; height: 44px; margin-top: 2px; }
        .scrubber-ticks { display: flex; justify-content: space-between; padding: 0 0px; margin-bottom: 4px; }
        .scrubber-tick { display: flex; flex-direction: column; align-items: center; gap: 2px; font-size: 10px; color: #9CA3AF; min-width: 28px; text-align: center; position: relative; }
        .scrubber-tick-mark { width: 1px; height: 8px; background: #E2E5EC; }
        .scrubber-tick.major .scrubber-tick-mark { height: 12px; background: #D1D5DB; }
        .scrubber-tick.major { color: #6B7280; font-weight: 500; }
        .scrubber-tick.dim { color: #D1D5DB; }
        .scrubber-tick.dim .scrubber-tick-mark { background: #E9EAEC; }
        .scrubber-rail { position: relative; height: 6px; background: #F3F4F6; border-radius: 3px; cursor: pointer; }
        .scrubber-fill { position: absolute; left: 0; top: 0; height: 100%; background: #1A56DB; border-radius: 3px; pointer-events: none; }
        .scrubber-dim-zone { position: absolute; top: 0; height: 100%; background: repeating-linear-gradient(90deg,#F3F4F6 0px,#F3F4F6 4px,#E9EAEC 4px,#E9EAEC 8px); border-radius: 0 3px 3px 0; pointer-events: none; opacity: 0.7; }
        .scrubber-handle { position: absolute; top: 50%; width: 18px; height: 18px; background: #1A56DB; border-radius: 50%; border: 3px solid #fff; box-shadow: 0 0 0 1.5px #1A56DB, 0 2px 6px rgba(26,86,219,0.35); cursor: grab; transform: translate(-50%, -50%); z-index: 3; transition: box-shadow 0.12s; }
        .scrubber-handle:active { cursor: grabbing; box-shadow: 0 0 0 3px rgba(26,86,219,0.2), 0 2px 8px rgba(26,86,219,0.4); }
        .scrubber-tooltip { position: absolute; top: -32px; transform: translateX(-50%); background: #1A56DB; color: #fff; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; white-space: nowrap; pointer-events: none; z-index: 4; }
        .scrubber-tooltip::after { content: ''; position: absolute; bottom: -4px; left: 50%; transform: translateX(-50%); width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 4px solid #1A56DB; }
        .scrubber-data-bar { display: flex; gap: 2px; height: 16px; margin-bottom: 4px; border-radius: 2px; overflow: hidden; }
        .sdb-seg { flex-shrink: 0; height: 100%; border-radius: 1px; }
        .panel-section { margin-bottom: 14px; }
        .panel-section-title { font-size: 11px; font-weight: 600; color: #9CA3AF; letter-spacing: 0.6px; text-transform: uppercase; margin-bottom: 8px; }
        .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
        .stat-card { background: #F9FAFB; border-radius: 8px; padding: 10px; border: 1px solid #F3F4F6; }
        .stat-value { font-size: 20px; font-weight: 600; line-height: 1; }
        .stat-label { font-size: 11px; color: #6B7280; margin-top: 3px; }
        .stat-delta { font-size: 11px; font-weight: 500; margin-top: 2px; }
        .delta-up { color: #EF4444; }
        .delta-dn { color: #22C55E; }
        .hotspot-list { display: flex; flex-direction: column; gap: 5px; }
        .hotspot-item { display: flex; align-items: center; gap: 8px; background: #F9FAFB; border-radius: 8px; padding: 8px 10px; border: 1px solid #F3F4F6; cursor: pointer; transition: border-color 0.15s; }
        .hotspot-item.selected { border-color: #BFDBFE; background: #EFF6FF; }
        .hotspot-item:hover:not(.selected) { border-color: #E5E7EB; }
        .hotspot-rank { width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; flex-shrink: 0; }
        .rank-1 { background: #FEE2E2; color: #991B1B; }
        .rank-2 { background: #FEF3C7; color: #92400E; }
        .rank-3 { background: #FEF3C7; color: #B45309; }
        .rank-n { background: #F3F4F6; color: #6B7280; }
        .hotspot-info { flex: 1; min-width: 0; }
        .hotspot-name { font-size: 12px; font-weight: 600; color: #1A1D23; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .hotspot-sub { font-size: 11px; color: #6B7280; }
        .risk-badge { font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 4px; flex-shrink: 0; }
        .risk-high { background: #FEE2E2; color: #991B1B; }
        .risk-med { background: #FEF3C7; color: #92400E; }
        .risk-low { background: #F0FDF4; color: #15803D; }
        .team-slider-wrap { background: #EFF6FF; border-radius: 8px; padding: 12px; border: 1px solid #BFDBFE; }
        .team-slider-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .team-slider-title { font-size: 12px; font-weight: 600; color: #1E40AF; }
        .team-count-badge { font-size: 18px; font-weight: 700; color: #1A56DB; background: #fff; border: 1px solid #BFDBFE; border-radius: 6px; padding: 1px 8px; min-width: 36px; text-align: center; }
        .sim-bar { margin-top: 8px; }
        .sim-bar-label { display: flex; justify-content: space-between; font-size: 11px; color: #6B7280; margin-bottom: 4px; }
        .sim-track { height: 8px; background: #BFDBFE; border-radius: 4px; overflow: hidden; }
        .sim-fill { height: 100%; background: #1A56DB; border-radius: 4px; transition: width 0.2s; }
        .sim-info { font-size: 11px; color: #1E40AF; margin-top: 5px; text-align: center; font-weight: 500; }
        input[type=range] { cursor: pointer; width: 100%; accent-color: #1A56DB; }
        .ctrl-layout { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; background: #F5F6FA; min-height: calc(100vh - 48px); }
        .ctrl-topbar { display: flex; align-items: center; gap: 10px; }
        .ctrl-title { font-size: 16px; font-weight: 700; color: #1A1D23; }
        .ctrl-sub { font-size: 12px; color: #6B7280; }
        .ctrl-spacer { flex: 1; }
        .live-badge { display: flex; align-items: center; gap: 6px; background: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 20px; padding: 4px 10px; font-size: 12px; font-weight: 600; color: #15803D; }
        .live-dot { width: 8px; height: 8px; border-radius: 50%; background: #22C55E; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        .ctrl-row { display: grid; gap: 12px; }
        .ctrl-row-3 { grid-template-columns: repeat(3, 1fr); }
        .card { background: #fff; border-radius: 10px; border: 1px solid #E2E5EC; padding: 14px 16px; }
        .card-title { font-size: 11px; font-weight: 600; color: #9CA3AF; letter-spacing: 0.5px; text-transform: uppercase; margin-bottom: 10px; }
        .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
        .kpi-card { background: #fff; border-radius: 10px; border: 1px solid #E2E5EC; padding: 14px 16px; }
        .kpi-icon-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
        .kpi-icon { width: 36px; height: 36px; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
        .kpi-icon-blue { background: #EFF6FF; color: #1D4ED8; }
        .kpi-icon-red { background: #FEF2F2; color: #DC2626; }
        .kpi-icon-amber { background: #FFFBEB; color: #D97706; }
        .kpi-icon-green { background: #F0FDF4; color: #15803D; }
        .kpi-icon svg { width: 18px; height: 18px; }
        .kpi-trend { font-size: 11px; font-weight: 600; padding: 2px 6px; border-radius: 4px; }
        .trend-up { background: #FEE2E2; color: #DC2626; }
        .trend-dn { background: #F0FDF4; color: #15803D; }
        .kpi-value { font-size: 26px; font-weight: 700; color: #1A1D23; line-height: 1; }
        .kpi-label { font-size: 12px; color: #6B7280; margin-top: 3px; }
        .ctrl-map { background: #E8ECF2; border-radius: 10px; border: 1px solid #E2E5EC; position: relative; overflow: hidden; min-height: 280px; }
        .ctrl-map-title { position: absolute; top: 12px; left: 12px; background: #fff; border-radius: 6px; padding: 6px 10px; font-size: 12px; font-weight: 600; color: #1A1D23; border: 1px solid #E2E5EC; z-index:2; }
        .toggle-group { position: absolute; top: 12px; right: 12px; background: #fff; border-radius: 6px; border: 1px solid #E2E5EC; display: flex; overflow: hidden; z-index:2; }
        .toggle-opt { padding: 5px 10px; font-size: 11px; font-weight: 500; cursor: pointer; color: #6B7280; }
        .toggle-opt.on { background: #EFF6FF; color: #1D4ED8; }
        .station-table { width: 100%; border-collapse: collapse; }
        .station-table th { font-size: 10px; font-weight: 600; color: #9CA3AF; text-transform: uppercase; letter-spacing: 0.4px; padding: 4px 8px; text-align: left; border-bottom: 1px solid #E2E5EC; }
        .station-table td { font-size: 12px; padding: 6px 8px; border-bottom: 1px solid #F3F4F6; color: #374151; }
        .station-table tr:last-child td { border-bottom: none; }
        .st-name { font-weight: 600; color: #1A1D23; }
        .risk-pill { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 20px; border-radius: 4px; font-size: 10px; font-weight: 700; }
        .risk-pill-red { background: #FEE2E2; color: #991B1B; }
        .risk-pill-amber { background: #FEF3C7; color: #92400E; }
        .risk-pill-green { background: #F0FDF4; color: #15803D; }
        .forecast-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
        .forecast-day { font-size: 11px; font-weight: 600; color: #374151; min-width: 28px; }
        .forecast-track { flex: 1; height: 8px; background: #F3F4F6; border-radius: 4px; overflow: hidden; }
        .forecast-fill { height: 100%; border-radius: 4px; }
        .forecast-num { font-size: 11px; font-weight: 600; color: #374151; min-width: 36px; text-align: right; }
        .waterbed-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; margin-top: 6px; }
        .wb-cell { aspect-ratio: 1; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; cursor: pointer; }
        .wb-enforced { background: #DCFCE7; color: #15803D; border: 2px solid #22C55E; }
        .wb-spill-high { background: #FEF9C3; color: #92400E; }
        .wb-spill-med { background: #FEF9C3; color: #B45309; opacity: 0.7; }
        .wb-normal { background: #EFF6FF; color: #1E40AF; }
        .wb-neutral { background: #F3F4F6; color: #9CA3AF; }
        .alert-feed { display: flex; flex-direction: column; gap: 6px; }
        .alert-item { display: flex; align-items: flex-start; gap: 8px; padding: 8px 10px; border-radius: 7px; border: 1px solid; }
        .alert-crit { background: #FEF2F2; border-color: #FECACA; }
        .alert-warn { background: #FFFBEB; border-color: #FDE68A; }
        .alert-info { background: #EFF6FF; border-color: #BFDBFE; }
        .alert-icon { width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }
        .alert-icon-red { background: #FEE2E2; }
        .alert-icon-amber { background: #FEF3C7; }
        .alert-icon-blue { background: #DBEAFE; }
        .alert-icon svg { width: 10px; height: 10px; }
        .alert-msg { font-size: 12px; color: #374151; line-height: 1.4; }
        .alert-time { font-size: 10px; color: #9CA3AF; margin-top: 2px; }
        .patrol-zone-list { display: flex; flex-direction: column; gap: 6px; }
        .pz-item { display: flex; align-items: center; gap: 8px; padding: 7px 10px; background: #F9FAFB; border-radius: 7px; border: 1px solid #F3F4F6; }
        .pz-team { width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; flex-shrink: 0; color: #fff; }
        .pz-team-1 { background: #1A56DB; }
        .pz-team-2 { background: #7C3AED; }
        .pz-team-3 { background: #0891B2; }
        .pz-team-4 { background: #15803D; }
        .pz-team-5 { background: #B45309; }
        .pz-info { flex: 1; }
        .pz-zone { font-size: 12px; font-weight: 600; color: #1A1D23; }
        .pz-sub { font-size: 10px; color: #6B7280; }
        .pz-prob { font-size: 12px; font-weight: 700; color: #1A1D23; }
        .divider { height: 1px; background: #F3F4F6; margin: 8px 0; }
        .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); border: 0; }
      `}</style>

      <div className="pv-container">
        {/* TAB BAR */}
        <div className="tab-bar">
          <div className="tab-bar-brand">
            <div className="brand-dot">
              <svg viewBox="0 0 16 16">
                <circle cx="8" cy="8" r="3"/>
                <circle cx="8" cy="3" r="1.5"/>
                <circle cx="8" cy="13" r="1.5"/>
                <circle cx="3" cy="8" r="1.5"/>
                <circle cx="13" cy="8" r="1.5"/>
              </svg>
            </div>
            <div>
              <div className="brand-name">ParkVision-Saathi</div>
              <div className="brand-sub">AI Enforcement Platform</div>
            </div>
          </div>
          <button 
            className={`tab-btn ${activeTab === 'police' ? 'active' : ''}`} 
            onClick={() => setActiveTab('police')}
          >
            Field Officer View
          </button>
          <button 
            className={`tab-btn ${activeTab === 'ctrl' ? 'active' : ''}`} 
            onClick={() => setActiveTab('ctrl')}
          >
            Control Room
          </button>
          <div className="tab-spacer"></div>
          <span className="chip chip-green"><span className="chip-dot chip-dot-green"></span>Bengaluru Active</span>
          <span style={{ marginLeft: '8px', fontSize: '12px', color: '#6B7280' }}>Thursday, 10:45 AM</span>
        </div>

        {/* FIELD OFFICER VIEW */}
        {activeTab === 'police' && (
          <div id="view-police">
            <div className="police-shell">
              <div className="police-topbar">
                <span className="topbar-title">Bengaluru Parking Enforcement — Morning Peak</span>
                <span className="chip chip-red"><span className="chip-dot chip-dot-red"></span>24 Critical Zones</span>
                <span className="chip chip-amber"><span className="chip-dot chip-dot-amber"></span>Morning Peak Active</span>
                <span className="chip chip-blue"><span className="chip-dot chip-dot-blue"></span>5 Teams Deployed</span>
                <span className="chip chip-green"><span className="chip-dot chip-dot-green"></span>Traffic Layer On</span>
              </div>

              <div className="police-body">
                {/* LEFT PANEL */}
                <div className="police-left">
                  <div className="panel-section">
                    <div className="panel-section-title">Zone Summary</div>
                    <div className="stat-grid">
                      <div className="stat-card">
                        <div className="stat-value" style={{ color: '#DC2626' }}>298K</div>
                        <div className="stat-label">Total violations</div>
                        <div className="stat-delta delta-up">↑ 12% vs last week</div>
                      </div>
                      <div className="stat-card">
                        <div className="stat-value" style={{ color: '#D97706' }}>169</div>
                        <div className="stat-label">Named junctions</div>
                        <div className="stat-delta" style={{ color: '#6B7280' }}>Monitored</div>
                      </div>
                      <div className="stat-card">
                        <div className="stat-value" style={{ color: '#1A56DB' }}>54</div>
                        <div className="stat-label">Police stations</div>
                        <div className="stat-delta delta-dn">3 offline</div>
                      </div>
                      <div className="stat-card">
                        <div className="stat-value" style={{ color: '#15803D' }}>66.6%</div>
                        <div className="stat-label">Approval rate</div>
                        <div className="stat-delta" style={{ color: '#6B7280' }}>validated</div>
                      </div>
                    </div>
                  </div>

                  <div className="panel-section">
                    <div className="panel-section-title">Top Hotspots — <span>{currentHour < 10 ? `0${currentHour}` : currentHour}:00</span></div>
                    <div className="hotspot-list">
                      {[
                        { name: 'Upparpet / Elite Jct', sub: '5,838 records · Main road', risk: 87, rankCls: 'rank-1' },
                        { name: 'Shivajinagar Market', sub: '3,402 records · Double park', risk: 79, rankCls: 'rank-2' },
                        { name: 'Majestic Bus Terminal', sub: '2,981 records · Near bus stop', risk: 74, rankCls: 'rank-3' },
                        { name: 'Indiranagar 100ft Rd', sub: '2,114 records · Wrong parking', risk: 61, rankCls: 'rank-n', isMed: true },
                        { name: 'Koramangala 5th Block', sub: '1,856 records · No parking zone', risk: 55, rankCls: 'rank-n', isMed: true },
                        { name: 'Silk Board Flyover', sub: '1,423 records · Heavy vehicles', risk: 48, rankCls: 'rank-n', isMed: true }
                      ].map((item, idx) => (
                        <div 
                          key={idx} 
                          className={`hotspot-item ${selectedHotspot === idx ? 'selected' : ''}`} 
                          onClick={() => setSelectedHotspot(idx)}
                        >
                          <div className={`hotspot-rank ${item.rankCls}`}>{idx + 1}</div>
                          <div className="hotspot-info">
                            <div className="hotspot-name">{item.name}</div>
                            <div className="hotspot-sub">{item.sub}</div>
                          </div>
                          <span className={`risk-badge ${item.isMed ? 'risk-med' : 'risk-high'}`}>{item.risk}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="panel-section">
                    <div className="panel-section-title">Patrol Simulation</div>
                    <div className="team-slider-wrap">
                      <div className="team-slider-header">
                        <span className="team-slider-title">Teams deployed</span>
                        <span className="team-count-badge">{teamCount}</span>
                      </div>
                      <input 
                        type="range" 
                        min="1" 
                        max="12" 
                        value={teamCount} 
                        step="1" 
                        onChange={(e) => setTeamCount(parseInt(e.target.value))}
                      />
                      <div className="sim-bar">
                        <div className="sim-bar-label"><span>Congestion coverage</span><span>{congestionPct}%</span></div>
                        <div className="sim-track"><div className="sim-fill" style={{ width: `${congestionPct}%` }}></div></div>
                      </div>
                      <div className="sim-info">{teamCount} teams → {congestionPct}% congestion impact covered</div>
                    </div>
                  </div>
                </div>

                {/* MAP COLUMN */}
                <div className="map-col">
                  <div className="map-area">
                    <div className="map-bg"></div>
                    <div className="map-major-h" style={{ top: '35%', left: 0, right: 0 }}></div>
                    <div className="map-major-h" style={{ top: '60%', left: 0, right: 0 }}></div>
                    <div className="map-major-v" style={{ left: '30%', top: 0, bottom: 0 }}></div>
                    <div className="map-major-v" style={{ left: '65%', top: 0, bottom: 0 }}></div>
                    <div className="map-road-h" style={{ top: '20%', left: 0, right: 0 }}></div>
                    <div className="map-road-h" style={{ top: '48%', left: 0, right: 0 }}></div>
                    <div className="map-road-h" style={{ top: '75%', left: 0, right: 0 }}></div>
                    <div className="map-road-v" style={{ left: '15%', top: 0, bottom: 0 }}></div>
                    <div className="map-road-v" style={{ left: '45%', top: 0, bottom: 0 }}></div>
                    <div className="map-road-v" style={{ left: '80%', top: 0, bottom: 0 }}></div>
                    
                    <div className="heat-cell" style={{ width: '80px', height: '70px', top: '28%', left: '27%', background: '#DC2626' }}></div>
                    <div className="heat-cell" style={{ width: '60px', height: '55px', top: '53%', left: '42%', background: '#F59E0B' }}></div>
                    <div className="heat-cell" style={{ width: '70px', height: '60px', top: '15%', left: '62%', background: '#EF4444' }}></div>
                    <div className="heat-cell" style={{ width: '50px', height: '45px', top: '64%', left: '20%', background: '#F97316' }}></div>
                    <div className="heat-cell" style={{ width: '45px', height: '40px', top: '40%', left: '73%', background: '#FCD34D' }}></div>
                    <div className="heat-cell" style={{ width: '40px', height: '35px', top: '70%', left: '60%', background: '#FDE68A', opacity: .3 }}></div>
                    
                    <div className="map-marker" style={{ top: '35%', left: '30%' }}><div className="marker-icon marker-red"><svg width="12" height="12" viewBox="0 0 12 12" fill="white"><circle cx="6" cy="5" r="3"/></svg></div></div>
                    <div className="map-marker" style={{ top: '22%', left: '65%' }}><div className="marker-icon marker-red"><svg width="12" height="12" viewBox="0 0 12 12" fill="white"><circle cx="6" cy="5" r="3"/></svg></div></div>
                    <div className="map-marker" style={{ top: '60%', left: '45%' }}><div className="marker-icon marker-amber"><svg width="12" height="12" viewBox="0 0 12 12" fill="white"><circle cx="6" cy="5" r="3"/></svg></div></div>
                    <div className="map-marker" style={{ top: '48%', left: '78%' }}><div className="marker-icon marker-amber"><svg width="12" height="12" viewBox="0 0 12 12" fill="white"><circle cx="6" cy="5" r="3"/></svg></div></div>
                    <div className="map-marker" style={{ top: '72%', left: '22%' }}><div className="marker-icon marker-amber"><svg width="12" height="12" viewBox="0 0 12 12" fill="white"><circle cx="6" cy="5" r="3"/></svg></div></div>
                    <div className="map-marker" style={{ top: '38%', left: '55%' }}><div className="marker-icon marker-green"><svg width="12" height="12" viewBox="0 0 12 12" fill="white"><path d="M2 6 L5 9 L10 3" stroke="white" stroke-width="2" fill="none"/></svg></div></div>
                    <div className="map-marker" style={{ top: '76%', left: '68%' }}><div className="marker-icon marker-blue"><svg width="12" height="12" viewBox="0 0 12 12" fill="white"><circle cx="6" cy="5" r="3"/></svg></div></div>
                    
                    <div className="map-controls">
                      <div className="map-btn">+</div>
                      <div className="map-btn">−</div>
                      <div className="map-btn" style={{ fontSize: '12px' }}>⊞</div>
                    </div>
                    <div className="map-legend">
                      <div className="map-legend-title">Risk Score</div>
                      <div className="legend-row"><div className="legend-box" style={{ background: '#DC2626' }}></div>0.9 – 1.0</div>
                      <div className="legend-row"><div className="legend-box" style={{ background: '#F97316' }}></div>0.7 – 0.89</div>
                      <div className="legend-row"><div className="legend-box" style={{ background: '#FCD34D' }}></div>0.5 – 0.69</div>
                      <div className="legend-row"><div className="legend-box" style={{ background: '#86EFAC' }}></div>0.3 – 0.49</div>
                      <div className="legend-row"><div className="legend-box" style={{ background: '#BFDBFE' }}></div>0.0 – 0.29</div>
                    </div>
                  </div>

                  {/* TIME SCRUBBER */}
                  <div className="time-scrubber">
                    <div className="scrubber-header">
                      <div><div className="scrubber-title">Time window</div></div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <div className="scrubber-buckets">
                          {BUCKETS.map((bucket, bIdx) => (
                            <div 
                              key={bIdx} 
                              className={`scrubber-bucket ${currentBucketIdx === bIdx ? 'active' : ''}`} 
                              onClick={() => handleBucketChange(bIdx)}
                            >
                              {bucket.label}
                            </div>
                          ))}
                        </div>
                        <div className="scrubber-time-display">{currentHour < 10 ? `0${currentHour}` : currentHour}:00</div>
                      </div>
                    </div>

                    {/* Density Bar */}
                    <div className="scrubber-data-bar">
                      {bucketHours.map((h) => {
                        const d = DENSITY[h];
                        const alpha = Math.round(d * 200);
                        const r = Math.round(26 + d * 203);
                        const g = Math.round(86 - d * 50);
                        const bl = Math.round(219 - d * 150);
                        const backgroundStyle = h >= currentBucket.dimFrom
                          ? `rgba(209,213,219,${0.4 + d * 0.3})`
                          : `rgba(${r},${g},${bl},${0.25 + d * 0.55})`;
                        return (
                          <div 
                            key={h} 
                            className="sdb-seg" 
                            style={{ flex: '1', background: backgroundStyle, borderRadius: '2px' }}
                          />
                        );
                      })}
                    </div>

                    {/* Track */}
                    <div className="scrubber-track-wrap">
                      <div 
                        className="scrubber-rail" 
                        ref={railRef} 
                        onMouseDown={(e) => {
                          setIsDragging(true);
                          updateHourFromEvent(e);
                        }}
                        onTouchStart={(e) => {
                          setIsDragging(true);
                          updateHourFromEvent(e);
                        }}
                      >
                        {currentBucket.dimFrom < currentBucket.end && (
                          <div 
                            className="scrubber-dim-zone" 
                            style={{ 
                              left: `${hourToPercent(currentBucket.dimFrom) * 100}%`, 
                              width: `${(1 - hourToPercent(currentBucket.dimFrom)) * 100}%` 
                            }}
                          ></div>
                        )}
                        <div className="scrubber-fill" style={{ width: `${currentPct * 100}%` }}></div>
                        <div 
                          className="scrubber-handle" 
                          style={{ left: `${currentPct * 100}%` }}
                        >
                          <div className="scrubber-tooltip">
                            {currentHour < 10 ? `0${currentHour}` : currentHour}:00
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Tick Labels */}
                    <div className="scrubber-ticks">
                      {bucketHours.map((h) => (
                        <div 
                          key={h} 
                          className={`scrubber-tick ${h % 2 === 0 ? 'major' : ''} ${h >= currentBucket.dimFrom ? 'dim' : ''}`}
                        >
                          <div className="scrubber-tick-mark"></div>
                          <span>{h}:00</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* CONTROL ROOM VIEW */}
        {activeTab === 'ctrl' && (
          <div id="view-ctrl">
            <div className="ctrl-layout">
              <div className="ctrl-topbar">
                <div>
                  <div className="ctrl-title">Bengaluru Traffic Enforcement — Control Room</div>
                  <div className="ctrl-sub">Live overview · 54 stations · Thursday, 10:45 AM</div>
                </div>
                <div className="ctrl-spacer"></div>
                <div className="live-badge"><div className="live-dot"></div>Live Data</div>
                <span className="chip chip-blue" style={{ marginLeft: '10px' }}>Forecast: High Risk Today</span>
              </div>

              <div className="kpi-grid">
                <div className="kpi-card">
                  <div className="kpi-icon-row">
                    <div className="kpi-icon kpi-icon-red"><svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="9" cy="9" r="7"/><path d="M9 5v4l3 3"/></svg></div>
                    <span className="kpi-trend trend-up">↑ 12%</span>
                  </div>
                  <div className="kpi-value">1,428</div>
                  <div className="kpi-label">Violations today</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-icon-row">
                    <div className="kpi-icon kpi-icon-amber"><svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 9 Q9 3 15 9 Q9 15 3 9z"/></svg></div>
                    <span className="kpi-trend trend-up">↑ 3</span>
                  </div>
                  <div className="kpi-value">24</div>
                  <div className="kpi-label">Critical zones active</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-icon-row">
                    <div className="kpi-icon kpi-icon-blue"><svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="9" cy="7" r="3"/><path d="M3 16c0-3.3 2.7-6 6-6s6 2.7 6 6"/></svg></div>
                    <span className="kpi-trend trend-dn">↓ 2</span>
                  </div>
                  <div className="kpi-value">5</div>
                  <div className="kpi-label">Teams deployed</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-icon-row">
                    <div className="kpi-icon kpi-icon-green"><svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 9 L7 13 L15 5"/></svg></div>
                    <span className="kpi-trend trend-dn">↓ 5%</span>
                  </div>
                  <div className="kpi-value">62%</div>
                  <div className="kpi-label">Congestion covered</div>
                </div>
              </div>

              <div className="ctrl-row ctrl-row-3">
                <div className="ctrl-map" style={{ minHeight: '260px' }}>
                  <div className="map-bg"></div>
                  <div className="map-major-h" style={{ top: '40%', left: 0, right: 0 }}></div>
                  <div className="map-major-v" style={{ left: '35%', top: 0, bottom: 0 }}></div>
                  <div className="map-major-v" style={{ left: '70%', top: 0, bottom: 0 }}></div>
                  <div className="map-road-h" style={{ top: '60%', left: 0, right: 0 }}></div>
                  <div className="map-road-v" style={{ left: '55%', top: 0, bottom: 0 }}></div>
                  <div className="heat-cell" style={{ width: '60px', height: '55px', top: '30%', left: '30%', background: '#DC2626', opacity: .4 }}></div>
                  <div className="heat-cell" style={{ width: '45px', height: '40px', top: '20%', left: '60%', background: '#F97316', opacity: .35 }}></div>
                  <div className="heat-cell" style={{ width: '50px', height: '45px', top: '55%', left: '48%', background: '#F59E0B', opacity: .35 }}></div>
                  <div className="heat-cell" style={{ width: '35px', height: '30px', top: '65%', left: '18%', background: '#FDE68A', opacity: .3 }}></div>
                  <div className="map-marker" style={{ top: '36%', left: '33%' }}><div className="marker-icon marker-red" style={{ width: '24px', height: '24px' }}></div></div>
                  <div className="map-marker" style={{ top: '26%', left: '63%' }}><div className="marker-icon marker-amber" style={{ width: '24px', height: '24px' }}></div></div>
                  <div className="map-marker" style={{ top: '60%', left: '52%' }}><div className="marker-icon marker-amber" style={{ width: '24px', height: '24px' }}></div></div>
                  <div className="map-marker" style={{ top: '48%', left: '20%' }}><div className="marker-icon marker-green" style={{ width: '24px', height: '24px' }}></div></div>
                  <div className="ctrl-map-title">Live Congestion Heatmap</div>
                  <div className="toggle-group">
                    <div className="toggle-opt on">Risk</div>
                    <div className="toggle-opt">Traffic</div>
                    <div className="toggle-opt">Patrol</div>
                  </div>
                </div>

                <div className="card">
                  <div className="card-title">Active Alerts</div>
                  <div className="alert-feed">
                    <div className="alert-item alert-crit">
                      <div className="alert-icon alert-icon-red"><svg viewBox="0 0 10 10" fill="#DC2626"><path d="M5 1L9 9H1L5 1z"/><rect x="4.5" y="4" width="1" height="3" fill="#fff"/><rect x="4.5" y="7.5" width="1" height="1" fill="#fff"/></svg></div>
                      <div><div className="alert-msg">Upparpet junction overloaded — risk 87. No team assigned.</div><div className="alert-time">2 min ago</div></div>
                    </div>
                    <div className="alert-item alert-warn">
                      <div className="alert-icon alert-icon-amber"><svg viewBox="0 0 10 10" fill="#F59E0B"><circle cx="5" cy="5" r="4"/><rect x="4.5" y="3" width="1" height="3" fill="#fff"/><rect x="4.5" y="7" width="1" height="1" fill="#fff"/></svg></div>
                      <div><div className="alert-msg">Majestic Bus Terminal — spillover from Shivajinagar detected.</div><div className="alert-time">5 min ago</div></div>
                    </div>
                    <div className="alert-item alert-warn">
                      <div className="alert-icon alert-icon-amber"><svg viewBox="0 0 10 10" fill="#F59E0B"><circle cx="5" cy="5" r="4"/><rect x="4.5" y="3" width="1" height="3" fill="#fff"/><rect x="4.5" y="7" width="1" height="1" fill="#fff"/></svg></div>
                      <div><div className="alert-msg">Heavy vehicle parking on MG Road — junction risk +15 pts.</div><div className="alert-time">8 min ago</div></div>
                    </div>
                    <div className="alert-item alert-info">
                      <div className="alert-icon alert-icon-blue"><svg viewBox="0 0 10 10" fill="#3B82F6"><circle cx="5" cy="5" r="4"/><rect x="4.5" y="4.5" width="1" height="3" fill="#fff"/><circle cx="5" cy="3" r="0.8" fill="#fff"/></svg></div>
                      <div><div className="alert-msg">Team 3 completed patrol at Indiranagar. Violations ↓ 40%.</div><div className="alert-time">14 min ago</div></div>
                    </div>
                    <div className="alert-item alert-info">
                      <div className="alert-icon alert-icon-blue"><svg viewBox="0 0 10 10" fill="#3B82F6"><circle cx="5" cy="5" r="4"/><rect x="4.5" y="4.5" width="1" height="3" fill="#fff"/><circle cx="5" cy="3" r="0.8" fill="#fff"/></svg></div>
                      <div><div className="alert-msg">LightGBM forecast: Sunday predicted peak — 50K+ records expected.</div><div className="alert-time">22 min ago</div></div>
                    </div>
                  </div>
                </div>

                <div className="card">
                  <div className="card-title">Stackelberg Patrol Allocation</div>
                  <div style={{ fontSize: '11px', color: '#6B7280', marginBottom: '8px' }}>Game-theory optimal · 5 teams · 10:45 AM</div>
                  <div className="patrol-zone-list">
                    <div className="pz-item"><div className="pz-team pz-team-1">T1</div><div className="pz-info"><div className="pz-zone">Upparpet / Elite Jct</div><div className="pz-sub">High risk · 2-wheeler dominant</div></div><div className="pz-prob">92%</div></div>
                    <div className="pz-item"><div className="pz-team pz-team-2">T2</div><div className="pz-info"><div className="pz-zone">Shivajinagar Market</div><div className="pz-sub">High risk · Double parking</div></div><div className="pz-prob">85%</div></div>
                    <div className="pz-item"><div className="pz-team pz-team-3">T3</div><div className="pz-info"><div className="pz-zone">Majestic Bus Terminal</div><div className="pz-sub">Spillover zone · Bus stop</div></div><div className="pz-prob">78%</div></div>
                    <div className="pz-item"><div className="pz-team pz-team-4">T4</div><div className="pz-info"><div className="pz-zone">Indiranagar 100ft Rd</div><div className="pz-sub">Medium risk · Wrong parking</div></div><div className="pz-prob">61%</div></div>
                    <div className="pz-item"><div className="pz-team pz-team-5">T5</div><div className="pz-info"><div className="pz-zone">Koramangala 5th Block</div><div className="pz-sub">Medium risk · NP zone</div></div><div className="pz-prob">55%</div></div>
                  </div>
                  <div className="divider"></div>
                  <div style={{ fontSize: '11px', color: '#6B7280' }}>Patrol probability = P(enforcement | Stackelberg equilibrium)</div>
                </div>
              </div>

              <div className="ctrl-row ctrl-row-3">
                <div className="card">
                  <div className="card-title">7-Day Violation Forecast — LightGBM</div>
                  <div style={{ fontSize: '12px', color: '#6B7280', marginBottom: '10px' }}>Precision@10: 81% · MAE: 214 violations/zone-day</div>
                  <div className="forecast-row"><span className="forecast-day">Thu</span><div className="forecast-track"><div className="forecast-fill" style={{ width: '72%', background: '#1A56DB' }}></div></div><span className="forecast-num">1,428</span></div>
                  <div className="forecast-row"><span className="forecast-day">Fri</span><div className="forecast-track"><div className="forecast-fill" style={{ width: '80%', background: '#3B82F6' }}></div></div><span className="forecast-num">1,591</span></div>
                  <div className="forecast-row"><span className="forecast-day">Sat</span><div className="forecast-track"><div className="forecast-fill" style={{ width: '88%', background: '#F97316' }}></div></div><span className="forecast-num">1,744</span></div>
                  <div className="forecast-row"><span className="forecast-day" style={{ color: '#DC2626', fontWeight: 700 }}>Sun</span><div className="forecast-track"><div className="forecast-fill" style={{ width: '100%', background: '#DC2626' }}></div></div><span className="forecast-num" style={{ color: '#DC2626' }}>1,986</span></div>
                  <div className="forecast-row"><span className="forecast-day">Mon</span><div className="forecast-track"><div className="forecast-fill" style={{ width: '62%', background: '#60A5FA' }}></div></div><span className="forecast-num">1,230</span></div>
                  <div className="forecast-row"><span className="forecast-day">Tue</span><div className="forecast-track"><div className="forecast-fill" style={{ width: '58%', background: '#93C5FD' }}></div></div><span className="forecast-num">1,148</span></div>
                  <div className="forecast-row"><span className="forecast-day">Wed</span><div className="forecast-track"><div className="forecast-fill" style={{ width: '55%', background: '#BAE6FD' }}></div></div><span className="forecast-num">1,089</span></div>
                  <div style={{ marginTop: '8px', padding: '6px 8px', background: '#FFFBEB', borderRadius: '6px', border: '1px solid #FDE68A', fontSize: '11px', color: '#92400E' }}>⚠ Sunday forecast exceeds average. Pre-deploy +3 teams recommended.</div>
                </div>

                <div className="card">
                  <div className="card-title">Waterbed Effect Simulation</div>
                  <div style={{ fontSize: '12px', color: '#6B7280', marginBottom: '8px' }}>H3 hex grid · Enforce Zone A → violations migrate</div>
                  <div className="waterbed-grid">
                    <div className="wb-cell wb-neutral">—</div><div className="wb-cell wb-normal">42</div><div className="wb-cell wb-spill-high">67↑</div><div className="wb-cell wb-normal">38</div><div className="wb-cell wb-neutral">—</div>
                    <div className="wb-cell wb-normal">51</div><div className="wb-cell wb-spill-high">89↑</div><div className="wb-cell wb-enforced">✓ 0</div><div className="wb-cell wb-spill-high">74↑</div><div className="wb-cell wb-normal">29</div>
                    <div className="wb-cell wb-neutral">—</div><div className="wb-cell wb-spill-med">58↑</div><div className="wb-cell wb-normal">41</div><div className="wb-cell wb-spill-med">55↑</div><div className="wb-cell wb-neutral">—</div>
                    <div className="wb-cell wb-neutral">—</div><div className="wb-cell wb-normal">33</div><div className="wb-cell wb-spill-med">48↑</div><div className="wb-cell wb-normal">26</div><div className="wb-cell wb-neutral">—</div>
                    <div className="wb-cell wb-neutral">—</div><div className="wb-cell wb-neutral">—</div><div className="wb-cell wb-normal">22</div><div className="wb-cell wb-neutral">—</div><div className="wb-cell wb-neutral">—</div>
                  </div>
                  <div style={{ display: 'flex', gap: '6px', marginTop: '8px', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '10px', padding: '2px 6px', borderRadius: '4px', background: '#DCFCE7', color: '#15803D', border: '1px solid #22C55E' }}>✓ Enforced</span>
                    <span style={{ fontSize: '10px', padding: '2px 6px', borderRadius: '4px', background: '#FEF9C3', color: '#92400E' }}>↑ Spillover</span>
                    <span style={{ fontSize: '10px', padding: '2px 6px', borderRadius: '4px', background: '#EFF6FF', color: '#1E40AF' }}>Normal</span>
                  </div>
                </div>

                <div className="card">
                  <div className="card-title">Top Stations by Violation Count</div>
                  <table className="station-table">
                    <thead>
                      <tr><th>#</th><th>Station</th><th>Count</th><th>Risk</th><th>Status</th></tr>
                    </thead>
                    <tbody>
                      <tr><td style={{ color: '#9CA3AF', fontWeight: 700 }}>1</td><td className="st-name">Upparpet</td><td>5,838</td><td><span className="risk-pill risk-pill-red">87</span></td><td><span className="chip chip-amber" style={{ fontSize: '10px', padding: '2px 7px' }}>Pending</span></td></tr>
                      <tr><td style={{ color: '#9CA3AF', fontWeight: 700 }}>2</td><td className="st-name">Shivajinagar</td><td>3,402</td><td><span class="risk-pill risk-pill-red">79</span></td><td><span className="chip chip-green" style={{ fontSize: '10px', padding: '2px 7px' }}>Active</span></td></tr>
                      <tr><td style={{ color: '#9CA3AF', fontWeight: 700 }}>3</td><td className="st-name">KR Market</td><td>2,981</td><td><span className="risk-pill risk-pill-amber">74</span></td><td><span className="chip chip-green" style={{ fontSize: '10px', padding: '2px 7px' }}>Active</span></td></tr>
                      <tr><td style={{ color: '#9CA3AF', fontWeight: 700 }}>4</td><td className="st-name">Indiranagar</td><td>2,114</td><td><span className="risk-pill risk-pill-amber">61</span></td><td><span className="chip chip-green" style={{ fontSize: '10px', padding: '2px 7px' }}>Active</span></td></tr>
                      <tr><td style={{ color: '#9CA3AF', fontWeight: 700 }}>5</td><td className="st-name">Koramangala</td><td>1,856</td><td><span className="risk-pill risk-pill-amber">55</span></td><td><span className="chip chip-blue" style={{ fontSize: '10px', padding: '2px 7px' }}>Patrol</span></td></tr>
                      <tr><td style={{ color: '#9CA3AF', fontWeight: 700 }}>6</td><td className="st-name">Silk Board</td><td>1,423</td><td><span className="risk-pill risk-pill-green">48</span></td><td><span className="chip chip-amber" style={{ fontSize: '10px', padding: '2px 7px' }}>Pending</span></td></tr>
                    </tbody>
                  </table>
                  <div className="divider"></div>
                  <div style={{ fontSize: '11px', color: '#6B7280' }}>54 total stations · 29 monitored · 25 unmonitored</div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}