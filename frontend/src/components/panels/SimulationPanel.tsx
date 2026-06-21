import { useCallback, useEffect, useState } from 'react';
import { useSimulation, useZoneNames } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';
import { useMapOverlay } from '@/state/MapOverlay';
import { useDebounce } from '@/hooks/useDebounce';
import { shortId } from '@/utils/format';
import { useToast } from '../Toast';

/**
 * Patrol simulation. The team slider auto-runs the simulation (debounced) and
 * the result is pushed to the map overlay so allocations + spillover render
 * in real time — the core interactive demo beat. A "Run Simulation" button
 * also triggers an immediate run (bypassing the debounce).
 */
export function SimulationPanel() {
  const { hour, station } = useAppState();
  const { simResult, setSimResult } = useMapOverlay();
  const sim = useSimulation();
  const toast = useToast();
  const names = useZoneNames();
  const nameFor = (id: string) => names.data?.get(id) ?? shortId(id);
  const [teams, setTeams] = useState(6);
  const debouncedTeams = useDebounce(teams, 350);

  const runSim = useCallback(
    (numTeams: number) => {
      if (!station) return;
      sim.mutate(
        { num_teams: numTeams, hour, strategy: 'stackelberg' },
        {
          onSuccess: (r) => setSimResult(r),
          onError: () => toast('Simulation failed', 'error'),
        },
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hour, station],
  );

  // Live auto-run as the slider / hour changes (debounced).
  useEffect(() => {
    runSim(debouncedTeams);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedTeams, hour, station]);

  return (
    <div className="sim-container">
      <h3 className="panel-h">Patrol Simulation</h3>
      <p className="panel-sub">Deploy teams using game-theoretic mixed strategies. Drag the slider — the map updates live.</p>

      <div className="sim-control">
        <label className="sim-label">
          <span>Patrol Teams</span>
          <span className="highlight">{teams}</span>
        </label>
        <input
          type="range"
          min={1}
          max={15}
          value={teams}
          step={1}
          onChange={(e) => setTeams(+e.target.value)}
          className="sim-slider"
        />
      </div>

      <button
        className="sim-run-btn"
        onClick={() => runSim(teams)}
        disabled={!station || sim.isPending}
      >
        {sim.isPending ? 'Running…' : `▶ Run Simulation (${teams} teams)`}
      </button>

      {sim.isPending && <div className="panel-loading"><div className="loading-spinner" /> Computing…</div>}

      {simResult && (
        <div className="sim-results">
          <div className="sim-metric">
            <span>Coverage</span>
            <span className="highlight">{simResult.covered_impact_pct}%</span>
          </div>
          <div className="sim-bar-track">
            <div className="sim-bar-fill" style={{ width: `${Math.min(simResult.covered_impact_pct, 100)}%` }} />
          </div>
          <div className="sim-metric">
            <span>Impact Covered</span>
            <span>{simResult.total_impact_covered.toFixed(0)}</span>
          </div>
          <div className="sim-metric">
            <span>Uncovered High-Risk</span>
            <span className="text-danger">{simResult.uncovered_zones.length}</span>
          </div>
          <div className="sim-metric">
            <span>Spillover Zones</span>
            <span className="text-warning">{simResult.spillover_zones.length}</span>
          </div>

          {simResult.spillover_zones.length > 0 && (
            <div className="sim-spillover-list">
              <div className="detail-section-title">Waterbed Effect (top shifts)</div>
              {simResult.spillover_zones.slice(0, 5).map((s) => (
                <div key={s.h3_id} className="spillover-row">
                  <span className="spillover-id" title={s.h3_id}>{nameFor(s.h3_id)}</span>
                  <span className="spillover-change" style={{ color: s.change_pct > 0 ? '#EF4444' : '#10B981' }}>
                    {s.original_impact.toFixed(0)} → {s.adjusted_impact.toFixed(0)} ({s.change_pct > 0 ? '+' : ''}
                    {s.change_pct.toFixed(0)}%)
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
