import { useForecastTopZones, useForecastAccuracy } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';
import { Skeleton } from '../Skeleton';
import { bandColor } from '@/utils/risk';

/** Forecast view — tomorrow's predicted hotspots + honest held-out accuracy. */
export function ForecastPanel() {
  const { station } = useAppState();
  const top = useForecastTopZones(0, !!station);
  const acc = useForecastAccuracy();
  const a = acc.data;

  const maxPred = top.data?.reduce((m, p) => Math.max(m, p.predicted_count), 0) || 1;

  return (
    <div className="forecast-container">
      <h3 className="panel-h">Forecast — Tomorrow's Hotspots</h3>
      <p className="panel-sub">
        {a?.model ?? 'LightGBM'} predicts next-day violation volume per H3 zone.
        {a?.is_proxy && <span className="proxy-tag"> proxy</span>}
      </p>

      {a && (
        <>
          <div className="forecast-accuracy">
            <div className="acc-metric acc-hero">
              <div className="acc-value">{a.precision_at_10 != null ? `${Math.round(a.precision_at_10 * 100)}%` : '—'}</div>
              <div className="acc-label">Precision@10</div>
            </div>
            <div className="acc-metric">
              <div className="acc-value">{a.mae?.toFixed(2) ?? '—'}</div>
              <div className="acc-label">MAE</div>
            </div>
            <div className="acc-metric">
              <div className="acc-value">{a.rmse?.toFixed(2) ?? '—'}</div>
              <div className="acc-label">RMSE</div>
            </div>
          </div>
          {a.summary && <p className="acc-summary">{a.summary}</p>}
        </>
      )}

      <div className="detail-section-title" style={{ margin: '14px 16px 6px' }}>Predicted Top Zones</div>
      {top.isLoading && (
        <div style={{ padding: '0 16px' }}>
          <Skeleton height={34} /> <Skeleton height={34} /> <Skeleton height={34} />
        </div>
      )}
      {!top.isLoading && top.data?.length === 0 && <p className="panel-sub">No forecast available.</p>}
      <div className="forecast-list">
        {top.data?.map((p, i) => (
          <div key={p.h3_id} className="forecast-row">
            <span className="forecast-rank">#{i + 1}</span>
            <span className="forecast-id" title={p.h3_id}>{p.h3_id}</span>
            <div className="forecast-bar-track">
              <div
                className="forecast-bar-fill"
                style={{ width: `${(p.predicted_count / maxPred) * 100}%`, background: bandColor(p.predicted_band) }}
              />
            </div>
            <span className="forecast-val">{p.predicted_count.toFixed(1)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
