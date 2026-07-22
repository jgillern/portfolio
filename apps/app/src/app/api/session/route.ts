import { NextResponse } from "next/server";

import {
  createSessionValue,
  SESSION_COOKIE,
  verifyOwnerPassword,
} from "@/lib/auth";

export const runtime = "nodejs";

const ATTEMPT_WINDOW_MS = 15 * 60 * 1000;
const ATTEMPT_LIMIT = 5;
const attempts = new Map<string, { count: number; resetAt: number }>();

function clientKey(request: Request): string {
  return (
    request.headers.get("x-vercel-forwarded-for") ??
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    "unknown"
  );
}

function rateLimited(key: string, now = Date.now()): boolean {
  const state = attempts.get(key);
  if (!state || state.resetAt <= now) {
    attempts.set(key, { count: 1, resetAt: now + ATTEMPT_WINDOW_MS });
    return false;
  }
  state.count += 1;
  return state.count > ATTEMPT_LIMIT;
}

function audit(outcome: "success" | "failure" | "rate_limited"): void {
  console.info(
    JSON.stringify({
      event: "owner_session",
      outcome,
      occurred_at: new Date().toISOString(),
    }),
  );
}

function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  return Boolean(origin) && origin === new URL(request.url).origin;
}

export async function POST(request: Request): Promise<Response> {
  if (!sameOrigin(request)) {
    return NextResponse.json({ error: "invalid_origin" }, { status: 403 });
  }
  const key = clientKey(request);
  if (rateLimited(key)) {
    audit("rate_limited");
    return NextResponse.json(
      { error: "rate_limited" },
      {
        status: 429,
        headers: {
          "Cache-Control": "no-store",
          "Retry-After": String(ATTEMPT_WINDOW_MS / 1000),
        },
      },
    );
  }
  const contentType = request.headers.get("content-type") ?? "";
  let password = "";
  if (contentType.includes("application/json")) {
    const body = (await request.json()) as { password?: unknown };
    password = typeof body.password === "string" ? body.password : "";
  } else {
    const body = await request.formData();
    password = String(body.get("password") ?? "");
  }
  if (!verifyOwnerPassword(password)) {
    audit("failure");
    return NextResponse.json(
      { error: "invalid_credentials" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }
  attempts.delete(key);
  audit("success");
  const response = NextResponse.redirect(new URL("/", request.url), 303);
  response.cookies.set(SESSION_COOKIE, createSessionValue(), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: 60 * 60 * 12,
  });
  response.headers.set("Cache-Control", "no-store");
  return response;
}

export async function DELETE(request: Request): Promise<Response> {
  if (!sameOrigin(request)) {
    return NextResponse.json({ error: "invalid_origin" }, { status: 403 });
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
  response.headers.set("Cache-Control", "no-store");
  return response;
}
