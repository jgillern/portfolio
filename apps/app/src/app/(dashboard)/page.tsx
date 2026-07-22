import type { Metadata } from "next";
import Link from "next/link";

import { ExposureBars } from "@/components/ExposureBars";
import { FilterBar } from "@/components/FilterBar";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { PerformanceChart } from "@/components/PerformanceChart";
import { StatusBadge } from "@/components/StatusBadge";
import { filtersFromRecord } from "@/lib/filters";
import { formatDate, formatDateTime, formatMoney, formatPercent } from "@/lib/format";
import {
  getAccounts,
  getBrokers,
  getDataQualityIssues,
  getExposures,
  getImportStatus,
  getIncomeCosts,
  getPerformance,
  getSummary,
  getTransactions,
} from "@/lib/read-model";

export const metadata: Metadata = { title: "Přehled" };

type Search = Record<string, string | string[] | undefined>;

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<Search>;
}): Promise<React.ReactNode> {
  const filters = filtersFromRecord(await searchParams);
  const [
    summary,
    performance,
    exposures,
    transactions,
    imports,
    issues,
    accounts,
    brokers,
    income,
  ] = await Promise.all([
    getSummary(filters),
    getPerformance(filters),
    getExposures(filters, "asset_class"),
    getTransactions(filters),
    getImportStatus(),
    getDataQualityIssues(),
    getAccounts(),
    getBrokers(),
    getIncomeCosts(filters),
  ]);
  const currency = summary.meta.currency;
  const healthy = imports.filter((item) => item.status === "healthy").length;

  return (
    <>
      <PageHeader
        eyebrow="Celé portfolio"
        title="Přehled majetku"
        description="Výkon, peněžní toky a ekonomická expozice napříč všemi účty."
        aside={
          <div className="freshness">
            <span>Ocenění k</span>
            <strong>{formatDateTime(summary.meta.as_of)}</strong>
            <StatusBadge value={summary.meta.data_freshness} />
          </div>
        }
      />
      <FilterBar accounts={accounts} brokers={brokers} filters={filters} pathname="/" />

      <section className="kpi-grid" aria-label="Klíčové ukazatele">
        <KpiCard
          detail={"Ocenění " + formatDate(summary.meta.as_of)}
          label="Tržní hodnota"
          quality={summary.meta.data_freshness}
          value={formatMoney(summary.market_value, currency)}
        />
        <KpiCard
          detail="Vklady minus výběry"
          label="Čisté externí vklady"
          value={formatMoney(summary.net_external_flows, currency)}
        />
        <KpiCard
          detail="Hodnota + výběry − vklady"
          label="Absolutní výsledek"
          tone={Number(summary.absolute_result) >= 0 ? "positive" : "negative"}
          value={formatMoney(summary.absolute_result, currency)}
        />
        <KpiCard
          detail="Časově vážený výnos"
          label="TWR"
          tone={Number(summary.twr ?? 0) >= 0 ? "positive" : "negative"}
          value={formatPercent(summary.twr, true)}
        />
        <KpiCard
          detail="Osobní výnos včetně načasování vkladů"
          label="XIRR"
          tone={Number(summary.xirr ?? 0) >= 0 ? "positive" : "negative"}
          value={formatPercent(summary.xirr, true)}
        />
        <KpiCard
          detail={"Dividendy a úroky " + formatMoney(String(Number(income.dividends) + Number(income.interest)), currency)}
          label="Náklady"
          tone="negative"
          value={formatMoney(String(Number(income.fees) + Number(income.taxes)), currency)}
        />
      </section>

      <section className="dashboard-grid">
        <article className="panel panel-wide">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Výkonnost</p>
              <h2>Portfolio vs. ETF proxy</h2>
            </div>
            <Link href="/methodology#benchmarks">Jak srovnání počítáme</Link>
          </div>
          <PerformanceChart points={performance} />
        </article>

        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Alokace</p>
              <h2>Třídy aktiv</h2>
            </div>
            <Link href="/exposures">Detail</Link>
          </div>
          <ExposureBars currency={currency} exposures={exposures} />
        </article>
      </section>

      <section className="dashboard-grid bottom-grid">
        <article className="panel panel-wide">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Ledger</p>
              <h2>Poslední transakce</h2>
            </div>
            <Link href="/transactions">Celá historie</Link>
          </div>
          <div className="compact-list">
            {transactions.slice(0, 5).map((transaction) => (
              <div className="transaction-row" key={transaction.id}>
                <span className={"event-icon event-" + transaction.event_type.toLowerCase()}>
                  {transaction.event_type === "BUY" ? "↓" : transaction.event_type === "SELL" ? "↑" : "·"}
                </span>
                <div>
                  <strong>{transaction.instrument_name ?? transaction.event_type}</strong>
                  <span>{transaction.broker} · {transaction.account}</span>
                </div>
                <div className="transaction-amount">
                  <strong>{formatMoney(transaction.gross_amount, transaction.currency ?? currency, 2)}</strong>
                  <span>{formatDate(transaction.occurred_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="panel health-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Kvalita dat</p>
              <h2>{healthy}/{imports.length} zdrojů aktuálních</h2>
            </div>
            <Link href="/sources">Diagnostika</Link>
          </div>
          <div className="health-meter">
            <span style={{ width: imports.length ? (healthy / imports.length) * 100 + "%" : "0%" }} />
          </div>
          <ul className="health-list">
            {imports.slice(0, 4).map((item) => (
              <li key={item.connector}>
                <span>{item.connector.replaceAll("_", " ")}</span>
                <StatusBadge value={item.status} />
              </li>
            ))}
          </ul>
          {issues.length ? (
            <div className="issue-callout">
              <strong>{issues.length} otevřené upozornění</strong>
              <span>{issues[0]?.summary}</span>
            </div>
          ) : null}
        </article>
      </section>
    </>
  );
}
