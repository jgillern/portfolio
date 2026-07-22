import type { PortfolioFilter } from "@portfolio/contracts";

import { databaseEnabled, readDatabase } from "./db";
import {
  syntheticAccounts,
  syntheticExposures,
  syntheticHoldings,
  syntheticImportStatus,
  syntheticIncomeCosts,
  syntheticIssues,
  syntheticMethodology,
  syntheticPerformance,
  syntheticSummary,
  syntheticTransactions,
} from "./synthetic";
import type {
  AccountSummary,
  DataQualityIssue,
  Exposure,
  Holding,
  ImportStatus,
  IncomeCosts,
  Methodology,
  PerformancePoint,
  PortfolioSummary,
  Transaction,
} from "./types";

const iso = (value: unknown): string =>
  value instanceof Date ? value.toISOString() : String(value);
const decimal = (value: unknown, fallback = "0"): string =>
  value === null || value === undefined ? fallback : String(value);
const nullableDecimal = (value: unknown): string | null =>
  value === null || value === undefined ? null : String(value);

function holdingMatches(holding: Holding, filter: PortfolioFilter): boolean {
  if (filter.account_id) {
    const account = syntheticAccounts.find((item) => item.id === filter.account_id);
    if (!account || holding.account !== account.name) return false;
  }
  if (filter.broker_id) {
    const account = syntheticAccounts.find((item) => item.broker_id === filter.broker_id);
    if (!account || holding.broker !== account.broker) return false;
  }
  return !filter.tax_wrapper || holding.tax_wrapper === filter.tax_wrapper;
}

function transactionMatches(transaction: Transaction, filter: PortfolioFilter): boolean {
  const date = transaction.occurred_at.slice(0, 10);
  if (filter.from && date < filter.from) return false;
  if (filter.to && date > filter.to) return false;
  if (filter.tax_wrapper && transaction.tax_wrapper !== filter.tax_wrapper) return false;
  if (filter.account_id) {
    const account = syntheticAccounts.find((item) => item.id === filter.account_id);
    if (!account || transaction.account !== account.name) return false;
  }
  if (filter.broker_id) {
    const account = syntheticAccounts.find((item) => item.broker_id === filter.broker_id);
    if (!account || transaction.broker !== account.broker) return false;
  }
  return true;
}

export async function getSummary(filter: PortfolioFilter): Promise<PortfolioSummary> {
  if (!databaseEnabled()) {
    return {
      ...syntheticSummary,
      meta: { ...syntheticSummary.meta, currency: filter.reporting_currency },
    };
  }
  const sql = readDatabase();
  const rows = await sql`
    SELECT
      ps.market_value,
      (
        SELECT coalesce(sum(flow.net_external_flow), 0)
        FROM portfolio_snapshot flow
        WHERE flow.reporting_currency = ${filter.reporting_currency}
          AND flow.account_id IS NULL
          AND (${filter.tax_wrapper ?? null}::tax_wrapper IS NULL OR flow.tax_wrapper = ${filter.tax_wrapper ?? null}::tax_wrapper)
          AND (${filter.from ?? null}::date IS NULL OR flow.snapshot_date >= ${filter.from ?? null}::date)
          AND (${filter.to ?? null}::date IS NULL OR flow.snapshot_date <= ${filter.to ?? null}::date)
      ) AS net_external_flows,
      ps.cumulative_twr,
      greatest(ps.price_set_as_of, ps.fx_set_as_of) AS as_of,
      lower(ps.quality::text) AS quality
    FROM portfolio_snapshot ps
    WHERE ps.reporting_currency = ${filter.reporting_currency}
      AND ps.account_id IS NULL
      AND (${filter.tax_wrapper ?? null}::tax_wrapper IS NULL OR ps.tax_wrapper = ${filter.tax_wrapper ?? null}::tax_wrapper)
      AND (${filter.to ?? null}::date IS NULL OR ps.snapshot_date <= ${filter.to ?? null}::date)
    ORDER BY ps.snapshot_date DESC
    LIMIT 1
  `;
  const row = rows[0];
  if (!row) {
    return {
      ...syntheticSummary,
      market_value: "0",
      net_external_flows: "0",
      absolute_result: "0",
      twr: null,
      xirr: null,
      realized_result: "0",
      unrealized_result: "0",
      income: "0",
      fees: "0",
      taxes: "0",
      meta: {
        as_of: new Date(0).toISOString(),
        data_freshness: "missing",
        currency: filter.reporting_currency,
        methodology_version: "2026.1",
        sources: ["Neon read model"],
      },
    };
  }
  const cash = await getIncomeCosts(filter);
  const marketValue = Number(row.market_value);
  const netFlows = Number(row.net_external_flows);
  return {
    market_value: decimal(row.market_value),
    net_external_flows: decimal(row.net_external_flows),
    absolute_result: decimal(marketValue - netFlows),
    twr: nullableDecimal(row.cumulative_twr),
    xirr: null,
    realized_result: "0",
    unrealized_result: decimal(marketValue - netFlows - Number(cash.dividends) - Number(cash.interest)),
    income: decimal(Number(cash.dividends) + Number(cash.interest)),
    fees: cash.fees,
    taxes: cash.taxes,
    meta: {
      as_of: iso(row.as_of),
      data_freshness: String(row.quality).toLowerCase() as PortfolioSummary["meta"]["data_freshness"],
      currency: filter.reporting_currency,
      methodology_version: "2026.1",
      sources: ["canonical ledger", "position snapshots", "market and FX providers"],
    },
  };
}

