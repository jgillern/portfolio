import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { z } from "zod";

import {
  BenchmarkSchema,
  IsoDateSchema,
  ReportingCurrencySchema,
  TaxWrapperSchema,
} from "@portfolio/contracts";

import { verifyMcpBearer } from "./auth";
import {
  getDataQualityIssues,
  getExposures,
  getHoldings,
  getImportStatus,
  getIncomeCosts,
  getMethodology,
  getPerformance,
  getSummary,
  getTransactions,
} from "./read-model";
import type { Exposure, PortfolioFilter } from "./types";

const filterShape = {
  from: IsoDateSchema.optional(),
  to: IsoDateSchema.optional(),
  reporting_currency: ReportingCurrencySchema.optional(),
  broker_id: z.uuid().optional(),
  account_id: z.uuid().optional(),
  tax_wrapper: TaxWrapperSchema.optional(),
  benchmark: z.array(BenchmarkSchema).max(3).optional(),
};

type ToolFilter = {
  from?: string;
  to?: string;
  reporting_currency?: "CZK" | "EUR";
  broker_id?: string;
  account_id?: string;
  tax_wrapper?: "DIP" | "STANDARD";
  benchmark?: Array<"SP500" | "MSCI_WORLD" | "MSCI_ACWI">;
};

const readOnlyAnnotations = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: false,
};

function filter(input: ToolFilter): PortfolioFilter {
  return {
    reporting_currency: input.reporting_currency ?? "CZK",
    benchmark: input.benchmark ?? [],
    ...(input.from ? { from: input.from } : {}),
    ...(input.to ? { to: input.to } : {}),
    ...(input.broker_id ? { broker_id: input.broker_id } : {}),
    ...(input.account_id ? { account_id: input.account_id } : {}),
    ...(input.tax_wrapper ? { tax_wrapper: input.tax_wrapper } : {}),
  };
}

function result(data: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(data) }],
    structuredContent: { data },
  };
}

function createServer(): McpServer {
  const server = new McpServer({
    name: "portfolio-readonly",
    version: "0.1.0",
  });

  server.registerTool(
    "get_portfolio_summary",
    {
      title: "Portfolio summary",
      description: "Read aggregate value, flows, results, TWR and XIRR.",
      inputSchema: filterShape,
      annotations: readOnlyAnnotations,
    },
    async (input) => result(await getSummary(filter(input))),
  );

  server.registerTool(
    "get_holdings",
    {
      title: "Portfolio holdings",
      description: "Read current positions, valuation quality and account allocation.",
      inputSchema: filterShape,
      annotations: readOnlyAnnotations,
    },
    async (input) => result(await getHoldings(filter(input))),
  );

  server.registerTool(
    "get_transactions",
    {
      title: "Portfolio transactions",
      description: "Read canonical ledger events without raw source documents.",
      inputSchema: filterShape,
      annotations: readOnlyAnnotations,
    },
    async (input) => result(await getTransactions(filter(input))),
  );

  server.registerTool(
    "get_performance",
    {
      title: "Portfolio performance",
      description: "Read normalized TWR and selected proxy benchmark series.",
      inputSchema: filterShape,
      annotations: readOnlyAnnotations,
    },
    async (input) => result(await getPerformance(filter(input))),
  );

  server.registerTool(
    "get_exposure",
    {
      title: "Portfolio exposure",
      description: "Read direct, look-through and Unknown exposure with coverage.",
      inputSchema: {
        ...filterShape,
        dimension: z
          .enum(["asset_class", "sector", "geography", "currency", "underlying"])
          .optional(),
      },
      annotations: readOnlyAnnotations,
    },
    async ({ dimension, ...input }) =>
      result(await getExposures(filter(input), dimension as Exposure["dimension"] | undefined)),
  );

  server.registerTool(
    "get_import_status",
    {
      title: "Import health",
      description: "Read redacted connector freshness and import counters.",
      inputSchema: {},
      annotations: readOnlyAnnotations,
    },
    async () => result(await getImportStatus()),
  );

  server.registerTool(
    "get_data_quality_issues",
    {
      title: "Data quality issues",
      description: "Read unresolved reconciliation and data quality findings.",
      inputSchema: {},
      annotations: readOnlyAnnotations,
    },
    async () => result(await getDataQualityIssues()),
  );

  server.registerTool(
    "get_income_costs",
    {
      title: "Income and costs",
      description: "Read dividends, interest, fees and taxes.",
      inputSchema: filterShape,
      annotations: readOnlyAnnotations,
    },
    async (input) => result(await getIncomeCosts(filter(input))),
  );

  server.registerTool(
    "get_methodology",
    {
      title: "Portfolio methodology",
      description: "Read calculation rules, data sources and limitations.",
      inputSchema: {},
      annotations: readOnlyAnnotations,
    },
    async () => result(await getMethodology()),
  );

  return server;
}

export async function handleMcp(request: Request): Promise<Response> {
  if (!verifyMcpBearer(request.headers.get("authorization"))) {
    return Response.json(
      { error: "unauthorized" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }

  const server = createServer();
  const transport = new WebStandardStreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
    enableJsonResponse: true,
  });
  await server.connect(transport);
  const response = await transport.handleRequest(request);
  const headers = new Headers(response.headers);
  headers.set("Cache-Control", "private, no-store");
  headers.set("X-Content-Type-Options", "nosniff");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}
