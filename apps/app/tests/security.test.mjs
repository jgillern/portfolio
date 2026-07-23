import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const auth = await readFile(new URL("../src/lib/auth.ts", import.meta.url), "utf8");
const session = await readFile(
  new URL("../src/app/api/session/route.ts", import.meta.url),
  "utf8",
);
const mcp = await readFile(new URL("../src/lib/mcp.ts", import.meta.url), "utf8");
const api = await readFile(
  new URL("../src/app/v1/[...resource]/route.ts", import.meta.url),
  "utf8",
);

test("owner session is HTTP-only, strict and signed", () => {
  assert.match(auth, /createHmac\("sha256"/);
  assert.match(auth, /timingSafeEqual/);
  assert.match(session, /sameSite: "strict"/);
  assert.match(session, /httpOnly: true/);
  assert.match(session, /ATTEMPT_LIMIT = 5/);
  assert.match(session, /status: 429/);
  assert.match(session, /event: "owner_session"/);
});

test("MCP authenticates and exposes named reads plus one scoped import", () => {
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
    "get_exposures",
    "get_import_status",
    "get_data_quality_issues",
    "get_income_and_costs",
    "get_methodology",
    "import_george_dip_statement",
  ]);
  assert.match(mcp, /"openai\/fileParams": \["statement"\]/);
  assert.match(mcp, /readOnlyHint: false/);
  assert.match(mcp, /CHATGPT/);
  assert.doesNotMatch(mcp, /place_order|execute_trade|generic_write/);
});

test("read API requires the owner session and disables caching", () => {
  assert.match(api, /isOwnerAuthenticated/);
  assert.match(api, /private, no-store/);
  assert.doesNotMatch(api, /export async function (POST|PUT|PATCH|DELETE)/);
});
