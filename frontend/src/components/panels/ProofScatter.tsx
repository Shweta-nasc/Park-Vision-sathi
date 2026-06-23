import { useValidationProof } from '@/hooks/queries';
import type { ProofPoint, SpearmanCI, ValidationProof } from '@/types/api';

/**
 * The "density ≠ impact" proof (Task 13).
 *
 * Two lightweight inline-SVG scatter plots (no charting dependency) of the
 * held-out test zones, both against the measured MapMyIndia travel-time ratio:
 *
 *   • Honest CIS (4 violation/road components, NO traffic signal) vs ratio
 *   • Raw violation count ("density") vs ratio
 *
 * Each carries its Spearman ρ with a bootstrap CI. The headline states whether
 * the honest CIS beats the raw-count baseline — i.e. whether congestion impact
 * is genuinely more than violation density. Until a live peak-time MapMyIndia
 * collection has been validated, the panel shows a graceful pending state (never
 * fabricated numbers).
 */

const ACCENT = '#2563eb'; // honest CIS / test points
const COUNT_COLOR = '#9333ea'; // raw-count plot
const EXPLORE = '#f59e0b'; // exploration zones

const fmtRho = (v?: number | null): string => (v == null ? '—' : v.toFixed(2));

function ciLabel(ci?: SpearmanCI | null): string {
  if (!ci || ci.lo == null || ci.hi == null) return '';
  return ` [${ci.lo.toFixed(2)}, ${ci.hi.toFixed(2)}]`;
}

interface PlotPoint {
  x: number;
  y: number;
  test: boolean;
  explore: boolean;
}

interface ScatterProps {
  title: string;
  xLabel: string;
  rho?: number | null;
  ci?: SpearmanCI | null;
  pts: PlotPoint[];
  color: string;
}

function Scatter({ title, xLabel, rho, ci, pts, color }: ScatterProps) {
  const W = 240;
  const H = 168;
  const P = 26;

  let body: JSX.Element;
  if (pts.length === 0) {
    body = (
      <p className="panel-sub" style={{ margin: '4px 0 0' }}>
        No measured zones yet.
      </p>
    );
  } else {
    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const yMin = Math.min(...ys);
    const yMax = Math.max(...ys);
    const sx = (x: number) => P + ((x - xMin) / (xMax - xMin || 1)) * (W - 2 * P);
    const sy = (y: number) => H - P - ((y - yMin) / (yMax - yMin || 1)) * (H - 2 * P);

    body = (
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={`${title}: Spearman rho ${fmtRho(rho)} on ${pts.length} zones`}
        style={{ display: 'block' }}
      >
        {/* axes */}
        <line x1={P} y1={H - P} x2={W - 4} y2={H - P} stroke="#d1d5db" strokeWidth={1} />
        <line x1={P} y1={6} x2={P} y2={H - P} stroke="#d1d5db" strokeWidth={1} />
        {pts.map((p, i) => {
          const cx = sx(p.x);
          const cy = sy(p.y);
          if (p.explore) {
            return (
              <circle key={i} cx={cx} cy={cy} r={4} fill="none" stroke={EXPLORE} strokeWidth={1.6} />
            );
          }
          return (
            <circle
              key={i}
              cx={cx}
              cy={cy}
              r={3.2}
              fill={p.test ? color : '#cbd5e1'}
              opacity={p.test ? 0.92 : 0.65}
            />
          );
        })}
        <text x={W / 2} y={H - 4} textAnchor="middle" fontSize={9} fill="#6b7280">
          {xLabel}
        </text>
        <text x={5} y={14} fontSize={9} fill="#6b7280">
          ratio
        </text>
      </svg>
    );
  }

  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#374151' }}>{title}</div>
      <div style={{ fontSize: 11, color: color, fontVariantNumeric: 'tabular-nums' }}>
        ρ = {fmtRho(rho)}
        <span style={{ color: '#9ca3af' }}>{ciLabel(ci)}</span>
      </div>
      {body}
    </div>
  );
}

const STRENGTH_META: Record<string, { label: string; color: string }> = {
  strong: { label: 'STRONG', color: '#10b981' },
  weak: { label: 'WEAK', color: '#f59e0b' },
  aborted: { label: 'ABORTED', color: '#6b7280' },
};

function toPlotPoints(d: ValidationProof, accessor: (p: ProofPoint) => number | null): PlotPoint[] {
  const out: PlotPoint[] = [];
  for (const p of d.points) {
    const x = accessor(p);
    if (x == null || !Number.isFinite(x) || !Number.isFinite(p.measured_ratio)) continue;
    out.push({
      x,
      y: p.measured_ratio,
      test: p.split === 'test',
      explore: !!p.is_exploration,
    });
  }
  return out;
}

export function ProofScatter({ enabled = true }: { enabled?: boolean }) {
  const q = useValidationProof(enabled);
  const d = q.data;

  const pending = !d || !d.available || d.points.length === 0;

  return (
    <div style={{ margin: '12px 16px' }}>
      <div className="detail-section-title" style={{ marginBottom: 6 }}>
        Density ≠ Impact (validated)
      </div>

      {q.isLoading && (
        <p className="panel-sub" style={{ margin: 0 }}>
          Loading validation proof…
        </p>
      )}

      {!q.isLoading && pending && (
        <p className="panel-sub" style={{ margin: 0 }}>
          The proof is pending a live peak-time MapMyIndia collection. Once real
          congestion is measured, this shows whether the Congestion Impact Score
          tracks actual traffic better than raw violation counts — on held-out
          zones, with confidence intervals.
        </p>
      )}

      {!q.isLoading && !pending && d && (
        <>
          <p className="panel-sub" style={{ margin: '0 0 8px' }}>
            {d.baseline_beaten ? (
              <strong style={{ color: '#10b981' }}>PROVEN</strong>
            ) : (
              <strong style={{ color: '#f59e0b' }}>NOT YET</strong>
            )}{' '}
            on {d.n_proof ?? d.points.length} held-out zones: the honest CIS
            (violation/road components, no traffic signal) vs the raw-count
            baseline, both against measured travel-time ratio.
            {d.calibration_strength && STRENGTH_META[d.calibration_strength] && (
              <span
                style={{
                  marginLeft: 6,
                  padding: '1px 6px',
                  borderRadius: 4,
                  fontSize: 10,
                  fontWeight: 700,
                  color: '#fff',
                  background: STRENGTH_META[d.calibration_strength].color,
                }}
              >
                {STRENGTH_META[d.calibration_strength].label}
              </span>
            )}
          </p>

          <div style={{ display: 'flex', gap: 12 }}>
            <Scatter
              title="Honest CIS"
              xLabel="CIS (non-traffic)"
              rho={d.spearman_cis_honest}
              ci={d.spearman_cis_honest_ci}
              pts={toPlotPoints(d, (p) => p.cis_honest)}
              color={ACCENT}
            />
            <Scatter
              title="Raw violation count"
              xLabel="violations (density)"
              rho={d.spearman_count}
              ci={d.spearman_count_ci}
              pts={toPlotPoints(d, (p) => p.count)}
              color={COUNT_COLOR}
            />
          </div>

          <p className="panel-sub" style={{ margin: '6px 0 0', fontSize: 11 }}>
            Solid = held-out test zones · faded = train · ringed = exploration
            zones. Full CIS ρ={fmtRho(d.spearman_cis_full)} is shown only as a
            circular upper bound (it contains the measured ratio) and is not the
            trust metric.
          </p>
        </>
      )}
    </div>
  );
}
