import { useForecastTopZones, useForecastAccuracy, useZoneNames, useForecastExplanations } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';
import { Skeleton } from '../Skeleton';
import { bandColor } from '@/utils/risk';
import { shortId } from '@/utils/format';
import type { ForecastExplanationZone } from '@/types/api';

/** Forecast view — tomorrow's predicted hotspots + honest held-out accuracy. */
export function ForecastPanel() {
  const { station } = useAppState();
  const top = useForecastTopZones(0, !!station);
  const acc = useForecastAccuracy();
  const names = useZoneNames();
  const explain = useForecastExplanations(!!station);
  const nameFor = (id: string) => names.data?.get(id) ?? shortId(id);
  const a = acc.data;

  const maxPred = top.data?.reduce((m, p) => Math.max(m, p.predicted_count), 0) || 1;

  // SHAP: explanation for the top predicted zone (when the sidecar is available).
  const explByZone = new Map<string, ForecastExplanationZone>();
  for (const z of explain.data?.zones ?? []) {
    if (z.h3_id) explByZone.set(z.h3_id, z);
  }
  const topZoneId = top.data?.[0]?.h3_id;
  const topExpl = topZoneId ? explByZone.get(topZoneId) : undefined;
  const maxAbsContrib = topExpl
    ? topExpl.top_contributors.reduce((m, c) => Math.max(m, Math.abs(c.contribution)), 0) || 1
    : 1;

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
            <span className="forecast-id" title={p.h3_id}>{nameFor(p.h3_id)}</span>
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

      {/* Task 9: SHAP — why the #1 zone is predicted hot (when the sidecar exists). */}
      {topExpl && topExpl.top_contributors.length > 0 && (
        <>
          <div className="detail-section-title" style={{ margin: '14px 16px 6px' }}>
            Why “{topZoneId ? nameFor(topZoneId) : ''}”? (SHAP)
          </div>
          <div style={{ padding: '0 16px' }}>
            {topExpl.top_contributors.map((c) => {
              const up = c.contribution >= 0;
              const pct = (Math.abs(c.contribution) / maxAbsContrib) * 100;
              return (
                <div key={c.feature} style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '3px 0', fontSize: 12 }}>
                  <span style={{ width: 130, color: '#374151' }} title={`value ${c.value}`}>{c.feature}</span>
                  <div style={{ flex: 1, height: 10, background: '#f3f4f6', borderRadius: 3, position: 'relative' }}>
                    <div style={{
                      width: `${pct}%`, height: '100%', borderRadius: 3,
                      background: up ? '#dc2626' : '#2563eb',
                    }} />
                  </div>
                  <span style={{ width: 56, textAlign: 'right', color: up ? '#dc2626' : '#2563eb' }}>
                    {up ? '+' : ''}{c.contribution.toFixed(2)}
                  </span>
                </div>
              );
            })}
            <p className="panel-sub" style={{ margin: '6px 0 0' }}>
              Red pushes the predicted count up, blue pulls it down (TreeSHAP, raw-score space).
            </p>
          </div>
        </>
      )}

      {/* Task 9: honest-limitations note (always shown). */}
      <div className="detail-section-title" style={{ margin: '14px 16px 6px' }}>Honest Limitations</div>
      <p className="panel-sub" style={{ margin: '0 16px 12px' }}>
        Violation records are <strong>enforcement locations</strong> (where police recorded a
        violation), not ground-truth violations — so the model can inherit where patrols
        already look. We mitigate this with <strong>ε = 10% exploration</strong>: 10% of patrol
        effort is steered to under-observed zones to surface violations the record misses.
      </p>
    </div>
  );
}
