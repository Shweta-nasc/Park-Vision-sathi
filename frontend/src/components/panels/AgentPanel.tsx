import { useAgentCalibration } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';
import { Skeleton } from '../Skeleton';

/**
 * Self-Validating Agent panel (planner demo moment #4).
 * Surfaces the agent's calibration of model scores against REAL Mappls traffic
 * data: a summary of validated/adjusted zones + a scrollable reasoning log.
 */
export function AgentPanel() {
  const { station } = useAppState();
  const agent = useAgentCalibration(!!station);

  const s = agent.data?.summary;

  return (
    <div className="agent-container">
      <h3 className="panel-h">Self-Validating Agent</h3>
      <p className="panel-sub">
        The agent compares model congestion scores against real Mappls travel-time
        data and calibrates each zone — with its reasoning.
      </p>

      {agent.isLoading && (
        <div style={{ padding: '0 16px' }}>
          <Skeleton height={40} /> <Skeleton height={40} />
        </div>
      )}

      {agent.data && !agent.data.available && (
        <p className="panel-sub">{agent.data.detail ?? 'Calibration not available.'}</p>
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
            <div className="agent-metric-val text-danger">{s.adjusted_down}</div>
            <div className="agent-metric-lbl">Adj. down</div>
          </div>
          <div className="agent-metric">
            <div className="agent-metric-val text-warning">{s.adjusted_up}</div>
            <div className="agent-metric-lbl">Adj. up</div>
          </div>
        </div>
      )}

      {agent.data?.log && agent.data.log.length > 0 && (
        <>
          <div className="detail-section-title" style={{ margin: '14px 16px 6px' }}>
            Agent Reasoning Log
          </div>
          <div className="agent-log">
            {agent.data.log.map((e, i) => (
              <div key={`${e.zone_id}-${i}`} className="agent-log-row">
                <span className="agent-log-zone">{e.zone_id}</span>
                <span className="agent-log-text">{e.reasoning}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
