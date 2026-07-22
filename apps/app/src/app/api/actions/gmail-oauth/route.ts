import { authorizeAction } from "@/lib/action-security";
import { callWorker } from "@/lib/worker-client";

export const runtime = "nodejs";

export async function POST(request: Request): Promise<Response> {
  const unauthorized = await authorizeAction(request);
  if (unauthorized) return unauthorized;
  try {
    const data = await callWorker({
      path: "/api/oauth/gmail/start",
      body: null,
      contentHashPayload: new Uint8Array(),
    });
    return Response.json(
      { data },
      { headers: { "Cache-Control": "private, no-store" } },
    );
  } catch {
    return Response.json(
      { error: "gmail_oauth_start_failed" },
      { status: 502, headers: { "Cache-Control": "private, no-store" } },
    );
  }
}