export async function getHoldings(filter: PortfolioFilter): Promise<Holding[]> {
  if (!databaseEnabled()) return syntheticHoldings.filter((item) => holdingMatches(item, filter));
  const sql = readDatabase();
  const rows = await sql`
    SELECT
      h.instrument_id,
      h.name,
      h.isin,
      listing.ticker,
      h.quantity,
      price.close AS price,
      price.currency AS price_currency,
      valuation.market_value,
      NULL::numeric AS unrealized_result,
      CASE
        WHEN total.market_value = 0 THEN NULL
        ELSE valuation.market_value / total.market_value
      END AS portfolio_weight,
      h.broker_name AS broker,
      h.account_name AS account,
      h.tax_wrapper,
      lower(coalesce(valuation.quality, 'MISSING')::text) AS valuation_quality,
      price.retrieved_at AS price_as_of
    FROM app_holding h
    JOIN app_account aa ON aa.id = h.account_id
    LEFT JOIN LATERAL (
      SELECT ps.market_value, ps.quality, ps.price_id
      FROM position_snapshot ps
      WHERE ps.account_id = h.account_id
        AND ps.instrument_id = h.instrument_id
        AND ps.reporting_currency = ${filter.reporting_currency}
      ORDER BY ps.snapshot_date DESC
      LIMIT 1
    ) valuation ON true
    LEFT JOIN price ON price.id = valuation.price_id
    LEFT JOIN LATERAL (
      SELECT ticker
      FROM listing
      WHERE instrument_id = h.instrument_id
      ORDER BY is_primary DESC, created_at
      LIMIT 1
    ) listing ON true
    LEFT JOIN LATERAL (
      SELECT market_value
      FROM portfolio_snapshot
      WHERE reporting_currency = ${filter.reporting_currency}
        AND account_id IS NULL
      ORDER BY snapshot_date DESC
      LIMIT 1
    ) total ON true
    WHERE (${filter.account_id ?? null}::uuid IS NULL OR h.account_id = ${filter.account_id ?? null}::uuid)
      AND (${filter.broker_id ?? null}::uuid IS NULL OR aa.broker_id = ${filter.broker_id ?? null}::uuid)
      AND (${filter.tax_wrapper ?? null}::tax_wrapper IS NULL OR h.tax_wrapper = ${filter.tax_wrapper ?? null}::tax_wrapper)
    ORDER BY valuation.market_value DESC NULLS LAST, h.name
  `;
  return rows.map((row) => ({
    instrument_id: String(row.instrument_id),
    name: String(row.name),
    isin: row.isin ? String(row.isin).trim() : null,
    ticker: row.ticker ? String(row.ticker) : null,
    quantity: decimal(row.quantity),
    price: nullableDecimal(row.price),
    price_currency: row.price_currency ? String(row.price_currency).trim() : null,
    market_value: nullableDecimal(row.market_value),
    unrealized_result: nullableDecimal(row.unrealized_result),
    portfolio_weight: nullableDecimal(row.portfolio_weight),
    broker: String(row.broker),
    account: String(row.account),
    tax_wrapper: String(row.tax_wrapper) as Holding["tax_wrapper"],
    valuation_quality: String(row.valuation_quality) as Holding["valuation_quality"],
    price_as_of: row.price_as_of ? iso(row.price_as_of) : null,
  }));
}

