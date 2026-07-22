import type { PerformancePoint } from "@/lib/types";

const WIDTH = 760;
const HEIGHT = 300;
const PAD_X = 34;
const PAD_Y = 28;

const series = [
  { key: "portfolio", label: "Portfolio · TWR", color: "#163d2c" },
  { key: "SP500", label: "S&P 500 proxy", color: "#dd6f3a" },
  { key: "MSCI_WORLD", label: "MSCI World proxy", color: "#5578a8" },
  { key: "MSCI_ACWI", label: "MSCI ACWI proxy", color: "#8f69a8" },
] as const;

function value(point: PerformancePoint, key: (typeof series)[number]["key"]): number | null {
  const raw = key === "portfolio" ? point.portfolio : point.benchmarks[key];
  if (raw === null || raw === undefined) return null;
  const parsed = Number(raw) * 100;
  return Number.isFinite(parsed) ? parsed : null;
}

export function PerformanceChart({ points }: { points: PerformancePoint[] }): React.ReactNode {
  const visible = series.filter((item) => points.some((point) => value(point, item.key) !== null));
  const values = visible.flatMap((item) =>
    points.map((point) => value(point, item.key)).filter((item): item is number => item !== null),
  );
  if (!points.length || !values.length) {
    return <div className="empty-state">Pro zvolené období není dostupná výkonnostní řada.</div>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(max - min, 1);
  const x = (index: number) =>
    PAD_X + (index / Math.max(points.length - 1, 1)) * (WIDTH - PAD_X * 2);
  const y = (amount: number) =>
    HEIGHT - PAD_Y - ((amount - min) / spread) * (HEIGHT - PAD_Y * 2);

  return (
    <div className="chart-wrap">
      <svg
        className="performance-chart"
        role="img"
        viewBox={"0 0 " + WIDTH + " " + HEIGHT}
        aria-label="Normalizovaná výkonnost portfolia a ETF proxy benchmarků"
      >
        {[0, 0.25, 0.5, 0.75, 1].map((step) => {
          const amount = min + spread * step;
          const gridY = y(amount);
          return (
            <g key={step}>
              <line x1={PAD_X} x2={WIDTH - PAD_X} y1={gridY} y2={gridY} className="chart-grid" />
              <text x={0} y={gridY + 4} className="chart-axis">{amount.toFixed(0)}</text>
            </g>
          );
        })}
        {visible.map((item) => {
          const coordinates = points
            .map((point, index) => {
              const amount = value(point, item.key);
              return amount === null ? null : x(index) + "," + y(amount);
            })
            .filter(Boolean)
            .join(" ");
          return (
            <polyline
              fill="none"
              key={item.key}
              points={coordinates}
              stroke={item.color}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={item.key === "portfolio" ? 3 : 2}
            />
          );
        })}
        <text x={PAD_X} y={HEIGHT - 5} className="chart-axis">{points[0]?.date}</text>
        <text x={WIDTH - PAD_X} y={HEIGHT - 5} textAnchor="end" className="chart-axis">
          {points.at(-1)?.date}
        </text>
      </svg>
      <div className="chart-legend">
        {visible.map((item) => (
          <span key={item.key}>
            <i style={{ background: item.color }} />
            {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}
