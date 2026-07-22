import type { Metadata } from "next";

import { ExposureBars } from "@/components/ExposureBars";
import { FilterBar } from "@/components/FilterBar";
import { PageHeader } from "@/components/PageHeader";
import { filtersFromRecord } from "@/lib/filters";
import { formatPercent } from "@/lib/format";
import { getAccounts, getBrokers, getExposures } from "@/lib/read-model";
import type { Exposure } from "@/lib/types";

export const metadata: Metadata = { title: "Expozice" };
type Search = Record<string, string | string[] | undefined>;

const sections: Array<{ key: Exposure["dimension"]; title: string; description: string }> = [
  { key: "asset_class", title: "Třídy aktiv", description: "Skutečná ekonomická expozice, nikoli právní obal." },
  { key: "geography", title: "Geografie", description: "Klasifikace zdroje včetně look-through fondů." },
  { key: "sector", title: "Sektory", description: "Známé podkladové pozice a nepokrytý zbytek." },
  { key: "currency", title: "Měnová expozice", description: "Ekonomická měna se může lišit od obchodní měny." },
  { key: "underlying", title: "Podkladové pozice", description: "Přímé a efektivní držení stejného emitenta dohromady." },
];

export default async function ExposuresPage({
  searchParams,
}: {
  searchParams: Promise<Search>;
}): Promise<React.ReactNode> {
  const filters = filtersFromRecord(await searchParams);
  const [exposures, accounts, brokers] = await Promise.all([
    getExposures(filters),
    getAccounts(),
    getBrokers(),
  ]);
  const coverage = exposures.length
    ? Math.min(...exposures.map((item) => Number(item.coverage)))
    : 0;

  return (
    <>
      <PageHeader
        eyebrow="Ekonomický pohled"
        title="Expozice"
        description="Přímé držení, look-through fondů a explicitní Unknown bez dopočítávání chybějících dat."
        aside={<div className="headline-number"><span>Min. pokrytí</span><strong>{formatPercent(String(coverage))}</strong></div>}
      />
      <FilterBar accounts={accounts} brokers={brokers} filters={filters} pathname="/exposures" />
      <div className="exposure-grid">
        {sections.map((section) => {
          const rows = exposures.filter((item) => item.dimension === section.key);
          return (
            <section className="panel" key={section.key}>
              <div className="panel-heading">
                <div><p className="eyebrow">{section.key.replace("_", " ")}</p><h2>{section.title}</h2></div>
              </div>
              <p className="panel-copy">{section.description}</p>
              <ExposureBars currency={filters.reporting_currency} exposures={rows} />
            </section>
          );
        })}
      </div>
    </>
  );
}
