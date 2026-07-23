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
import { callWorker } from "./worker-client";
import {
  getAccounts,
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

const importAnnotations = {
  readOnlyHint: false,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: false,
};

const MAX_PDF_BYTES = 10 * 1024 * 1024;
const ChatGptFileSchema = z.object({
  download_url: z.string().url(),
  file_id: z.string().min(1),
  mime_type: z.string().optional(),
  file_name: z.string().optional(),
});
type ChatGptFile = z.infer<typeof ChatGptFileSchema>;

function blockedDownloadHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local")) {
    return true;
  }
  if (/^(127\.|10\.|169\.254\.|192\.168\.)/.test(host)) return true;
  const match = /^172\.(\d+)\./.exec(host);
  if (match && Number(match[1]) >= 16 && Number(match[1]) <= 31) return true;
  return host === "::1" || host.startsWith("fc") || host.startsWith("fd") || host.startsWith("fe80:");
}

async function downloadPdf(file: ChatGptFile): Promise<Uint8Array> {
  if (file.mime_type && file.mime_type !== "application/pdf") {
    throw new Error("Only PDF statements are accepted.");
  }
  const url = new URL(file.download_url);
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    blockedDownloadHost(url.hostname)
  ) {
    throw new Error("The temporary file URL is not allowed.");
  }
  const response = await fetch(url, {
    headers: { Accept: "application/pdf" },
    redirect: "error",
    cache: "no-store",
    signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok || !response.body) {
    throw new Error("The ChatGPT attachment could not be downloaded.");
  }
  const declaredLength = Number(response.headers.get("content-length") ?? "0");
  if (declaredLength > MAX_PDF_BYTES) {
    throw new Error("The PDF exceeds the 10 MB limit.");
  }

  const chunks: Uint8Array[] = [];
  let size = 0;
  const reader = response.body.getReader();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_PDF_BYTES) {
      await reader.cancel();
      throw new Error("The PDF exceeds the 10 MB limit.");
    }
    chunks.push(value);
  }
  if (!size) throw new Error("The PDF is empty.");
  const payload = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    payload.set(chunk, offset);
    offset += chunk.byteLength;
  }
  if (new TextDecoder().decode(payload.subarray(0, 5)) !== "%PDF-") {
    throw new Error("The attachment is not a PDF.");
  }
  return payload;
}

async function importGeorgeDipStatement(
  accountRef: string,
  file: ChatGptFile,
): Promise<unknown> {
  const payload = await downloadPdf(file);
  const outbound = new FormData();
  outbound.set("broker_code", "GEORGE");
  outbound.set("account_ref", accountRef);
  outbound.set("source_channel", "CHATGPT");
  const pdfBuffer = new ArrayBuffer(payload.byteLength);
  new Uint8Array(pdfBuffer).set(payload);
  outbound.set(
    "document",
    new Blob([pdfBuffer], { type: "application/pdf" }),
    (file.file_name ?? "george-dip.pdf").slice(0, 160),
  );
  return callWorker({
    path: "/api/import",
    body: outbound,
    contentHashPayload: payload,
  });
}

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
    name: "portfolio-private",
    version: "0.2.0",
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
    "get_exposures",
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
    "get_income_and_costs",
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

  server.registerTool(
    "get_accounts",
    {
      title: "Configured portfolio accounts",
      description:
        "Read account pseudonyms, brokers and tax wrappers. Use the name field as account_ref for a statement import.",
      inputSchema: {},
      annotations: readOnlyAnnotations,
    },
    async () => result(await getAccounts()),
  );

  server.registerTool(
    "import_george_dip_statement",
    {
      title: "Import a George DIP statement",
      description:
        "Import one attached Ceska sporitelna/George PDF into the configured DIP account. " +
        "Only completed transactions are posted; pending orders are ignored. " +
        "The worker validates that the account is GEORGE + DIP before writing.",
      inputSchema: {
        account_ref: z.string().min(1).max(120),
        statement: ChatGptFileSchema,
      },
      annotations: importAnnotations,
      _meta: {
        "openai/fileParams": ["statement"],
        "openai/toolInvocation/invoking": "Importuji výpis ČS DIP…",
        "openai/toolInvocation/invoked": "Výpis ČS DIP byl zpracován",
      },
    },
    async ({ account_ref, statement }) =>
      result(await importGeorgeDipStatement(account_ref, statement)),
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
