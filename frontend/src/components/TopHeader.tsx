import { useHealth, useStationSummary } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';
import { TimeControls } from './TimeControls';
import { fmt } from '@/utils/format';

export function TopHeader({ onSwitchStation }: { onSwitchStation: () => void }) {
  const { station, hour } = useAppState();
  const health = useHealth();
  const summary = useStationSummary(station?.name ?? null, hour);

  const status = health.isLoading
    ? { cls: '', text: 'Connecting' }
    : health.isError
      ? { cls: 'err', text: 'Offline' }
      : { cls: 'ok', text: 'Live' };

  return (
    <header className="top-bar">
      <div className="bar-left">
        <div className="brand-mark" title="ParkVision Saathi">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M12 22s-8-4.5-8-11.8A8 8 0 0 1 12 2a8 8 0 0 1 8 8.2c0 7.3-8 11.8-8 11.8z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
        </div>
        <div className="brand-text">
          <span className="brand-name">ParkVision <b>Saathi</b></span>
          <span className="brand-tag">Patrol Operations</span>
        </div>

        <button className="station-switch" onClick={onSwitchStation} title="Switch station">
          <span className="station-switch-name">{station?.name ?? '—'}</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>

        <div className="bar-counts">
          <span className="count-pill">{summary.data?.total_zones ?? 0} zones</span>
          <span className="count-pill danger">{summary.data?.high_risk_zones ?? 0} high-risk</span>
          {summary.data?.total_violations != null && (
            <span className="count-pill subtle">{fmt(summary.data.total_violations)} violations</span>
          )}
        </div>
      </div>

      <div className="bar-right">
        <TimeControls />
        <div className={`status-pill ${status.cls}`}>
          <span className={`status-dot ${status.cls}`} />
          <span>{status.text}</span>
        </div>
      </div>
    </header>
  );
}
