import { useHealth, useStationSummary } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';
import { TimeControls } from './TimeControls';

export function TopHeader() {
  const { station, hour } = useAppState();
  const health = useHealth();
  const summary = useStationSummary(station?.name ?? null, hour);

  const status = health.isLoading
    ? { cls: '', text: 'Connecting' }
    : health.isError
      ? { cls: 'err', text: 'Offline' }
      : { cls: 'ok', text: 'Connected' };

  return (
    <header className="top-header">
      <div className="header-left">
        <div className="station-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 22s-8-4.5-8-11.8A8 8 0 0 1 12 2a8 8 0 0 1 8 8.2c0 7.3-8 11.8-8 11.8z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
          <span>{station?.name ?? '—'}</span>
        </div>
        <div className="header-divider" />
        <div className="header-meta">
          <span className="meta-item">{summary.data?.total_zones ?? 0} zones</span>
          <span className="meta-dot">·</span>
          <span className="meta-item meta-high">{summary.data?.high_risk_zones ?? 0} high priority</span>
        </div>
      </div>
      <div className="header-center">
        <TimeControls />
      </div>
      <div className="header-right">
        <div className="status-pill">
          <span className={`status-dot ${status.cls}`} />
          <span>{status.text}</span>
        </div>
      </div>
    </header>
  );
}