export async function getTransactions(filter: PortfolioFilter): Promise<Transaction[]> {
  if (!databaseEnabled()) {
    return syntheticTransactions.filter((item) => transactionMatches(item, filter));
  }
  const sql = readDatabase();
  const rows = await sql`
    SELECT *
    FROM app_transaction
    WHERE (${filter.from ?? null}::date IS NULL OR occurred_at::date >= ${filter.from ?? null}::date)
      AND (${filter.to ?? null}::date IS NULL OR occurred_at::date <= ${filter.to ?? null}::date)
      AND (${filter.account_id ?? null}::uuid IS NULL OR account_id = ${filter.account_id ?? null}::uuid)
      AND (${filter.broker_id ?? null}::uuid IS NULL OR broker_id = ${filter.broker_id ?? null}::uuid)
      AND (${filter.tax_wrapper ?? null}::tax_wrapper IS NULL OR tax_wrapper = ${filter.tax_wrapper ?? null}::tax_wrapper)
    ORDER BY occurred_at DESC
    LIMIT 500
  `;
  return rows.map((row) => ({
    id: String(row.id),
    occurred_at: iso(row.occurred_at),
    event_type: String(row.event_type) as Transaction["event_type"],
    broker: String(row.broker_name),
    account: String(row.account_name),
    tax_wrapper: String(row.tax_wrapper) as Transaction["tax_wrapper"],
    instrument_name: row.instrument_name ? String(row.instrument_name) : null,
    isin: row.isin ? String(row.isin).trim() : null,
    quantity_delta: nullableDecimal(row.quantity_delta),
    gross_amount: nullableDecimal(row.gross_amount),
    currency: row.gross_currency ? String(row.gross_currency).trim() : null,
    fee_amount: decimal(row.fee_amount),
    tax_amount: decimal(row.tax_amount),
    source_status: String(row.source_status),
  }));
}

export async function getExposures(
  filter: PortfolioFilter,
  dimension?: Exposure["dimension"],
): Promise<Exposure[]> {
  if (!databaseEnabled()) {
    return syntheticExposures.filter((item) => !dimension || item.dimension === dimension);
  }
  const sql = readDatabase();
  const rows = await sql`
    SELECT
      lower(dimension::text) AS dimension,
      exposure_key,
      label,
      weight,
      value,
      lower(source::text) AS source,
      coverage,
      snapshot_date
    FROM exposure_snapshot
    WHERE reporting_currency = ${filter.reporting_currency}
      AND (${filter.account_id ?? null}::uuid IS NULL OR account_id = ${filter.account_id ?? null}::uuid)
      AND (${filter.tax_wrapper ?? null}::tax_wrapper IS NULL OR tax_wrapper = ${filter.tax_wrapper ?? null}::tax_wrapper)
      AND (${dimension ?? null}::text IS NULL OR dimension::text = upper(${dimension ?? null}::text))
      AND snapshot_date = (
        SELECT max(snapshot_date)
        FROM exposure_snapshot
        WHERE reporting_currency = ${filter.reporting_currency}
      )
    ORDER BY dimension, weight DESC
  `;
  return rows.map((row) => ({
    dimension: String(row.dimension) as Exposure["dimension"],
    key: String(row.exposure_key),
    label: String(row.label),
    weight: decimal(row.weight),
    value: decimal(row.value),
    source: String(row.source) as Exposure["source"],
    coverage: decimal(row.coverage),
    as_of: iso(row.snapshot_date).slice(0, 10),
  }));
}

