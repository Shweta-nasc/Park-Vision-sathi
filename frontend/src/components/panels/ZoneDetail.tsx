import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/endpoints';
import { useAppState } from '@/state/AppState';
import { useMapOverlay } from '@/state/MapOverlay';
import { RiskGauge } from '../RiskGauge';
import { EmptyState } from '../Skeleton';
import { bandColor, riskColor } from '@/utils/risk';
import { cleanJunction, fmt } from '@/utils/format';
import type { CongestionComponents } from '@/types/api';

function Bar({ label, pct, weight }: { label: string; pct: number; weight?: number }) {
  const v = Math.max(0, Math.min(100, pct));
  const c = v >= 70 ? '#EF4444' : v >= 40 ? '#F59E0B' : '#10B981';
  return (
    <div className="detail-bar-row">
      <span className="detail-bar-label">
        {label}
        {weight != null && <span className="detail-bar-weight"> ·{Math.round(weight * 100)}%</span>}
      </span>
      <div className="detail-bar-track">
        <div className="detail-bar-fill" style={{ width: `${v}%`, background: c }} />
      </div>
      <span className="detail-bar-value">{v.toFixed(0)}</span>
    </div>
  );
}

/** Component weights (match backend CIS weights). */
const COMP_META: { key: keyof CongestionComponents; label: string; weight?: number }[] = [
  { key: 'lane_blockage', label: 'Lane blockage', weight: 0.3 },
  { key: 'intersection_impact', label: 'Intersection', weight: 0.25 },
  { key: 'traffic_degradation', label: 'Traffic degradation', weight: 0.25 },
  { key: 'access_blockage', label: 'Access blockage', weight: 0.1 },
  { key: 'vehicle_size', label: 'Heavy vehicles', weight: 0.1 },
];

export function ZoneDetail() {
  const { selectedZone, hour, setPanel } = useAppState();
  const { setRouteTarget } = useMapOverlay();

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
    return <EmptyState title="Select a hotspot on the map or a priority area to see its full profile" />;
  }

  const z = { ...selectedZone, ...(detail.data ?? {}) };
  const name = cleanJunction(z.junction) || z.station || z.h3_id;
  const laneHours = z.estimated_lane_hours_blocked ?? 0;
  const ratio = traffic.data?.travel_time_ratio ?? z.mappls_ratio ?? null;
  const components = z.components as CongestionComponents | undefined;
  const calibrated = z.calibrated_score;
  const showCalib = calibrated != null && Math.abs(calibrated - z.congestion_impact) >= 0.5;

  return (
    <div className="details-content">
      {/* Header */}
      <div className="detail-zone-header">
        <div>
          <div className="detail-zone-name">{name}</div>
          <div className="detail-zone-id">{z.h3_id} · {hour}:00 IST</div>
        </div>
        <span className="risk-chip" style={{ background: `${riskColor(z.risk_label)}1a`, color: riskColor(z.risk_label) }}>
          {z.risk_label}
        </span>
      </div>

      {/* Dual score: Congestion Impact (gauge) + Enforcement priority */}
      <div className="detail-score-grid">
        <div className="detail-gauge-cell">
          <RiskGauge score={z.congestion_impact} />
          <div className="detail-gauge-cap">Congestion Impact</div>
          <div className="detail-gauge-band" style={{ color: bandColor(z.impact_band) }}>{z.impact_band}</div>
        </div>
        <div className="detail-score-cell">
          <div className="detail-score-num" style={{ color: riskColor(z.risk_label) }}>{z.risk_score.toFixed(0)}</div>
          <div className="detail-gauge-cap">Enforcement priority</div>
          <div className="detail-gauge-band" style={{ color: riskColor(z.risk_label) }}>{z.risk_label}</div>
          <div className="detail-score-hint">where violations happen</div>
        </div>
      </div>

      {showCalib && (
        <div className="calib-note">
          <span className="calib-dot" />
          Agent calibrated CIS {z.congestion_impact.toFixed(0)} → <strong>{calibrated!.toFixed(0)}</strong> against live travel time
          {z.agent_reasoning ? `: ${z.agent_reasoning}` : ''}
        </div>
      )}

      {/* Lane-hours blocked — the tangible metric */}
      <div className="detail-section">
        <div className="detail-section-title">Traffic Impact</div>
        <div className="lane-hours-card">
          <div className="lane-hours-value">{fmt(laneHours)}</div>
          <div className="lane-hours-label">estimated lane-hours blocked</div>
          {ratio != null && (
            <div className="lane-hours-ratio">MapMyIndia travel-time ratio: <strong>{ratio}×</strong></div>
          )}
        </div>
      </div>

      {/* CIS component breakdown (real) */}
      <div className="detail-section">
        <div className="detail-section-title">
          Congestion Impact Breakdown
          {detail.isLoading && <span className="detail-loading-dot"> · loading…</span>}
        </div>
        {components ? (
          COMP_META.map((c) => (
            <Bar key={c.key} label={c.label} weight={c.weight} pct={(components[c.key] ?? 0) * 100} />
          ))
        ) : (
          <>
            <Bar label="Violation density" pct={z.density * 100} />
            <Bar label="Road importance" pct={z.road_importance * 100} />
            <Bar label="Heavy vehicles" pct={z.heavy_vehicle_ratio * 100} />
          </>
        )}
      </div>

      {/* Top violations */}
      {z.top_violations && z.top_violations.length > 0 && (
        <div className="detail-section">
          <div className="detail-section-title">Top Violations</div>
          <div className="chip-row">
            {z.top_violations.slice(0, 5).map((v) => (
              <span key={v} className="violation-chip">{v}</span>
            ))}
          </div>
        </div>
      )}

      {/* Operations intel */}
      <div className="detail-section">
        <div className="detail-section-title">Operations Intel</div>
        <div className="detail-stats">
          <div className="detail-stat">
            <div className="detail-stat-value">{z.violation_count ? fmt(z.violation_count) : '—'}</div>
            <div className="detail-stat-label">Violations</div>
          </div>
          <div className="detail-stat">
            <div className="detail-stat-value">{'force_needed' in z ? (z as any).force_needed : '—'}</div>
            <div className="detail-stat-label">Force units</div>
          </div>
          <div className="detail-stat">
            <div className="detail-stat-value" style={{ color: '#2563eb' }}>
              {((z.patrol_probability ?? 0) * 100).toFixed(1)}%
            </div>
            <div className="detail-stat-label">Patrol prob.</div>
          </div>
          <div className="detail-stat">
            <div className="detail-stat-value" style={{ color: '#db2777' }}>
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
          Ask AI
        </button>
      </div>
    </div>
  );
}
