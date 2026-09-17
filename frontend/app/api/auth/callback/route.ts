import { NextResponse } from "next/server";

import {
  accessTokenCookie,
  clearAccessTokenCookie,
  clearPkceCookie,
  clearProfileCookie,
  portalOidcConfig,
  portalOidcConfigured,
  profileCookie,
  profileFromIdToken,
  readPkcePayload,
} from "../../../../lib/server/portal-oidc";

export const runtime = "nodejs";

function redirectError(request: Request, code: string): NextResponse {
  const response = NextResponse.redirect(
    new URL(`/?sso_error=${encodeURIComponent(code)}`, request.url),
  );
  response.headers.append("Set-Cookie", clearPkceCookie());
  response.headers.append("Set-Cookie", clearAccessTokenCookie());
  response.headers.append("Set-Cookie", clearProfileCookie());
  return response;
}

function peekClaims(token: string): { iss?: string; aud?: string; typ?: string } {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return {};
    const json = Buffer.from(parts[1].replace(/-/g, "+").replace(/_/g, "/"), "base64").toString(
      "utf8",
    );
    const payload = JSON.parse(json) as { iss?: string; aud?: string };
    const headerJson = Buffer.from(parts[0].replace(/-/g, "+").replace(/_/g, "/"), "base64").toString(
      "utf8",
    );
    const header = JSON.parse(headerJson) as { typ?: string };
    return {
      iss: payload.iss,
      aud: typeof payload.aud === "string" ? payload.aud : undefined,
      typ: header.typ,
    };
  } catch {
    return {};
  }
}

export async function GET(request: Request) {
  if (!portalOidcConfigured()) {
    return NextResponse.json({ error: "portal_oidc_not_configured" }, { status: 503 });
  }

  const url = new URL(request.url);
  const code = url.searchParams.get("code") ?? "";
  const state = url.searchParams.get("state") ?? "";
  const oauthError = url.searchParams.get("error");
  if (oauthError) {
    return redirectError(request, oauthError);
  }

  const pkce = readPkcePayload(request);
  if (!code || !pkce || !state || state !== pkce.state) {
    return redirectError(request, "invalid_callback");
  }

  const config = portalOidcConfig();
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: config.redirectUri,
    client_id: config.clientId,
    code_verifier: pkce.verifier,
  });

  const tokenResponse = await fetch(config.tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body,
    cache: "no-store",
  });

  if (!tokenResponse.ok) {
    return redirectError(request, `token_exchange_${tokenResponse.status}`);
  }

  const payload = (await tokenResponse.json()) as {
    access_token?: string;
    id_token?: string;
    expires_in?: number;
  };
  if (!payload.access_token) {
    return redirectError(request, "missing_token");
  }

  const claims = peekClaims(payload.access_token);
  if (claims.typ && claims.typ.toLowerCase() !== "at+jwt") {
    return redirectError(request, "bad_token_typ");
  }

  const meResponse = await fetch(`${config.interviewApiBaseUrl}/api/v1/identity/me`, {
    headers: {
      Authorization: `Bearer ${payload.access_token}`,
      Accept: "application/json",
    },
    cache: "no-store",
  });
  if (!meResponse.ok) {
    const expectedIss = config.issuer;
    const hint =
      claims.iss && claims.iss !== expectedIss
        ? `iss_mismatch`
        : meResponse.status === 401
          ? "api_rejected_token"
          : `api_${meResponse.status}`;
    return redirectError(request, hint);
  }

  const maxAge = Math.max(60, Math.min(Number(payload.expires_in ?? 900), 3600));
  const profile = profileFromIdToken(payload.id_token);
  const response = NextResponse.redirect(new URL("/?sso=ok", request.url));
  response.headers.append("Set-Cookie", clearPkceCookie());
  response.headers.append("Set-Cookie", accessTokenCookie(payload.access_token, maxAge));
  if (profile) {
    response.headers.append("Set-Cookie", profileCookie(profile, maxAge));
  } else {
    response.headers.append("Set-Cookie", clearProfileCookie());
  }
  return response;
}