export async function getPerformance(filter: PortfolioFilter): Promise<PerformancePoint[]> {
  if (!databaseEnabled()) {
    return syntheticPerformance
      .filter((point) => (!filter.from || point.date >= filter.from) && (!filter.to || point.date <= filter.to))
      .map((point) => ({
        ...point,
        benchmarks: Object.fromEntries(
          Object.entries(point.benchmarks).filter(([code]) => !filter.benchmark.length || filter.benchmark.includes(code as "SP500" | "MSCI_WORLD" | "MSCI_ACWI")),
        ),
      }));
  }
  const sql = readDatabase();
  const portfolioRows = await sql`
    SELECT snapshot_date, cumulative_twr, lower(quality::text) AS quality
    FROM portfolio_snapshot
    WHERE reporting_currency = ${filter.reporting_currency}
      AND (${filter.account_id ?? null}::uuid IS NULL OR account_id = ${filter.account_id ?? null}::uuid)
      AND (${filter.tax_wrapper ?? null}::tax_wrapper IS NULL OR tax_wrapper = ${filter.tax_wrapper ?? null}::tax_wrapper)
      AND (${filter.from ?? null}::date IS NULL OR snapshot_date >= ${filter.from ?? null}::date)
      AND (${filter.to ?? null}::date IS NULL OR snapshot_date <= ${filter.to ?? null}::date)
    ORDER BY snapshot_date
  `;
  const benchmarkRows = filter.benchmark.length
    ? await sql`
        SELECT bs.series_date, b.code, bs.normalized_value
        FROM benchmark_series bs
        JOIN benchmark b ON b.id = bs.benchmark_id
        WHERE bs.reporting_currency = ${filter.reporting_currency}
          AND b.code IN ${sql(filter.benchmark)}
          AND (${filter.from ?? null}::date IS NULL OR bs.series_date >= ${filter.from ?? null}::date)
          AND (${filter.to ?? null}::date IS NULL OR bs.series_date <= ${filter.to ?? null}::date)
      `
    : [];
  const benchmarkByDate = new Map<string, PerformancePoint["benchmarks"]>();
  for (const row of benchmarkRows) {
    const key = iso(row.series_date).slice(0, 10);
    const existing = benchmarkByDate.get(key) ?? {};
    existing[String(row.code) as keyof PerformancePoint["benchmarks"]] = decimal(row.normalized_value);
    benchmarkByDate.set(key, existing);
  }
  return portfolioRows.map((row) => {
    const date = iso(row.snapshot_date).slice(0, 10);
    return {
      date,
      portfolio: row.cumulative_twr === null ? null : decimal(Number(row.cumulative_twr) + 1),
      benchmarks: benchmarkByDate.get(date) ?? {},
      quality: String(row.quality) as PerformancePoint["quality"],
    };
  });
}

export async function getImportStatus(): Promise<ImportStatus[]> {
  if (!databaseEnabled()) return syntheticImportStatus;
  const rows = await readDatabase()`SELECT * FROM app_import_status ORDER BY connector`;
  return rows.map((row) => ({
    connector: String(row.connector),
    last_checked_at: row.last_checked_at ? iso(row.last_checked_at) : null,
    last_received_at: row.last_received_at ? iso(row.last_received_at) : null,
    last_success_at: row.last_success_at ? iso(row.last_success_at) : null,
    imported_count: Number(row.imported_count),
    duplicate_count: Number(row.duplicate_count),
    error_count: Number(row.error_count),
    status: String(row.status) as ImportStatus["status"],
  }));
}

