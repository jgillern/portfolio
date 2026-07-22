import { z } from "zod";

export const DecimalStringSchema = z.string().regex(/^-?\d+(\.\d+)?$/);
export const IsoDateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
export const IsoDateTimeSchema = z.iso.datetime({ offset: true });

export const TaxWrapperSchema = z.enum(["DIP", "STANDARD"]);
export const ReportingCurrencySchema = z.enum(["CZK", "EUR"]);
export const DataQualitySchema = z.enum([
  "verified",
  "estimated",
  "partial",
  "stale",
  "missing",
]);
export const EventTypeSchema = z.enum([
  "BUY",
  "SELL",
  "DEPOSIT",
  "WITHDRAWAL",
  "DIVIDEND",
  "INTEREST",
  "FEE",
  "TAX",
  "FX_CONVERSION",
  "TRANSFER_IN",
  "TRANSFER_OUT",
  "SPLIT",
  "MERGER",
  "SPINOFF",
  "RETURN_OF_CAPITAL",
  "ADJUSTMENT_REVERSAL",
]);
export const BenchmarkSchema = z.enum(["SP500", "MSCI_WORLD", "MSCI_ACWI"]);

export const PortfolioFilterSchema = z.object({
  from: IsoDateSchema.optional(),
  to: IsoDateSchema.optional(),
  reporting_currency: ReportingCurrencySchema.default("CZK"),
  broker_id: z.uuid().optional(),
  account_id: z.uuid().optional(),
  tax_wrapper: TaxWrapperSchema.optional(),
  benchmark: z.array(BenchmarkSchema).max(3).default([]),
});

export const ResponseMetaSchema = z.object({
  as_of: IsoDateTimeSchema,
  data_freshness: DataQualitySchema,
  currency: ReportingCurrencySchema,
  methodology_version: z.string(),
  sources: z.array(z.string()),
});

export const PortfolioSummarySchema = z.object({
  market_value: DecimalStringSchema,
  net_external_flows: DecimalStringSchema,
  absolute_result: DecimalStringSchema,
  twr: DecimalStringSchema.nullable(),
  xirr: DecimalStringSchema.nullable(),
  realized_result: DecimalStringSchema,
  unrealized_result: DecimalStringSchema,
  income: DecimalStringSchema,
  fees: DecimalStringSchema,
  taxes: DecimalStringSchema,
  meta: ResponseMetaSchema,
});

export const HoldingSchema = z.object({
  instrument_id: z.uuid(),
  name: z.string(),
  isin: z.string().nullable(),
  ticker: z.string().nullable(),
  quantity: DecimalStringSchema,
  price: DecimalStringSchema.nullable(),
  price_currency: z.string().length(3).nullable(),
  market_value: DecimalStringSchema.nullable(),
  unrealized_result: DecimalStringSchema.nullable(),
  portfolio_weight: DecimalStringSchema.nullable(),
  broker: z.string(),
  account: z.string(),
  tax_wrapper: TaxWrapperSchema,
  valuation_quality: DataQualitySchema,
  price_as_of: IsoDateTimeSchema.nullable(),
});

export const TransactionSchema = z.object({
  id: z.uuid(),
  occurred_at: IsoDateTimeSchema,
  event_type: EventTypeSchema,
  broker: z.string(),
  account: z.string(),
  tax_wrapper: TaxWrapperSchema,
  instrument_name: z.string().nullable(),
  isin: z.string().nullable(),
  quantity_delta: DecimalStringSchema.nullable(),
  gross_amount: DecimalStringSchema.nullable(),
  currency: z.string().length(3).nullable(),
  fee_amount: DecimalStringSchema,
  tax_amount: DecimalStringSchema,
  source_status: z.string(),
});

export const ExposureSchema = z.object({
  dimension: z.enum(["asset_class", "sector", "geography", "currency", "underlying"]),
  key: z.string(),
  label: z.string(),
  weight: DecimalStringSchema,
  value: DecimalStringSchema,
  source: z.enum(["direct", "look_through", "unknown"]),
  coverage: DecimalStringSchema,
  as_of: IsoDateSchema,
});

export const ImportStatusSchema = z.object({
  connector: z.string(),
  last_checked_at: IsoDateTimeSchema.nullable(),
  last_received_at: IsoDateTimeSchema.nullable(),
  last_success_at: IsoDateTimeSchema.nullable(),
  imported_count: z.number().int().nonnegative(),
  duplicate_count: z.number().int().nonnegative(),
  error_count: z.number().int().nonnegative(),
  status: z.enum(["healthy", "stale", "error", "not_configured"]),
});

export const DataQualityIssueSchema = z.object({
  id: z.uuid(),
  code: z.string(),
  severity: z.enum(["info", "warning", "error", "critical"]),
  status: z.enum(["open", "acknowledged", "resolved"]),
  summary: z.string(),
  detected_at: IsoDateTimeSchema,
  resolved_at: IsoDateTimeSchema.nullable(),
});

export type PortfolioFilter = z.infer<typeof PortfolioFilterSchema>;
export type PortfolioSummary = z.infer<typeof PortfolioSummarySchema>;
export type Holding = z.infer<typeof HoldingSchema>;
export type Transaction = z.infer<typeof TransactionSchema>;
export type Exposure = z.infer<typeof ExposureSchema>;
export type ImportStatus = z.infer<typeof ImportStatusSchema>;
export type DataQualityIssue = z.infer<typeof DataQualityIssueSchema>;
