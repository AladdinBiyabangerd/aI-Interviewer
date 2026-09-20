import "server-only";

import { portalOidcConfig, portalOidcConfigured, readAccessToken, readProfile } from "./portal-oidc";

export type AdminIdentity = { accountId: string; name: string };

export async function adminSession(request: Request): Promise<AdminIdentity | null> {
  const token = readAccessToken(request);
  if (!token || !portalOidcConfigured()) return null;
  const allowed = process.env.INTERVIEW_ADMIN_ACCOUNT_IDS?.split(",").map((id) => id.trim().toLowerCase()) ?? [];
  if (!allowed.length) return null;
  try {
    const response = await fetch(`${portalOidcConfig().interviewApiBaseUrl}/api/v1/identity/me`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) return null;
    const body: unknown = await response.json();
    if (!body || typeof body !== "object" || Array.isArray(body)) return null;
    const accountId = (body as Record<string, unknown>).account_id;
    if (typeof accountId !== "string" || !/^[0-9a-f-]{36}$/i.test(accountId)
      || !allowed.includes(accountId.toLowerCase())) return null;
    return { accountId, name: readProfile(request)?.displayName ?? "Admin" };
  } catch {
    return null;
  }
}

export async function adminGuard(request: Request, write = false): Promise<Response | null> {
  if (!await adminSession(request)) return Response.json({ code: "admin_access_denied" }, {
    status: 403, headers: { "Cache-Control": "no-store" },
  });
  if (write && request.headers.get("origin") !== new URL(request.url).origin) {
    return Response.json({ code: "invalid_origin" }, {
      status: 403, headers: { "Cache-Control": "no-store" },
    });
  }
  return null;
}
