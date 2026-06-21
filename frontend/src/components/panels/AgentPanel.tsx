import { useAgentReport } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';
import { Skeleton } from '../Skeleton';
import type { AgentZone } from '@/types/api';

/**
 * Self-Validating Agent panel. The agent compares the model's Congestion Impact
 * Score against REAL MapMyIndia travel-time data and calibrates each zone —
 * surfacing a summary + its per-zone reasoning.
 */
function statusMeta(status: string): { label: string; color: string } {
  if (status === 'adjusted_up') return { label: 'Adjusted ↑', color: '#dc2626' };
  if (status === 'adjusted_down') return { label: 'Adjusted ↓', color: '#2563eb' };
  return { label: 'Accurate', color: '#10b981' };
}

export function AgentPanel() {
  const { station } = useAppState();
  const agent = useAgentReport(!!station);
  const s = agent.data?.summary;
  const zones: AgentZone[] = agent.data?.zones ?? [];

  return (
    <div className="agent-container">
      <h3 className="panel-h">Self-Validating Agent</h3>
      <p className="panel-sub">
        Calibrates each zone's Congestion Impact Score against real MapMyIndia
        travel-time data — and shows its reasoning.
      </p>

      {agent.isLoading && (
        <div style={{ padding: '0 16px' }}>
          <Skeleton height={40} /> <Skeleton height={40} />
        </div>
      )}

      {agent.data && !agent.data.available && (
        <p className="panel-sub">Calibration report not available.</p>
      )}

      {s && (
        <div className="agent-summary">
          <div className="agent-metric">
            <div className="agent-metric-val">{s.validated}</div>
            <div className="agent-metric-lbl">Validated</div>
          </div>
          <div className="agent-metric">
            <div className="agent-metric-val text-success">{s.accurate}</div>
            <div className="agent-metric-lbl">Accurate</div>
          </div>
          <div className="agent-metric">
            <div className="agent-metric-val text-danger">{s.adjusted_up}</div>
            <div className="agent-metric-lbl">Adj. up</div>
          </div>
          <div className="agent-metric">
            <div className="agent-metric-val" style={{ color: '#2563eb' }}>{s.adjusted_down}</div>
            <div className="agent-metric-lbl">Adj. down</div>
          </div>
        </div>
      )}

      {s?.mean_abs_adjustment_pct != null && (
        <p className="agent-meanadj">
          Mean absolute calibration adjustment: <strong>{s.mean_abs_adjustment_pct}%</strong>
        </p>
      )}

      {zones.length > 0 && (
        <>
          <div className="detail-section-title" style={{ margin: '14px 16px 6px' }}>Agent Reasoning Log</div>
          <div className="agent-log">
            {zones.map((e, i) => {
              const m = statusMeta(e.status);
              return (
                <div key={`${e.zone_id}-${i}`} className="agent-log-row" style={{ borderLeftColor: m.color }}>
                  <div className="agent-log-head">
                    <span className="agent-log-zone">{e.station ?? e.zone_id}</span>
                    <span className="agent-log-status" style={{ color: m.color }}>
                      {e.raw_score?.toFixed(0)} → {e.calibrated_score?.toFixed(0)} · {m.label}
                    </span>
                  </div>
                  <span className="agent-log-text">{e.reasoning}</span>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
