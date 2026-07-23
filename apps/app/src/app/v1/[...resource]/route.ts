import { NextResponse } from "next/server";

import { isOwnerAuthenticated } from "@/lib/auth";
import { parsePortfolioFilters } from "@/lib/filters";
import {
  getAccounts,
  getBrokers,
  getDataQualityIssues,
  getExposures,
  getHoldings,
  getImportStatus,
  getIncomeCosts,
  getMethodology,
  getPerformance,
  getSummary,
  getTransactions,
} from "@/lib/read-model";
import type { Exposure } from "@/lib/types";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type RouteContext = { params: Promise<{ resource: string[] }> };

const exposureDimensions = new Set<Exposure["dimension"]>([
  "asset_class",
  "sector",
  "geography",
  "currency",
  "underlying",
]);

function response(data: unknown, status = 200): Response {
  return NextResponse.json(
    { data },
    {
      status,
      headers: {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
      },
    },
  );
}

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  if (!(await isOwnerAuthenticated())) return response({ error: "unauthorized" }, 401);

  const { resource } = await context.params;
  const key = resource.join("/");
  const url = new URL(request.url);
  const filter = parsePortfolioFilters(url);

  switch (key) {
    case "portfolio/summary":
      return response(await getSummary(filter));
    case "portfolio/holdings":
      return response(await getHoldings(filter));
    case "portfolio/performance":
      return response(await getPerformance(filter));
    case "portfolio/exposures": {
      const requested = url.searchParams.get("dimension");
      const dimension =
        requested && exposureDimensions.has(requested as Exposure["dimension"])
          ? (requested as Exposure["dimension"])
          : undefined;
      return response(await getExposures(filter, dimension));
    }
    case "portfolio/income":
    case "portfolio/costs":
      return response(await getIncomeCosts(filter));
    case "transactions":
      return response(await getTransactions(filter));
    case "accounts":
      return response(await getAccounts());
    case "brokers":
      return response(await getBrokers());
    case "import-status":
      return response(await getImportStatus());
    case "data-quality-issues":
      return response(await getDataQualityIssues());
    case "methodology":
      return response(await getMethodology());
    default:
      return response({ error: "not_found" }, 404);
  }
}
