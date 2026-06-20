import { useAppState } from '@/state/AppState';
import { LAYER_META } from '@/utils/risk';
import type { MapLayer } from '@/types/api';

/**
 * THEME-CRITICAL two-layer toggle. Switching between "Violation Density" and
 * "Congestion Risk" shows two visually different heatmaps — the core judging
 * moment. Spillover is a third operational layer.
 */
const LAYERS: MapLayer[] = ['violation_density', 'congestion_risk', 'spillover'];

export function LayerToggle() {
  const { layer, setLayer } = useAppState();
  return (
    <div className="map-controls">
      <div className="layer-toggle">
        {LAYERS.map((l) => (
          <button
            key={l}
            className={`layer-btn ${layer === l ? 'active' : ''}`}
            onClick={() => setLayer(l)}
          >
            {LAYER_META[l].title}
            <span className="layer-sub">{LAYER_META[l].sub}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
