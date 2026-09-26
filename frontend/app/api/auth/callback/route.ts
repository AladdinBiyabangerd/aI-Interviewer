import {
  accessTokenCookie,
  clearAccessTokenCookie,
  clearPkceCookie,
  clearProfileCookie,
  noStore,
  portalOidcConfig,
  portalOidcConfigured,
  profileCookie,
  profileFromIdToken,
  readBoundedJsonObject,
  readPkcePayload,
} from "../../../../lib/server/portal-oidc.ts";

export const runtime = "nodejs";

function redirectError(config: ReturnType<typeof portalOidcConfig>, code: string): Response {
  const response = new Response(null, {
    status: 307,
    headers: {
      Location: new URL(`/?sso_error=${encodeURIComponent(code)}`, config.redirectUri).toString(),
    },
  });
  response.headers.append("Set-Cookie", clearPkceCookie());
  response.headers.append("Set-Cookie", clearAccessTokenCookie());
  response.headers.append("Set-Cookie", clearProfileCookie());
  return noStore(response);
}

function providerErrorCode(value: string): string {
  return ["access_denied", "consent_required", "interaction_required", "login_required"]
    .includes(value) ? value : "provider_error";
}

function accessTokenClaims(token: string): { iss?: string; aud: string[]; typ?: string } {
  try {
    const [encodedHeader, encodedPayload] = token.split(".");
    const header = JSON.parse(Buffer.from(encodedHeader, "base64url").toString("utf8")) as { typ?: string };
    const payload = JSON.parse(Buffer.from(encodedPayload, "base64url").toString("utf8")) as {
      iss?: string;
      aud?: string | string[];
    };
    return {
      iss: payload.iss,
      aud: Array.isArray(payload.aud) ? payload.aud : payload.aud ? [payload.aud] : [],
      typ: header.typ,
    };
  } catch {
    return { aud: [] };
  }
}

export async function GET(request: Request) {
  if (!portalOidcConfigured()) {
    return noStore(Response.json({ error: "portal_oidc_not_configured" }, { status: 503 }));
  }

  const config = portalOidcConfig();
  const url = new URL(request.url);
  const code = url.searchParams.get("code") ?? "";
  const state = url.searchParams.get("state") ?? "";
  const oauthError = url.searchParams.get("error");
  if (oauthError) return redirectError(config, providerErrorCode(oauthError));

  const pkce = readPkcePayload(request);
  if (!code || code.length > 4096 || !pkce || !state || state !== pkce.state) {
    return redirectError(config, "invalid_callback");
  }

  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: config.redirectUri,
    client_id: config.clientId,
    code_verifier: pkce.verifier,
  });

  let tokenResponse: Response;
  try {
    tokenResponse = await fetch(config.tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
  } catch {
    return redirectError(config, "token_exchange_unavailable");
  }
  if (!tokenResponse.ok) return redirectError(config, `token_exchange_${tokenResponse.status}`);

  const payload = await readBoundedJsonObject(tokenResponse, 64 * 1024);
  const accessToken = typeof payload?.access_token === "string" ? payload.access_token : "";
  const idToken = typeof payload?.id_token === "string" ? payload.id_token : undefined;
  const tokenType = typeof payload?.token_type === "string" ? payload.token_type : "";
  if (!accessToken || accessToken.length > 8192
    || (tokenType && tokenType.toLowerCase() !== "bearer")) {
    return redirectError(config, "invalid_token_response");
  }

  const claims = accessTokenClaims(accessToken);
  if (claims.typ?.toLowerCase() !== "at+jwt"
    || claims.iss !== config.issuer
    || !claims.aud.includes(config.interviewApiBaseUrl)) {
    return redirectError(config, "invalid_access_token_claims");
  }

  let meResponse: Response;
  try {
    meResponse = await fetch(`${config.interviewApiBaseUrl}/api/v1/identity/me`, {
      headers: { Authorization: `Bearer ${accessToken}`, Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
  } catch {
    return redirectError(config, "api_unavailable");
  }
  if (!meResponse.ok) return redirectError(config, `api_${meResponse.status}`);

  const expiresIn = Number(payload?.expires_in ?? 900);
  const maxAge = Number.isFinite(expiresIn) ? Math.max(60, Math.min(expiresIn, 3600)) : 900;
  let profile: Awaited<ReturnType<typeof profileFromIdToken>>;
  try {
    profile = await profileFromIdToken(idToken, pkce.nonce, config);
  } catch {
    return redirectError(config, "invalid_id_token");
  }
  const response = new Response(null, {
    status: 307,
    headers: { Location: new URL("/?sso=ok", config.redirectUri).toString() },
  });
  response.headers.append("Set-Cookie", clearPkceCookie());
  response.headers.append("Set-Cookie", accessTokenCookie(accessToken, maxAge));
  response.headers.append("Set-Cookie", profile ? profileCookie(profile, maxAge) : clearProfileCookie());
  return noStore(response);
}
