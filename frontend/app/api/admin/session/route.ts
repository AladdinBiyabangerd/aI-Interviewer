import { adminConfigured, adminSession, adminSessionCookie, authenticateAdmin, clearAdminSessionCookie } from "../../../../lib/server/admin-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const noStore = { "Cache-Control": "no-store" };
let activePasswordChecks = 0;

async function boundedBody(request: Request): Promise<string | null> {
  const reader = request.body?.getReader();
  if (!reader) return "";
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > 2048) { await reader.cancel(); return null; }
    chunks.push(value);
  }
  return Buffer.concat(chunks).toString("utf8");
}

export async function GET(request: Request): Promise<Response> {
  return Response.json({ authenticated: Boolean(adminSession(request)), configured: adminConfigured() }, { headers: noStore });
}

export async function POST(request: Request): Promise<Response> {
  if (request.headers.get("origin") !== new URL(request.url).origin) {
    return Response.json({ code: "invalid_origin" }, { status: 403, headers: noStore });
  }
  if (!adminConfigured()) return Response.json({ code: "admin_not_configured" }, { status: 503, headers: noStore });
  if (!request.headers.get("content-type")?.startsWith("application/json")) {
    return Response.json({ code: "invalid_content_type" }, { status: 415, headers: noStore });
  }
  const raw = await boundedBody(request);
  if (raw === null) {
    return Response.json({ code: "request_too_large" }, { status: 413, headers: noStore });
  }
  let input: unknown;
  try { input = JSON.parse(raw); } catch { return Response.json({ code: "invalid_json" }, { status: 400, headers: noStore }); }
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return Response.json({ code: "invalid_credentials" }, { status: 401, headers: noStore });
  }
  const values = input as Record<string, unknown>;
  if (activePasswordChecks >= 4) return Response.json({ code: "rate_limited" }, { status: 429, headers: noStore });
  activePasswordChecks += 1;
  let valid = false;
  try { valid = await authenticateAdmin(values.username, values.password); }
  finally { activePasswordChecks -= 1; }
  if (!valid) {
    return Response.json({ code: "invalid_credentials" }, { status: 401, headers: noStore });
  }
  const response = Response.json({ authenticated: true }, { headers: noStore });
  response.headers.append("Set-Cookie", adminSessionCookie());
  return response;
}

export async function DELETE(request: Request): Promise<Response> {
  if (request.headers.get("origin") !== new URL(request.url).origin) {
    return Response.json({ code: "invalid_origin" }, { status: 403, headers: noStore });
  }
  const response = Response.json({ authenticated: false }, { headers: noStore });
  response.headers.append("Set-Cookie", clearAdminSessionCookie());
  return response;
}
