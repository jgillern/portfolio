import { isOwnerAuthenticated } from "./auth";

export async function authorizeAction(request: Request): Promise<Response | null> {
  if (!(await isOwnerAuthenticated())) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const origin = request.headers.get("origin");
  if (!origin || origin !== new URL(request.url).origin) {
    return Response.json({ error: "invalid_origin" }, { status: 403 });
  }
  return null;
}
