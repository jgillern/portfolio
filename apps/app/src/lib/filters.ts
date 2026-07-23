import { PortfolioFilterSchema, type PortfolioFilter } from "@portfolio/contracts";

function candidateFromSearchParams(params: URLSearchParams) {
  return {
    from: params.get("from") || undefined,
    to: params.get("to") || undefined,
    reporting_currency: params.get("reporting_currency") || undefined,
    broker_id: params.get("broker_id") || undefined,
    account_id: params.get("account_id") || undefined,
    tax_wrapper: params.get("tax_wrapper") || undefined,
    benchmark: params.getAll("benchmark"),
  };
}

export function parsePortfolioFilters(input: string | URL | URLSearchParams): PortfolioFilter {
  const params =
    input instanceof URLSearchParams
      ? input
      : input instanceof URL
        ? input.searchParams
        : new URL(input, "https://portfolio.invalid").searchParams;
  const parsed = PortfolioFilterSchema.safeParse(candidateFromSearchParams(params));
  return parsed.success ? parsed.data : PortfolioFilterSchema.parse({});
}

export function filtersFromRecord(
  values: Record<string, string | string[] | undefined>,
): PortfolioFilter {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (Array.isArray(value)) {
      value.forEach((item) => params.append(key, item));
    } else if (value) {
      params.set(key, value);
    }
  }
  return parsePortfolioFilters(params);
}
