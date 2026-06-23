import { useState } from 'react';
import { usePriorityAreas } from '@/hooks/queries';
import { hourToBucket } from '@/api/endpoints';
import { useAppState } from '@/state/AppState';
import { useMapOverlay } from '@/state/MapOverlay';
import { cleanJunction } from '@/utils/format';
import { Skeleton } from './Skeleton';
import type { PriorityArea } from '@/types/api';

/** Human label for a CIS time bucket (matches backend TIME_BUCKET_BINS). */
const BUCKET_LABEL: Record<string, string> = {
  night: 'Night',
  morning_peak: 'Morning Peak',
  midday: 'Midday',
  afternoon: 'Afternoon',
  all_day: 'All-day',
};

/**
 * Collapsible bottom dock listing the station's priority areas (force units,
 * distance, ETA). Click a card to open its detail; "Route" draws a line on the map.
 */
export function PriorityDock() {
  const { station, hour, selectedZone, setSelectedZone, setPanel, setPanelOpen } = useAppState();
  const { setRouteTarget } = useMapOverlay();
  const { data, isLoading } = usePriorityAreas(station?.name ?? null, hour);
  const [open, setOpen] = useState(true);

  const pick = (a: PriorityArea) => {
    setSelectedZone(a);
    setPanel('details');
    setPanelOpen(true);
  };

  const count = data?.length ?? 0;
  const windowLabel = BUCKET_LABEL[hourToBucket(hour)] ?? 'All-day';

  return (
    <div className={`priority-dock ${open ? 'open' : 'collapsed'}`}>
      <button className="dock-handle" onClick={() => setOpen((v) => !v)}>
        <span className="dock-handle-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12h4l3 8 4-16 3 8h4" />
          </svg>
          Priority Areas
          {count > 0 && <span className="dock-count">{count}</span>}
          <span className="dock-window" title="Congestion ranking window (follows the hour)">{windowLabel}</span>
        </span>
        <span className="dock-chevron" aria-hidden>{open ? '▾' : '▴'}</span>
      </button>

      {open && (
        <div className="priority-cards">
          {isLoading && (
            <>
              <Skeleton height={92} style={{ flex: '0 0 210px' }} />
              <Skeleton height={92} style={{ flex: '0 0 210px' }} />
              <Skeleton height={92} style={{ flex: '0 0 210px' }} />
            </>
          )}
          {!isLoading && count === 0 && <div className="dock-empty">No priority areas for this shift</div>}
          {data?.map((a) => {
            const cls = a.priority.toLowerCase();
            const name = cleanJunction(a.top_junction) || a.station || a.h3_id;
            const selected = selectedZone?.h3_id === a.h3_id;
            return (
              <div key={a.h3_id} className={`priority-card ${selected ? 'selected' : ''}`} onClick={() => pick(a)}>
                <div className="card-top">
                  <span className="card-area-name" title={name}>{name}</span>
                  <span className={`priority-badge ${cls}`}>{a.priority}</span>
                </div>
                <div className="card-scores">
                  <span className="card-score-pill" title={`Congestion impact · ${windowLabel} window`}>
                    CIS {a.congestion_impact.toFixed(0)}
                  </span>
                  <span className="card-score-pill alt" title="Enforcement priority · all-day">
                    Risk {a.risk_score.toFixed(0)}
                  </span>
                </div>
                <div className="card-meta">
                  <span className="card-meta-item">{a.force_needed} units</span>
                  <span className="card-meta-item">{a.distance_km} km</span>
                  <span className="card-meta-item">{a.eta_minutes} min</span>
                </div>
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
            );
          })}
        </div>
      )}
    </div>
  );
}
