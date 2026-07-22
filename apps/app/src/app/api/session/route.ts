import { NextResponse } from "next/server";

import {
  createSessionValue,
  SESSION_COOKIE,
  verifyOwnerPassword,
} from "@/lib/auth";

export const runtime = "nodejs";

function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  return Boolean(origin) && origin === new URL(request.url).origin;
}

export async function POST(request: Request): Promise<Response> {
  if (!sameOrigin(request)) {
    return NextResponse.json({ error: "invalid_origin" }, { status: 403 });
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
    return NextResponse.json(
      { error: "invalid_credentials" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }
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
