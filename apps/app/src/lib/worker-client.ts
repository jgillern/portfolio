import { createHash, createHmac, randomUUID } from "node:crypto";

type WorkerCall = {
  path: "/api/sync" | "/api/import" | "/api/secrets" | "/api/oauth/gmail/start";
  body: BodyInit | null;
  contentHashPayload: Uint8Array;
  contentType?: string;
  idempotencyKey?: string;
};

export async function callWorker({
  path,
  body,
  contentHashPayload,
  contentType,
  idempotencyKey,
}: WorkerCall): Promise<unknown> {
  const baseUrl = process.env.WORKER_BASE_URL;
  const signingKey = process.env.WORKER_SIGNING_KEY;
  if (!baseUrl || !signingKey) {
    throw new Error("Worker connection is not configured.");
  }

  const timestamp = String(Math.floor(Date.now() / 1000));
  const bodyHash = createHash("sha256").update(contentHashPayload).digest("hex");
  const signaturePayload = [timestamp, "POST", path, bodyHash].join("\n");
  const signature = createHmac("sha256", signingKey)
    .update(signaturePayload)
    .digest("hex");
  const headers = new Headers({
    "X-Portfolio-Timestamp": timestamp,
    "X-Portfolio-Signature": signature,
    "X-Portfolio-Content-Sha256": bodyHash,
    "X-Portfolio-Idempotency-Key": idempotencyKey ?? randomUUID(),
  });
  if (contentType) headers.set("Content-Type", contentType);

  const response = await fetch(new URL(path, baseUrl), {
    method: "POST",
    headers,
    body,
    cache: "no-store",
    redirect: "error",
  });
  if (!response.ok) {
    throw new Error("Worker request failed with status " + response.status + ".");
  }
  return response.json();
}