export async function getDataQualityIssues(): Promise<DataQualityIssue[]> {
  if (!databaseEnabled()) return syntheticIssues;
  const rows = await readDatabase()`
    SELECT id, code, severity, status, summary, detected_at, resolved_at
    FROM app_data_quality_issue
    WHERE status <> 'resolved'
    ORDER BY detected_at DESC
  `;
  return rows.map((row) => ({
    id: String(row.id),
    code: String(row.code),
    severity: String(row.severity) as DataQualityIssue["severity"],
    status: String(row.status) as DataQualityIssue["status"],
    summary: String(row.summary),
    detected_at: iso(row.detected_at),
    resolved_at: row.resolved_at ? iso(row.resolved_at) : null,
  }));
}

export async function getAccounts(): Promise<AccountSummary[]> {
  if (!databaseEnabled()) return syntheticAccounts;
  const rows = await readDatabase()`
    SELECT id, broker_id, broker_name, pseudonym, tax_wrapper, base_currency
    FROM app_account
    ORDER BY broker_name, pseudonym
  `;
  return rows.map((row) => ({
    id: String(row.id),
    broker_id: String(row.broker_id),
    broker: String(row.broker_name),
    name: String(row.pseudonym),
    tax_wrapper: String(row.tax_wrapper) as AccountSummary["tax_wrapper"],
    base_currency: String(row.base_currency).trim(),
  }));
}

export async function getIncomeCosts(filter: PortfolioFilter): Promise<IncomeCosts> {
  if (!databaseEnabled()) {
    return { ...syntheticIncomeCosts, currency: filter.reporting_currency };
  }
  const sql = readDatabase();
  const rows = await sql`
    SELECT
      coalesce(sum(gross_amount) FILTER (WHERE event_type = 'DIVIDEND'), 0) AS dividends,
      coalesce(sum(gross_amount) FILTER (WHERE event_type = 'INTEREST'), 0) AS interest,
      coalesce(sum(fee_amount), 0) AS fees,
      coalesce(sum(tax_amount), 0) AS taxes
    FROM app_transaction
    WHERE (${filter.from ?? null}::date IS NULL OR occurred_at::date >= ${filter.from ?? null}::date)
      AND (${filter.to ?? null}::date IS NULL OR occurred_at::date <= ${filter.to ?? null}::date)
      AND (${filter.account_id ?? null}::uuid IS NULL OR account_id = ${filter.account_id ?? null}::uuid)
      AND (${filter.broker_id ?? null}::uuid IS NULL OR broker_id = ${filter.broker_id ?? null}::uuid)
      AND (${filter.tax_wrapper ?? null}::tax_wrapper IS NULL OR tax_wrapper = ${filter.tax_wrapper ?? null}::tax_wrapper)
  `;
  const row = rows[0] ?? {};
  return {
    dividends: decimal(row.dividends),
    interest: decimal(row.interest),
    fees: decimal(row.fees),
    taxes: decimal(row.taxes),
    currency: filter.reporting_currency,
  };
}

export async function getMethodology(): Promise<Methodology> {
  return syntheticMethodology;
}

export async function getBrokers(): Promise<Array<{ id: string; code: string; name: string }>> {
  if (!databaseEnabled()) {
    return Array.from(
      new Map(
        syntheticAccounts.map((account) => [
          account.broker_id,
          { id: account.broker_id, code: account.broker.toUpperCase(), name: account.broker },
        ]),
      ).values(),
    );
  }
  const rows = await readDatabase()`
    SELECT id, code, display_name
    FROM broker
    WHERE is_active
    ORDER BY display_name
  `;
  return rows.map((row) => ({
    id: String(row.id),
    code: String(row.code),
    name: String(row.display_name),
  }));
}
