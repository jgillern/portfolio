import {
  createHash,
  createHmac,
  pbkdf2Sync,
  timingSafeEqual,
} from "node:crypto";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export const SESSION_COOKIE = "portfolio_session";
const SESSION_VERSION = "v1";
const SESSION_LIFETIME_SECONDS = 60 * 60 * 12;
const PASSWORD_ITERATIONS = 310_000;

function safeEqual(left: string, right: string): boolean {
  const leftBytes = Buffer.from(left, "utf8");
  const rightBytes = Buffer.from(right, "utf8");
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

function sessionSignature(expiresAt: string): string {
  const secret = process.env.SESSION_SIGNING_KEY;
  if (!secret) return "";
  return createHmac("sha256", secret)
    .update(SESSION_VERSION + "." + expiresAt)
    .digest("base64url");
}

export function createSessionValue(now = Date.now()): string {
  const expiresAt = String(Math.floor(now / 1000) + SESSION_LIFETIME_SECONDS);
  return [SESSION_VERSION, expiresAt, sessionSignature(expiresAt)].join(".");
}

export function verifySessionValue(value: string | undefined, now = Date.now()): boolean {
  if (!value) return false;
  const [version, expiresAt, signature] = value.split(".");
  if (version !== SESSION_VERSION || !expiresAt || !signature) return false;
  if (!/^\d+$/.test(expiresAt) || Number(expiresAt) < Math.floor(now / 1000)) return false;
  const expected = sessionSignature(expiresAt);
  return Boolean(expected) && safeEqual(signature, expected);
}

export function verifyOwnerPassword(password: string): boolean {
  const salt = process.env.OWNER_PASSWORD_SALT;
  const expected = process.env.OWNER_PASSWORD_HASH;
  if (!salt || !expected) return false;
  const actual = pbkdf2Sync(password, salt, PASSWORD_ITERATIONS, 32, "sha256").toString("hex");
  return safeEqual(actual, expected.toLowerCase());
}

function explicitPreviewBypass(): boolean {
  return (
    process.env.VERCEL_ENV === "preview" &&
    process.env.ALLOW_PREVIEW_AUTH_BYPASS === "true"
  );
}

export async function isOwnerAuthenticated(): Promise<boolean> {
  if (explicitPreviewBypass()) return true;
  const jar = await cookies();
  return verifySessionValue(jar.get(SESSION_COOKIE)?.value);
}

export async function requireOwner(): Promise<void> {
  if (!(await isOwnerAuthenticated())) redirect("/login");
}

export function verifyMcpBearer(authorization: string | null): boolean {
  const expectedHash = process.env.MCP_BEARER_TOKEN_HASH?.toLowerCase();
  if (!expectedHash || !authorization?.startsWith("Bearer ")) return false;
  const token = authorization.slice("Bearer ".length).trim();
  const actualHash = createHash("sha256").update(token).digest("hex");
  return safeEqual(actualHash, expectedHash);
}
