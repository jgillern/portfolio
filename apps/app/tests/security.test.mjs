import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const auth = await readFile(new URL("../src/lib/auth.ts", import.meta.url), "utf8");
const mcp = await readFile(new URL("../src/lib/mcp.ts", import.meta.url), "utf8");
const api = await readFile(
  new URL("../src/app/v1/[...resource]/route.ts", import.meta.url),
  "utf8",
);

test("owner session is HTTP-only, strict and signed", () => {
  assert.match(auth, /createHmac\("sha256"/);
  assert.match(auth, /timingSafeEqual/);
  assert.match(auth, /sameSite: "strict"/);
  assert.match(auth, /httpOnly: true/);
});

test("MCP authenticates and exposes only named read tools", () => {
  assert.match(mcp, /verifyMcpBearer/);
  assert.doesNotMatch(mcp, /execute_sql|query_sql|registerResource/);
  const tools = [...mcp.matchAll(/server\.registerTool\(\s*"([^"]+)"/g)].map(
    (match) => match[1],
  );
  assert.deepEqual(tools, [
    "get_portfolio_summary",
    "get_holdings",
    "get_transactions",
    "get_performance",
    "get_exposure",
    "get_import_status",
    "get_data_quality_issues",
    "get_income_costs",
    "get_methodology",
  ]);
});

test("read API requires the owner session and disables caching", () => {
  assert.match(api, /isOwnerAuthenticated/);
  assert.match(api, /private, no-store/);
  assert.doesNotMatch(api, /export async function (POST|PUT|PATCH|DELETE)/);
});
