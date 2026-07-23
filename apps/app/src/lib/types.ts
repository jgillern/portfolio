import type {
  DataQualityIssue,
  Exposure,
  Holding,
  ImportStatus,
  PortfolioFilter,
  PortfolioSummary,
  Transaction,
} from "@portfolio/contracts";

export type {
  DataQualityIssue,
  Exposure,
  Holding,
  ImportStatus,
  PortfolioFilter,
  PortfolioSummary,
  Transaction,
};

export type PerformancePoint = {
  date: string;
  portfolio: string | null;
  benchmarks: Partial<Record<"SP500" | "MSCI_WORLD" | "MSCI_ACWI", string | null>>;
  quality: "verified" | "estimated" | "partial" | "stale" | "missing";
};

export type AccountSummary = {
  id: string;
  broker_id: string;
  broker: string;
  name: string;
  tax_wrapper: "DIP" | "STANDARD";
  base_currency: string;
};

export type IncomeCosts = {
  dividends: string;
  interest: string;
  fees: string;
  taxes: string;
  currency: "CZK" | "EUR";
};

export type Methodology = {
  version: string;
  ledger: string;
  performance: string;
  fx: string;
  valuation: string;
  benchmarks: string;
  exposures: string;
  limitations: string[];
};
