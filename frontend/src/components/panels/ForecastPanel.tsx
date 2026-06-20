import { useForecastTopZones, useForecastAccuracy } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';
import { Skeleton } from '../Skeleton';

/** Forecast view — tomorrow's predicted hotspots + model accuracy badge. */
export function ForecastPanel() {
  const { hour, station } = useAppState();
  const top = useForecastTopZones(hour, !!station);
  const acc = useForecastAccuracy();

  const maxPred = top.data?.reduce((m, p) => Math.max(m, p.predicted_count), 0) ?? 1;

  return (
    <div className="forecast-container">
      <h3 className="panel-h">Forecast — Predicted Hotspots</h3>
      <p className="panel-sub">LightGBM-predicted violation counts for hour {hour}:00.</p>

      {acc.data && (
        <div className="forecast-accuracy">
          <div className="acc-metric">
            <div className="acc-value">{acc.data.mae?.toFixed(2)}</div>
            <div className="acc-label">MAE</div>
          </div>
          <div className="acc-metric">
            <div className="acc-value">{acc.data.rmse?.toFixed(2)}</div>
            <div className="acc-label">RMSE</div>
          </div>
          <div className="acc-metric">
            <div className="acc-value">{acc.data.n_predictions?.toLocaleString()}</div>
            <div className="acc-label">Predictions</div>
          </div>
        </div>
      )}

      <div className="detail-section-title" style={{ marginTop: 12 }}>Tomorrow's Top Zones</div>
      {top.isLoading && (
        <>
          <Skeleton height={40} /> <Skeleton height={40} /> <Skeleton height={40} />
        </>
      )}
      {top.data?.length === 0 && <p className="panel-sub">No forecast available for this hour.</p>}
      <div className="forecast-list">
        {top.data?.map((p, i) => (
          <div key={p.h3_id} className="forecast-row">
            <span className="forecast-rank">#{i + 1}</span>
            <span className="forecast-id">{p.h3_id}</span>
            <div className="forecast-bar-track">
              <div className="forecast-bar-fill" style={{ width: `${(p.predicted_count / maxPred) * 100}%` }} />
            </div>
            <span className="forecast-val">{p.predicted_count.toFixed(1)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
