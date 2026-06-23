import { useAgentReport } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';
import { Skeleton } from '../Skeleton';
import { ProofScatter } from './ProofScatter';
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

const fmtRho = (v?: number | null): string => (v == null ? '—' : v.toFixed(3));
const fmtWeight = (v?: number | null): string => (v == null ? '—' : v.toFixed(3));

export function AgentPanel() {
  const { station } = useAppState();
  const agent = useAgentReport(!!station);
  const s = agent.data?.summary;
  const zones: AgentZone[] = agent.data?.zones ?? [];
  const cal = agent.data?.calibration_run ?? null;
  const calReady = !!(cal && cal.available && cal.weights_new);

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

      {/* Task 13: the density≠impact proof — the non-circular trust metric on
          held-out zones, with a graceful pending state until the live run. */}
      <ProofScatter enabled />

      {/* Task 6: the calibration loop — before/after fitted weights + agreement
          with reality. Renders a graceful "pending live run" state until a real
          peak-time MapMyIndia collection has been calibrated. */}
      {cal && (
        <div className="agent-calibration" style={{ margin: '12px 16px' }}>
          <div className="detail-section-title" style={{ marginBottom: 6 }}>
            Calibration Loop (MapMyIndia)
          </div>

          {!calReady && (
            <p className="panel-sub" style={{ margin: 0 }}>
              Weight calibration is pending a live peak-time MapMyIndia run. Once
              real congestion is collected, the agent refits the CIS weights and
              reports its agreement with reality here.
            </p>
          )}

          {calReady && cal && (
            <>
              <p className="panel-sub" style={{ margin: '0 0 8px' }}>
                Agreement with reality went <strong>{fmtRho(cal.spearman_old)}</strong>{' '}
                → <strong>{fmtRho(cal.spearman_new)}</strong> (Spearman ρ) on{' '}
                <strong>{cal.n_zones_measured ?? '—'}</strong> real-traffic zones
                {cal.n_exploration ? ` (incl. ${cal.n_exploration} exploration)` : ''}.
              </p>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: '#6b7280' }}>
                    <th style={{ padding: '2px 4px' }}>Component</th>
                    <th style={{ padding: '2px 4px', textAlign: 'right' }}>Old</th>
                    <th style={{ padding: '2px 4px', textAlign: 'right' }}>New</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.keys(cal.weights_new ?? {}).map((k) => {
                    const oldW = cal.weights_old?.[k];
                    const newW = cal.weights_new?.[k];
                    const changed = oldW != null && newW != null && Math.abs(oldW - newW) >= 0.005;
                    return (
                      <tr key={k} style={{ borderTop: '1px solid #f0f0f0' }}>
                        <td style={{ padding: '2px 4px' }}>{k}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right' }}>{fmtWeight(oldW)}</td>
                        <td
                          style={{
                            padding: '2px 4px',
                            textAlign: 'right',
                            fontWeight: changed ? 600 : 400,
                            color: changed ? '#2563eb' : 'inherit',
                          }}
                        >
                          {fmtWeight(newW)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {cal.lozo_metrics?.lozo_r2 != null && (
                <p className="panel-sub" style={{ margin: '8px 0 0' }}>
                  Degradation model ({cal.lozo_metrics.model ?? 'ridge'}): leave-one-zone-out
                  R²={fmtRho(cal.lozo_metrics.lozo_r2)}, ρ={fmtRho(cal.lozo_metrics.lozo_spearman)}.
                </p>
              )}
            </>
          )}
        </div>
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
