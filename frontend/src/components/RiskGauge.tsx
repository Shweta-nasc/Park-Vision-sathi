import { scoreColor } from '@/utils/risk';

/** Circular 0-100 congestion-impact gauge (planner Sprint 12 requirement). */
export function RiskGauge({ score, size = 96 }: { score: number; size?: number }) {
  const r = size / 2 - 8;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - Math.min(Math.max(score, 0), 100) / 100);
  const color = scoreColor(score);
  const c = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="risk-gauge">
      <circle cx={c} cy={c} r={r} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth={8} />
      <circle
        cx={c}
        cy={c}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={8}
        strokeDasharray={circ}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform={`rotate(-90 ${c} ${c})`}
        style={{ transition: 'stroke-dashoffset 0.6s ease' }}
      />
      <text x={c} y={c + 2} textAnchor="middle" fill={color} fontSize={size * 0.26} fontWeight={800} fontFamily="Inter">
        {score.toFixed(0)}
      </text>
      <text x={c} y={c + size * 0.18} textAnchor="middle" fill="var(--text-muted)" fontSize={size * 0.1} fontFamily="Inter">
        / 100
      </text>
    </svg>
  );
}
