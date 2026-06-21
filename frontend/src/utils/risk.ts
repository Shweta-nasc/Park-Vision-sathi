import type { ImpactBand, MapLayer, RiskLabel } from '@/types/api';

/** Color for a risk label (used by markers, badges). */
export function riskColor(label: RiskLabel): string {
  switch (label) {
    case 'CRITICAL':
      return '#B91C1C';
    case 'HIGH':
      return '#DC2626';
    case 'MEDIUM':
      return '#F59E0B';
    default:
      return '#059669';
  }
}

/** Color for a 0-100 score. */
export function scoreColor(score: number): string {
  if (score >= 80) return '#B91C1C';
  if (score >= 67) return '#DC2626';
  if (score >= 34) return '#F59E0B';
  return '#059669';
}

export function bandColor(band: ImpactBand): string {
  switch (band) {
    case 'CRITICAL':
      return '#B91C1C';
    case 'SEVERE':
      return '#DC2626';
    case 'MODERATE':
      return '#F59E0B';
    default:
      return '#059669';
  }
}

/** Heatmap gradient per layer — makes the two-layer toggle visually distinct. */
export const HEAT_GRADIENTS: Record<MapLayer, Record<number, string>> = {
  violation_density: { 0.0: '#1E3A8A', 0.4: '#2563EB', 0.7: '#60A5FA', 1.0: '#BFDBFE' },
  congestion_risk: { 0.0: '#059669', 0.4: '#F59E0B', 0.7: '#F97316', 1.0: '#DC2626' },
  spillover: { 0.0: '#06B6D4', 0.4: '#2A9D8F', 0.7: '#F59E0B', 1.0: '#DC2626' },
};

export const LAYER_META: Record<MapLayer, { title: string; sub: string }> = {
  violation_density: { title: 'Violation Density', sub: 'Where violations happen' },
  congestion_risk: { title: 'Congestion Risk', sub: 'Where violations choke traffic' },
  spillover: { title: 'Spillover', sub: 'Waterbed displacement' },
};
