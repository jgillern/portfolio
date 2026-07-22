import { formatMoney, formatPercent } from "@/lib/format";
import type { Exposure } from "@/lib/types";

import { StatusBadge } from "./StatusBadge";

export function ExposureBars({
  exposures,
  currency,
}: {
  exposures: Exposure[];
  currency: string;
}): React.ReactNode {
  if (!exposures.length) {
    return <div className="empty-state">Expozice pro zvolený pohled není dostupná.</div>;
  }
  return (
    <div className="exposure-bars">
      {exposures.map((item) => (
        <div className="exposure-row" key={item.dimension + item.key + item.source}>
          <div className="exposure-heading">
            <strong>{item.label}</strong>
            <span>{formatPercent(item.weight)} · {formatMoney(item.value, currency)}</span>
          </div>
          <div className="bar-track" aria-label={item.label + " " + formatPercent(item.weight)}>
            <span
              className={"bar-fill bar-" + item.source}
              style={{ width: Math.min(Number(item.weight) * 100, 100) + "%" }}
            />
          </div>
          <div className="exposure-meta">
            <StatusBadge value={item.source === "unknown" ? "missing" : item.source} />
            <span>Pokrytí {formatPercent(item.coverage)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
