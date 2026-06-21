import { useAppState } from '@/state/AppState';
import { LAYER_META } from '@/utils/risk';
import type { MapLayer } from '@/types/api';

/**
 * THEME-CRITICAL layer switch. Toggling "Violation Density" vs "Congestion Risk"
 * shows two visually different heatmaps — the core judging moment. Spillover is a
 * third operational layer. Rendered as a floating segmented control.
 */
const LAYERS: MapLayer[] = ['violation_density', 'congestion_risk', 'spillover'];

export function LayerToggle() {
  const { layer, setLayer } = useAppState();
  return (
    <div className="layer-seg">
      {LAYERS.map((l) => (
        <button
          key={l}
          className={`layer-seg-btn ${layer === l ? 'active' : ''}`}
          onClick={() => setLayer(l)}
          title={LAYER_META[l].sub}
        >
          <span className="layer-seg-title">{LAYER_META[l].title}</span>
          <span className="layer-seg-sub">{LAYER_META[l].sub}</span>
        </button>
      ))}
    </div>
  );
}
