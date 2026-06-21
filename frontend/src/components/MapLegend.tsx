import { useAppState } from '@/state/AppState';
import { HEAT_GRADIENTS, LAYER_META } from '@/utils/risk';

/** Floating heatmap legend (bottom-left). Reflects the active layer's gradient. */
export function MapLegend() {
  const { layer } = useAppState();
  const grad = HEAT_GRADIENTS[layer];
  const css = `linear-gradient(90deg, ${Object.entries(grad)
    .map(([stop, color]) => `${color} ${Number(stop) * 100}%`)
    .join(', ')})`;

  const lowHigh =
    layer === 'violation_density'
      ? ['Fewer', 'More']
      : layer === 'spillover'
        ? ['Low', 'High']
        : ['Minimal', 'Critical'];

  return (
    <div className="map-legend">
      <div className="legend-title">{LAYER_META[layer].title}</div>
      <div className="legend-sub">{LAYER_META[layer].sub}</div>
      <div className="legend-bar" style={{ background: css }} />
      <div className="legend-scale">
        <span>{lowHigh[0]}</span>
        <span>{lowHigh[1]}</span>
      </div>
    </div>
  );
}
