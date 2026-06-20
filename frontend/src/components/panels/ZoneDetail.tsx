import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/endpoints';
import { useAppState } from '@/state/AppState';
import { useMapOverlay } from '@/state/MapOverlay';
import { RiskGauge } from '../RiskGauge';
import { EmptyState } from '../Skeleton';
import { bandColor } from '@/utils/risk';
import { cleanJunction } from '@/utils/format';

function Bar({ label, pct }: { label: string; pct: number }) {
  const v = Math.max(0, Math.min(100, pct));
  const c = v >= 70 ? '#EF4444' : v >= 40 ? '#F59E0B' : '#10B981';
  return (
    <div className="detail-bar-row">
      <span className="detail-bar-label">{label}</span>
      <div className="detail-bar-track">
        <div className="detail-bar-fill" style={{ width: `${v}%`, background: c }} />
      </div>
      <span className="detail-bar-value">{v.toFixed(0)}%</span>
    </div>
  );
}

export function ZoneDetail() {
  const { selectedZone, hour, setPanel } = useAppState();
  const { setRouteTarget } = useMapOverlay();

  // Enrich with full backend detail + traffic context (lane-hours).
  const detail = useQuery({
    queryKey: ['zoneDetail', selectedZone?.h3_id, hour],
    queryFn: () => api.zoneDetail(selectedZone!.h3_id, hour),
    enabled: !!selectedZone,
  });
  const traffic = useQuery({
    queryKey: ['traffic', selectedZone?.h3_id],
    queryFn: () => api.traffic(selectedZone!.h3_id),
    enabled: !!selectedZone,
  });

  if (!selectedZone) {
    return <EmptyState title="Click a hotspot on the map or select a priority area to see details" />;
  }

  const z = { ...selectedZone, ...(detail.data ?? {}) };
  const name = cleanJunction(z.junction) || z.h3_id;
  const laneHours = z.estimated_lane_hours_blocked;
  const ratio = traffic.data?.travel_time_ratio ?? null;

  return (
    <div className="details-content">
      <div className="detail-zone-header">
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 2 }}>{name}</div>
          <div className="detail-zone-id">
            {z.h3_id} · Hour {hour}:00
          </div>
        </div>
        <span className="detail-risk-badge" style={{ background: 'rgba(255,255,255,.08)', color: bandColor(z.impact_band) }}>
          {z.impact_band}
        </span>
      </div>

      <div className="detail-gauge-row">
        <RiskGauge score={z.congestion_impact} />
        <div>
          <div className="detail-score-label">Congestion Impact</div>
          <div className="detail-band" style={{ color: bandColor(z.impact_band) }}>
            {z.impact_band}
          </div>
          {z.station && <div className="detail-score-label">Station: {z.station}</div>}
        </div>
      </div>

      {/* Lane-hours blocked — the tangible metric judges latch onto */}
      <div className="detail-section">
        <div className="detail-section-title">Traffic Impact</div>
        <div className="lane-hours-card">
          <div className="lane-hours-value">{laneHours.toFixed(1)}</div>
          <div className="lane-hours-label">estimated lane-hours blocked / day</div>
          {ratio != null && <div className="lane-hours-ratio">Travel time ratio: {ratio}×</div>}
        </div>
      </div>

      <div className="detail-section">
        <div className="detail-section-title">Impact Breakdown</div>
        <Bar label="Density" pct={z.density * 100} />
        <Bar label="Road Imp." pct={z.road_importance * 100} />
        <Bar label="Peak Weight" pct={(z.peak_weight / 1.5) * 100} />
        <Bar label="Repeat Offend." pct={z.repeat_offender * 100} />
        <Bar label="Heavy Vehicle" pct={z.heavy_vehicle_ratio * 100} />
      </div>

      <div className="detail-section">
        <div className="detail-section-title">Operations Intel</div>
        <div className="detail-stats">
          <div className="detail-stat">
            <div className="detail-stat-value">{'force_needed' in z ? (z as any).force_needed : '—'}</div>
            <div className="detail-stat-label">Force units</div>
          </div>
          <div className="detail-stat">
            <div className="detail-stat-value">{z.violation_count || '—'}</div>
            <div className="detail-stat-label">Violations</div>
          </div>
          <div className="detail-stat">
            <div className="detail-stat-value" style={{ color: '#3B82F6' }}>
              {((z.patrol_probability ?? 0) * 100).toFixed(1)}%
            </div>
            <div className="detail-stat-label">Patrol prob.</div>
          </div>
          <div className="detail-stat">
            <div className="detail-stat-value" style={{ color: '#EC4899' }}>
              {(z.violator_risk_score ?? 0).toFixed(0)}
            </div>
            <div className="detail-stat-label">Violator risk</div>
          </div>
        </div>
      </div>

      <div className="detail-actions">
        <button className="detail-btn detail-btn-primary" onClick={() => setRouteTarget(selectedZone)}>
          Route now →
        </button>
        <button className="detail-btn detail-btn-outline" onClick={() => setPanel('chat')}>
          🤖 AI Explain
        </button>
      </div>
    </div>
  );
}
