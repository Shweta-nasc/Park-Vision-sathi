import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/endpoints';
import { useAppState } from '@/state/AppState';
import { useZoneNames } from '@/hooks/queries';
import { shortId } from '@/utils/format';
import { Skeleton } from '../Skeleton';

/** Game-theory view: Stackelberg patrol allocations + violator utility. */
export function GameTheoryPanel() {
  const { hour, station } = useAppState();
  const names = useZoneNames();
  const nameFor = (id: string) => names.data?.get(id) ?? shortId(id);

  const stack = useQuery({
    queryKey: ['stackelberg', hour],
    queryFn: () => api.stackelberg(hour, 10),
    enabled: !!station,
  });
  const violators = useQuery({
    queryKey: ['violators', hour, 'panel'],
    queryFn: () => api.violators(hour, 8),
    enabled: !!station,
  });

  const maxProb = stack.data?.reduce((m, a) => Math.max(m, a.patrol_probability), 0) ?? 1;

  return (
    <div className="game-container">
      <h3 className="panel-h">Game Theory</h3>
      <p className="panel-sub">Stackelberg patrol allocation vs. violator adaptation utility.</p>

      <div className="detail-section-title">Patrol Probability (top zones)</div>
      {stack.isLoading && <Skeleton height={40} />}
      <div className="game-list">
        {stack.data?.map((a, i) => (
          <div key={a.h3_id} className="game-row">
            <span className="forecast-rank">#{i + 1}</span>
            <span className="forecast-id" title={a.h3_id}>{nameFor(a.h3_id)}</span>
            <div className="forecast-bar-track">
              <div
                className="forecast-bar-fill"
                style={{ width: `${(a.patrol_probability / maxProb) * 100}%`, background: '#3B82F6' }}
              />
            </div>
            <span className="forecast-val">{(a.patrol_probability * 100).toFixed(2)}%</span>
          </div>
        ))}
      </div>

      <div className="detail-section-title" style={{ marginTop: 14 }}>Violator Utility (highest risk)</div>
      {violators.isLoading && <Skeleton height={40} />}
      <div className="game-list">
        {violators.data?.map((v) => (
          <div key={v.h3_id} className="game-row">
            <span className="forecast-id" title={v.h3_id}>{nameFor(v.h3_id)}</span>
            <span className="violator-pill">risk {v.violator_risk_score.toFixed(0)}</span>
            <span className="violator-cost">cost {v.expected_cost.toFixed(1)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
