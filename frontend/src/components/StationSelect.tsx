import { useMemo, useState } from 'react';
import { useStations } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';
import { SkeletonList } from './Skeleton';
import { fmt } from '@/utils/format';

/** Full-screen station picker — first thing the operator sees. */
export function StationSelect() {
  const { data: stations, isLoading, isError } = useStations();
  const { setStation } = useAppState();
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    if (!stations) return [];
    const q = query.toLowerCase();
    return stations.filter((s) => s.name.toLowerCase().includes(q));
  }, [stations, query]);

  return (
    <div className="station-screen">
      <div className="station-screen-bg" />
      <div className="station-screen-content">
        <div className="brand-block">
          <div className="brand-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 22s-8-4.5-8-11.8A8 8 0 0 1 12 2a8 8 0 0 1 8 8.2c0 7.3-8 11.8-8 11.8z" />
              <circle cx="12" cy="10" r="3" />
            </svg>
          </div>
          <h1 className="brand-title">ParkVisionSaathi</h1>
          <p className="brand-subtitle">Patrol Operations Dashboard</p>
        </div>

        <div className="select-card">
          <div className="select-card-header">
            <h2>Select Your Station</h2>
            <p>Choose your police station to view jurisdiction data</p>
          </div>
          <div className="select-search-wrap">
            <svg className="select-search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <input
              className="select-search"
              placeholder="Search by station name..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoComplete="off"
            />
          </div>

          <div className="select-list">
            {isLoading && <SkeletonList count={5} />}
            {isError && (
              <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
                <p style={{ fontSize: 14, marginBottom: 8 }}>Could not load stations</p>
                <p style={{ fontSize: 12 }}>Check that the API is running on port 8000</p>
              </div>
            )}
            {!isLoading && !isError && filtered.length === 0 && (
              <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                No stations match your search
              </div>
            )}
            {filtered.map((s) => (
              <div key={s.name} className="station-item" onClick={() => setStation(s)}>
                <div className="station-item-left">
                  <div className="station-item-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M12 22s-8-4.5-8-11.8A8 8 0 0 1 12 2a8 8 0 0 1 8 8.2c0 7.3-8 11.8-8 11.8z" />
                      <circle cx="12" cy="10" r="3" />
                    </svg>
                  </div>
                  <div>
                    <div className="station-item-name">{s.name}</div>
                    <div className="station-item-meta">
                      {s.zone_count} zones · {fmt(s.total_violations)} violations
                    </div>
                  </div>
                </div>
                <svg className="station-item-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </div>
            ))}
          </div>
          <div className="select-footer">
            {stations ? `${stations.length} stations available` : 'Loading stations…'}
          </div>
        </div>
      </div>
    </div>
  );
}
