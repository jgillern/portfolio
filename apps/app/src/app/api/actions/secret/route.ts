import { authorizeAction } from "@/lib/action-security";
import { callWorker } from "@/lib/worker-client";

export const runtime = "nodejs";

export async function POST(request: Request): Promise<Response> {
  const unauthorized = await authorizeAction(request);
  if (unauthorized) return unauthorized;

  const input = (await request.json()) as {
    account_id?: unknown;
    secret_type?: unknown;
    value?: unknown;
  };
  if (
    typeof input.account_id !== "string" ||
    !/^[0-9a-f-]{36}$/i.test(input.account_id) ||
    !new Set(["XTB_PDF_PASSWORD", "GEORGE_PDF_PASSWORD"]).has(
      String(input.secret_type),
    ) ||
    typeof input.value !== "string" ||
    input.value.length < 1 ||
    input.value.length > 4096
  ) {
    return Response.json({ error: "invalid_secret" }, { status: 400 });
  }
  const payload = JSON.stringify({
    account_id: input.account_id,
    secret_type: input.secret_type,
    value: input.value,
    key_version: 1,
  });
  try {
    const data = await callWorker({
      path: "/api/secrets",
      body: payload,
      contentHashPayload: new TextEncoder().encode(payload),
      contentType: "application/json",
    });
    return Response.json(
      { data },
      { headers: { "Cache-Control": "private, no-store" } },
    );
  } catch {
    return Response.json(
      { error: "secret_update_failed" },
      { status: 502, headers: { "Cache-Control": "private, no-store" } },
    );
  }
}
