import type { Metadata } from "next";

import { FilterBar } from "@/components/FilterBar";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { filtersFromRecord } from "@/lib/filters";
import { formatDate, formatMoney } from "@/lib/format";
import { getAccounts, getBrokers, getTransactions } from "@/lib/read-model";

export const metadata: Metadata = { title: "Transakce" };
type Search = Record<string, string | string[] | undefined>;

export default async function TransactionsPage({
  searchParams,
}: {
  searchParams: Promise<Search>;
}): Promise<React.ReactNode> {
  const filters = filtersFromRecord(await searchParams);
  const [transactions, accounts, brokers] = await Promise.all([
    getTransactions(filters),
    getAccounts(),
    getBrokers(),
  ]);

  return (
    <>
      <PageHeader
        eyebrow="Canonical ledger"
        title="Transakce"
        description="Neměnná auditní historie obchodů, cash flow, příjmů, poplatků a daní."
        aside={<div className="headline-number"><span>Záznamů</span><strong>{transactions.length}</strong></div>}
      />
      <FilterBar accounts={accounts} brokers={brokers} filters={filters} pathname="/transactions" />
      <section className="panel table-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Události</p><h2>Časová osa</h2></div>
          <span className="table-note">Opravy se účtují reverzní událostí</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Datum</th><th>Typ</th><th>Instrument</th><th>Množství</th><th>Hrubá částka</th><th>Poplatek</th><th>Daň</th><th>Zdroj</th></tr></thead>
            <tbody>
              {transactions.map((item) => (
                <tr key={item.id}>
                  <td><strong>{formatDate(item.occurred_at)}</strong><small>{item.broker} · {item.account}</small></td>
                  <td><span className={"event-pill event-" + item.event_type.toLowerCase()}>{item.event_type}</span></td>
                  <td><strong>{item.instrument_name ?? "—"}</strong><small>{item.isin ?? item.tax_wrapper}</small></td>
                  <td className="numeric">{item.quantity_delta ? Number(item.quantity_delta).toLocaleString("cs-CZ", { maximumFractionDigits: 6 }) : "—"}</td>
                  <td className="numeric emph">{formatMoney(item.gross_amount, item.currency ?? filters.reporting_currency, 2)}</td>
                  <td className="numeric">{formatMoney(item.fee_amount, item.currency ?? filters.reporting_currency, 2)}</td>
                  <td className="numeric">{formatMoney(item.tax_amount, item.currency ?? filters.reporting_currency, 2)}</td>
                  <td><StatusBadge value={item.source_status === "RECONCILED" ? "verified" : "partial"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!transactions.length ? <div className="empty-state">Zvolenému období neodpovídá žádná transakce.</div> : null}
        </div>
      </section>
    </>
  );
}
