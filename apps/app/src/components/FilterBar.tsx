import Link from "next/link";

import type { PortfolioFilter } from "@portfolio/contracts";

import type { AccountSummary } from "@/lib/types";

type Broker = { id: string; code: string; name: string };

type Props = {
  filters: PortfolioFilter;
  accounts: AccountSummary[];
  brokers: Broker[];
  pathname: string;
};

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function periodHref(
  pathname: string,
  filters: PortfolioFilter,
  months: number | "ytd" | "max",
): string {
  const params = new URLSearchParams();
  if (filters.reporting_currency !== "CZK") params.set("reporting_currency", filters.reporting_currency);
  if (filters.broker_id) params.set("broker_id", filters.broker_id);
  if (filters.account_id) params.set("account_id", filters.account_id);
  if (filters.tax_wrapper) params.set("tax_wrapper", filters.tax_wrapper);
  filters.benchmark.forEach((item) => params.append("benchmark", item));

  if (months !== "max") {
    const to = filters.to ? new Date(filters.to + "T12:00:00Z") : new Date();
    const from = new Date(to);
    if (months === "ytd") from.setUTCMonth(0, 1);
    else from.setUTCMonth(from.getUTCMonth() - months);
    params.set("from", isoDate(from));
    params.set("to", isoDate(to));
  }
  const query = params.toString();
  return query ? pathname + "?" + query : pathname;
}

export function FilterBar({ filters, accounts, brokers, pathname }: Props): React.ReactNode {
  const chips = [
    filters.tax_wrapper === "DIP" ? "DIP" : filters.tax_wrapper === "STANDARD" ? "Klasické" : "Vše",
    filters.reporting_currency,
    filters.broker_id ? brokers.find((item) => item.id === filters.broker_id)?.name : null,
    filters.account_id ? accounts.find((item) => item.id === filters.account_id)?.name : null,
  ].filter(Boolean);

  return (
    <section className="filter-shell" aria-label="Globální filtry">
      <div className="period-tabs" aria-label="Období">
        {[
          ["1M", 1],
          ["3M", 3],
          ["YTD", "ytd"],
          ["1Y", 12],
          ["3Y", 36],
          ["5Y", 60],
          ["MAX", "max"],
        ].map(([label, value]) => (
          <Link href={periodHref(pathname, filters, value as number | "ytd" | "max")} key={label}>
            {label}
          </Link>
        ))}
      </div>

      <form action={pathname} className="filter-form" method="get">
        <label>
          <span>Od</span>
          <input defaultValue={filters.from ?? ""} name="from" type="date" />
        </label>
        <label>
          <span>Do</span>
          <input defaultValue={filters.to ?? ""} name="to" type="date" />
        </label>
        <label>
          <span>Režim</span>
          <select defaultValue={filters.tax_wrapper ?? ""} name="tax_wrapper">
            <option value="">Vše</option>
            <option value="DIP">DIP</option>
            <option value="STANDARD">Klasické</option>
          </select>
        </label>
        <label>
          <span>Broker</span>
          <select defaultValue={filters.broker_id ?? ""} name="broker_id">
            <option value="">Všichni</option>
            {brokers.map((broker) => (
              <option key={broker.id} value={broker.id}>{broker.name}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Účet</span>
          <select defaultValue={filters.account_id ?? ""} name="account_id">
            <option value="">Všechny</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name} · {account.broker}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Měna</span>
          <select defaultValue={filters.reporting_currency} name="reporting_currency">
            <option value="CZK">CZK</option>
            <option value="EUR">EUR</option>
          </select>
        </label>
        <fieldset className="benchmark-filter">
          <legend>ETF proxy</legend>
          {[
            ["SP500", "S&P 500"],
            ["MSCI_WORLD", "World"],
            ["MSCI_ACWI", "ACWI"],
          ].map(([value, label]) => (
            <label key={value}>
              <input
                defaultChecked={filters.benchmark.includes(value as "SP500" | "MSCI_WORLD" | "MSCI_ACWI")}
                name="benchmark"
                type="checkbox"
                value={value}
              />
              <span>{label}</span>
            </label>
          ))}
        </fieldset>
        <button className="filter-submit" type="submit">Použít</button>
      </form>

      <div className="active-filters" aria-label="Aktivní filtry">
        <span>Aktivní pohled</span>
        {chips.map((chip) => <strong key={chip}>{chip}</strong>)}
      </div>
    </section>
  );
}
