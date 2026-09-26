import {
  clearAccessTokenCookie,
  clearProfileCookie,
  noStore,
  portalOidcConfig,
  portalOidcConfigured,
  readAccessToken,
  readBoundedJsonObject,
  readProfile,
} from "../../../../lib/server/portal-oidc.ts";

export const runtime = "nodejs";

function json(body: unknown, status = 200): Response {
  return noStore(Response.json(body, { status }));
}

export async function GET(request: Request) {
  if (!portalOidcConfigured()) {
    return json({ authenticated: false, reason: "not_configured" });
  }

  const config = portalOidcConfig();
  const token = readAccessToken(request);
  if (!token) {
    return json({ authenticated: false, portal_url: config.portalHomeUrl });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${config.interviewApiBaseUrl}/api/v1/identity/me`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
  } catch {
    return json({
      authenticated: false,
      reason: "upstream_unavailable",
      portal_url: config.portalHomeUrl,
    }, 503);
  }
  if (!upstream.ok) {
    const response = json({
      authenticated: false,
      reason: "upstream",
      status: upstream.status,
      portal_url: config.portalHomeUrl,
    }, upstream.status === 401 || upstream.status === 403 ? 401 : 502);
    if (upstream.status === 401 || upstream.status === 403) {
      response.headers.append("Set-Cookie", clearAccessTokenCookie());
      response.headers.append("Set-Cookie", clearProfileCookie());
    }
    return response;
  }

  const data = await readBoundedJsonObject(upstream, 8 * 1024);
  const accountId = typeof data?.account_id === "string" ? data.account_id : "";
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
    .test(accountId)) {
    return json({
      authenticated: false,
      reason: "invalid_upstream_response",
      portal_url: config.portalHomeUrl,
    }, 502);
  }
  const profile = readProfile(request);
  return json({
    authenticated: true,
    account_id: accountId,
    given_name: profile?.givenName ?? "",
    family_name: profile?.familyName ?? "",
    display_name: profile?.displayName ?? "",
    portal_url: config.portalHomeUrl,
  });
}
