import assert from "node:assert/strict";
import { spawn } from "node:child_process";

const port = 3210;
const server = spawn(
  "pnpm",
  [
    "--filter",
    "@portfolio/app",
    "start",
    "--hostname",
    "127.0.0.1",
    "--port",
    String(port),
  ],
  {
    env: {
      ...process.env,
      ALLOW_PREVIEW_AUTH_BYPASS: "true",
      DATA_MODE: "synthetic",
      VERCEL_ENV: "preview",
    },
    shell: process.platform === "win32",
    stdio: ["ignore", "pipe", "pipe"],
  },
);

let stderr = "";
server.stderr.on("data", (chunk) => {
  stderr += chunk.toString();
});

async function waitForServer() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch("http://127.0.0.1:" + port + "/");
      if (response.ok) return;
    } catch {
      // The server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Next server did not become ready. " + stderr.slice(-500));
}

try {
  await waitForServer();
  const dashboard = await fetch(
    "http://127.0.0.1:" +
      port +
      "/?tax_wrapper=DIP&reporting_currency=EUR",
  );
  assert.equal(dashboard.status, 200);
  const html = await dashboard.text();
  assert.match(html, /Přehled majetku/);
  assert.match(html, />DIP</);
  assert.match(html, />EUR</);

  const holdings = await fetch(
    "http://127.0.0.1:" +
      port +
      "/holdings?tax_wrapper=STANDARD&reporting_currency=CZK",
  );
  assert.equal(holdings.status, 200);
  assert.match(await holdings.text(), /Holdings/);

  const api = await fetch(
    "http://127.0.0.1:" +
      port +
      "/v1/portfolio/summary?tax_wrapper=DIP&reporting_currency=EUR",
  );
  assert.equal(api.status, 200);
  assert.match(api.headers.get("cache-control") ?? "", /no-store/);
  const body = await api.json();
  assert.equal(body.data.meta.currency, "EUR");
  console.log("Production smoke checks passed.");
} finally {
  server.kill("SIGTERM");
}
