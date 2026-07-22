import { authorizeAction } from "@/lib/action-security";
import { callWorker } from "@/lib/worker-client";

export const runtime = "nodejs";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const BROKERS = new Set(["PATRIA", "XTB", "GEORGE"]);
const CONTENT_TYPES = new Set([
  "text/html",
  "text/csv",
  "application/csv",
  "application/pdf",
]);

export async function POST(request: Request): Promise<Response> {
  const unauthorized = await authorizeAction(request);
  if (unauthorized) return unauthorized;

  const incoming = await request.formData();
  const brokerCode = String(incoming.get("broker_code") ?? "").toUpperCase();
  const accountRef = String(incoming.get("account_ref") ?? "");
  const document = incoming.get("document");
  if (
    !BROKERS.has(brokerCode) ||
    !accountRef ||
    accountRef.length > 120 ||
    !(document instanceof File) ||
    !CONTENT_TYPES.has(document.type) ||
    document.size < 1 ||
    document.size > MAX_UPLOAD_BYTES
  ) {
    return Response.json({ error: "invalid_upload" }, { status: 400 });
  }

  const payload = new Uint8Array(await document.arrayBuffer());
  const outbound = new FormData();
  outbound.set("broker_code", brokerCode);
  outbound.set("account_ref", accountRef);
  outbound.set(
    "document",
    new Blob([payload], { type: document.type }),
    document.name.slice(0, 160),
  );
  try {
    const data = await callWorker({
      path: "/api/import",
      body: outbound,
      contentHashPayload: payload,
    });
    return Response.json(
      { data },
      { headers: { "Cache-Control": "private, no-store" } },
    );
  } catch {
    return Response.json(
      { error: "import_failed" },
      { status: 502, headers: { "Cache-Control": "private, no-store" } },
    );
  }
}
