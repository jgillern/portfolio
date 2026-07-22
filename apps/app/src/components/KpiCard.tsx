import Link from "next/link";

import { StatusBadge } from "./StatusBadge";

type Props = {
  label: string;
  value: string;
  detail: string;
  tone?: "default" | "positive" | "negative";
  quality?: string;
};

export function KpiCard({
  label,
  value,
  detail,
  tone = "default",
  quality,
}: Props): React.ReactNode {
  return (
    <article className="kpi-card">
      <div className="kpi-label">
        <span>{label}</span>
        <Link href="/methodology" title={"Definice: " + label} aria-label={"Metodika: " + label}>
          ?
        </Link>
      </div>
      <strong className={"kpi-value " + tone}>{value}</strong>
      <div className="kpi-detail">
        <span>{detail}</span>
        {quality ? <StatusBadge value={quality} /> : null}
      </div>
    </article>
  );
}
