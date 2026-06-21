import { usePriorityAreas } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';
import { useMapOverlay } from '@/state/MapOverlay';
import { cleanJunction } from '@/utils/format';
import { Skeleton } from './Skeleton';
import type { PriorityArea } from '@/types/api';

export function PriorityStrip() {
  const { station, hour, selectedZone, setSelectedZone, setPanel, setPanelOpen } = useAppState();
  const { setRouteTarget } = useMapOverlay();
  const { data, isLoading } = usePriorityAreas(station?.name ?? null, hour);

  const pick = (a: PriorityArea) => {
    setSelectedZone(a);
    setPanel('details');
    setPanelOpen(true);
  };

  return (
    <div className="priority-strip">
      <div className="strip-header">
        <h3>Priority Areas</h3>
        <span className="strip-subtitle">{station ? `Under ${station.name}` : ''}</span>
      </div>
      <div className="priority-cards">
        {isLoading && (
          <>
            <Skeleton height={96} style={{ flex: '0 0 210px' }} />
            <Skeleton height={96} style={{ flex: '0 0 210px' }} />
            <Skeleton height={96} style={{ flex: '0 0 210px' }} />
          </>
        )}
        {!isLoading && data?.length === 0 && (
          <div style={{ padding: 16, color: 'var(--text-muted)', fontSize: 12 }}>
            No priority areas for this shift
          </div>
        )}
        {data?.map((a) => {
          const cls = a.priority.toLowerCase();
          const name = cleanJunction(a.top_junction) || a.h3_id;
          const selected = selectedZone?.h3_id === a.h3_id;
          return (
            <div
              key={a.h3_id}
              className={`priority-card ${selected ? 'selected' : ''}`}
              onClick={() => pick(a)}
            >
              <div className="card-top">
                <span className="card-area-name" title={name}>
                  {name}
                </span>
                <span className={`priority-badge ${cls}`}>{a.priority}</span>
              </div>
              <div className="card-meta">
                <span className="card-meta-item">👮 {a.force_needed} units</span>
                <span className="card-meta-item">📍 {a.distance_km} km</span>
                <span className="card-meta-item">⏱ {a.eta_minutes}m</span>
              </div>
              <div className="card-actions">
                <button
                  className="card-route-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    pick(a);
                    setRouteTarget(a);
                  }}
                >
                  Route now →
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
