import type { Metadata } from "next";

import { FilterBar } from "@/components/FilterBar";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { filtersFromRecord } from "@/lib/filters";
import { formatMoney, formatPercent } from "@/lib/format";
import { getAccounts, getBrokers, getHoldings, getSummary } from "@/lib/read-model";

export const metadata: Metadata = { title: "Pozice" };
type Search = Record<string, string | string[] | undefined>;

export default async function HoldingsPage({
  searchParams,
}: {
  searchParams: Promise<Search>;
}): Promise<React.ReactNode> {
  const filters = filtersFromRecord(await searchParams);
  const [holdings, summary, accounts, brokers] = await Promise.all([
    getHoldings(filters),
    getSummary(filters),
    getAccounts(),
    getBrokers(),
  ]);
  const currency = summary.meta.currency;

  return (
    <>
      <PageHeader
        eyebrow="Aktuální pozice"
        title="Holdings"
        description="Instrumenty agregované podle identity a ISIN; kvalita ocenění zůstává viditelná."
        aside={<div className="headline-number"><span>Celkem</span><strong>{formatMoney(summary.market_value, currency)}</strong></div>}
      />
      <FilterBar accounts={accounts} brokers={brokers} filters={filters} pathname="/holdings" />
      <section className="panel table-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Pozice</p><h2>{holdings.length} instrumentů</h2></div>
          <span className="table-note">Seřazeno podle tržní hodnoty</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Instrument</th><th>Množství</th><th>Cena</th><th>Tržní hodnota</th><th>Váha</th><th>Výsledek</th><th>Účet</th><th>Kvalita</th></tr></thead>
            <tbody>
              {holdings.map((holding) => (
                <tr key={holding.instrument_id + holding.account}>
                  <td><strong>{holding.name}</strong><small>{holding.isin ?? holding.ticker ?? "Bez identifikátoru"}</small></td>
                  <td className="numeric">{Number(holding.quantity).toLocaleString("cs-CZ", { maximumFractionDigits: 6 })}</td>
                  <td className="numeric">{formatMoney(holding.price, holding.price_currency ?? currency, 2)}</td>
                  <td className="numeric emph">{formatMoney(holding.market_value, currency)}</td>
                  <td className="numeric">{formatPercent(holding.portfolio_weight)}</td>
                  <td className={"numeric " + (Number(holding.unrealized_result ?? 0) >= 0 ? "positive" : "negative")}>{formatMoney(holding.unrealized_result, currency)}</td>
                  <td><strong>{holding.account}</strong><small>{holding.broker} · {holding.tax_wrapper}</small></td>
                  <td><StatusBadge value={holding.valuation_quality} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!holdings.length ? <div className="empty-state">Pro zvolené filtry nejsou žádné otevřené pozice.</div> : null}
        </div>
      </section>
    </>
  );
}
